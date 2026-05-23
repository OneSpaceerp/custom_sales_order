# Copyright (c) 2026, Nest Software Development and contributors
# For license information, please see license.txt

"""
Sales Order Cost controller.

A single Sales Order Cost document holds multiple cost line items
(child table ``cost_items`` → Sales Order Cost Item). On every save/delete
the actual cost is distributed **proportionally** across ALL Sales Orders
sharing the same ``custom_order_number``, weighted by each SO's ``grand_total``.

Journal Entries are generated **per cost item row** — each row gets its own
JE using the row's ``cost_date`` as the posting date.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

logger = frappe.logger("custom_sales_order")


class SalesOrderCost(Document):
    """Parent document containing itemized cost/expense lines for a Sales Order."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def validate(self):
        """Resolve payment accounts and compute the total."""
        self._resolve_sales_order()
        self._resolve_payment_accounts()
        self._compute_total()

    def on_update(self):
        """Sync actual cost across all SOs sharing this order number."""
        self._sync_actual_cost()

    def on_trash(self):
        """Cancel all linked JEs and sync actual cost when deleted."""
        self._cancel_all_journal_entries()
        self._sync_actual_cost(exclude_self=True)

    # ------------------------------------------------------------------
    # Public whitelisted methods — called from client JS
    # ------------------------------------------------------------------

    @frappe.whitelist()
    def generate_journal_entry(self):
        """Create one JE per cost item row, using each row's date as posting date.

        Called via ``frm.call("generate_journal_entry")`` from the client.
        """
        self._create_journal_entries()
        frappe.db.commit()

        # Collect all created JE names for the response
        je_names = [
            item.journal_entry
            for item in self.cost_items
            if item.journal_entry
        ]
        return {"journal_entries": je_names, "count": len(je_names)}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_sales_order(self):
        """Look up Sales Orders by order number.

        - If multiple SOs share the order number, store the first one in
          ``sales_order`` for backward compat and filtering.
        - If ``sales_order`` is set but ``custom_order_number`` is not,
          fetch the order number from the SO.
        """
        if self.custom_order_number and not self.sales_order:
            # Find all SOs with this order number, pick the first
            so_list = frappe.get_all(
                "Sales Order",
                filters={"custom_order_number": self.custom_order_number},
                fields=["name", "company"],
                order_by="creation ASC",
                limit_page_length=0,
            )
            if so_list:
                self.sales_order = so_list[0].name
            else:
                frappe.throw(
                    _("No Sales Order found with Order Number '{0}'.").format(
                        self.custom_order_number
                    )
                )
        elif self.sales_order and not self.custom_order_number:
            # Fetch order number from SO
            order_number = frappe.db.get_value(
                "Sales Order", self.sales_order, "custom_order_number"
            )
            self.custom_order_number = order_number or ""

        # Always fetch company from the primary SO
        if self.sales_order:
            self.company = frappe.db.get_value(
                "Sales Order", self.sales_order, "company"
            )

    def _resolve_payment_accounts(self):
        """For each cost item, resolve the payment account from Mode of Payment."""
        if not self.cost_items:
            return

        for item in self.cost_items:
            if not item.mode_of_payment or not self.company:
                item.payment_account = None
                continue

            account = _get_payment_account(item.mode_of_payment, self.company)

            if account:
                item.payment_account = account
            else:
                frappe.msgprint(
                    _(
                        "Row {0}: No default account found for Mode of Payment '{1}' "
                        "in company '{2}'. Please configure it in the Mode of Payment "
                        "master or set a Cost Clearing Account in Custom Sales Order Settings."
                    ).format(item.idx, item.mode_of_payment, self.company),
                    indicator="orange",
                    title=_("Payment Account Not Found"),
                )
                item.payment_account = None

    def _compute_total(self):
        """Sum all cost item amounts into total_amount."""
        self.total_amount = flt(
            sum(flt(item.amount) for item in (self.cost_items or [])), 2
        )

    def _sync_actual_cost(self, exclude_self=False):
        """Distribute total costs proportionally across ALL Sales Orders
        sharing the same ``custom_order_number``, weighted by ``grand_total``.

        Example: Order 1316 has 3 SOs with grand_totals 20k, 15k, 10k.
        Total cost = 30k.
        SO1 gets 20/45 * 30k = 13,333.33
        SO2 gets 15/45 * 30k = 10,000.00
        SO3 gets 10/45 * 30k = 6,666.67

        Parameters
        ----------
        exclude_self : bool
            If True, exclude this document's total from the sum
            (used in on_trash before the record is deleted).
        """
        if not self.custom_order_number:
            return

        try:
            # 1. Get ALL SOs sharing this order number with their grand_totals
            linked_sos = frappe.get_all(
                "Sales Order",
                filters={"custom_order_number": self.custom_order_number},
                fields=["name", "grand_total"],
                limit_page_length=0,
            )

            if not linked_sos:
                return

            # 2. Sum ALL cost items across ALL Sales Order Cost docs
            #    with the same custom_order_number
            total_cost = flt(
                frappe.db.sql(
                    """
                    SELECT COALESCE(SUM(ci.amount), 0)
                    FROM `tabSales Order Cost Item` ci
                    INNER JOIN `tabSales Order Cost` sc ON sc.name = ci.parent
                    WHERE sc.custom_order_number = %s
                    """,
                    self.custom_order_number,
                )[0][0]
            )

            if exclude_self:
                total_cost = flt(total_cost - flt(self.total_amount))

            # 3. Calculate total grand_total across all linked SOs
            total_grand = sum(flt(so.grand_total) for so in linked_sos)

            # 4. Distribute proportionally
            if total_grand > 0:
                for so in linked_sos:
                    proportion = flt(so.grand_total) / total_grand
                    so_cost = flt(total_cost * proportion, 2)

                    frappe.db.set_value(
                        "Sales Order",
                        so.name,
                        "custom_actual_cost",
                        so_cost,
                        update_modified=False,
                    )

                    logger.info(
                        "Distributed cost for SO %s: %s (%.1f%% of %s)",
                        so.name,
                        so_cost,
                        proportion * 100,
                        total_cost,
                    )
            else:
                # All SOs have zero grand_total — split equally
                equal_share = flt(total_cost / len(linked_sos), 2)
                for so in linked_sos:
                    frappe.db.set_value(
                        "Sales Order",
                        so.name,
                        "custom_actual_cost",
                        equal_share,
                        update_modified=False,
                    )

        except Exception:
            frappe.log_error(
                title=_("Failed to sync actual cost for order number {0}").format(
                    self.custom_order_number
                ),
                message=frappe.get_traceback(with_context=True),
            )

    def _create_journal_entries(self):
        """Create one JE per cost item row, each with its own posting date.

        Each JE has:
        - Debit: COGS Account for the row's amount
        - Credit: Row's payment account (or fallback clearing account)
        - Posting date: Row's cost_date
        """
        # 1. Read settings
        settings = frappe.get_single("Custom Sales Order Settings")

        if not settings.enable_cogs_je:
            frappe.msgprint(
                _("COGS Journal Entry posting is disabled in Settings."),
                indicator="orange",
            )
            return

        if not settings.cogs_account:
            frappe.throw(
                _(
                    "COGS Account is not configured in Custom Sales Order Settings. "
                    "Please set it before generating Journal Entries."
                )
            )

        if not self.cost_items or len(self.cost_items) == 0:
            frappe.throw(_("No cost items found. Please add cost items first."))

        # 2. Cancel all existing JEs first
        self._cancel_all_journal_entries()

        # 3. Create one JE per cost item row
        created_count = 0
        for item in self.cost_items:
            amount = flt(item.amount, 2)
            if amount <= 0:
                continue

            # Determine the credit account
            credit_account = item.payment_account or settings.cost_clearing_account
            if not credit_account:
                frappe.throw(
                    _(
                        "Row {0} ('{1}'): No payment account and no Cost Clearing "
                        "Account in Settings. Please configure a Mode of Payment "
                        "Account or set a fallback in Settings."
                    ).format(item.idx, item.description or "Unnamed")
                )

            # Build the JE
            je = frappe.new_doc("Journal Entry")
            je.posting_date = item.cost_date
            je.company = self.company
            je.user_remark = _(
                "COGS for Order #{0} — {1} | Row {2}: {3}"
            ).format(
                self.custom_order_number or "",
                self.name,
                item.idx,
                item.description or item.mode_of_payment or "Cost",
            )

            # DEBIT: COGS Account
            je.append(
                "accounts",
                {
                    "account": settings.cogs_account,
                    "debit_in_account_currency": amount,
                    "credit_in_account_currency": 0,
                },
            )

            # CREDIT: Payment Account
            je.append(
                "accounts",
                {
                    "account": credit_account,
                    "debit_in_account_currency": 0,
                    "credit_in_account_currency": amount,
                },
            )

            je.insert(ignore_permissions=True)
            je.submit()

            # Link the JE back to the child row
            frappe.db.set_value(
                "Sales Order Cost Item",
                item.name,
                "journal_entry",
                je.name,
                update_modified=False,
            )
            item.journal_entry = je.name
            created_count += 1

            logger.info(
                "Created JE %s (amount=%s, date=%s) for row %s of %s",
                je.name,
                amount,
                item.cost_date,
                item.idx,
                self.name,
            )

        # 4. Store the last JE on the parent for quick reference
        if created_count > 0:
            last_je = self.cost_items[-1].journal_entry if self.cost_items else None
            self.db_set("cogs_journal_entry", last_je, update_modified=False)
            self.cogs_journal_entry = last_je

        frappe.msgprint(
            _("{0} Journal Entries created successfully.").format(created_count),
            indicator="green",
        )

    def _cancel_all_journal_entries(self):
        """Cancel all JEs linked to cost item rows in this document."""
        for item in (self.cost_items or []):
            je_name = item.journal_entry
            if not je_name:
                continue

            if frappe.db.exists("Journal Entry", je_name):
                je_doc = frappe.get_doc("Journal Entry", je_name)
                if je_doc.docstatus == 1:
                    je_doc.cancel()
                    logger.info(
                        "Cancelled JE %s from %s row %s",
                        je_name,
                        self.name,
                        item.idx,
                    )

            frappe.db.set_value(
                "Sales Order Cost Item",
                item.name,
                "journal_entry",
                None,
                update_modified=False,
            )
            item.journal_entry = None

        # Clear the parent reference too
        self.db_set("cogs_journal_entry", None, update_modified=False)
        self.cogs_journal_entry = None


# ---------------------------------------------------------------------------
# Whitelisted utilities — called from client JS
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_payment_account(mode_of_payment, company):
    """Return the default account for a Mode of Payment in a given company.

    This is a whitelisted wrapper because ``frappe.client.get_value``
    does not reliably query child tables.
    """
    account = _get_payment_account(mode_of_payment, company)
    return {"payment_account": account or ""}


@frappe.whitelist()
def get_sales_order_from_order_number(order_number):
    """Look up ALL Sales Orders sharing a custom_order_number.

    Returns the primary SO (first by creation), company, and the full
    list of linked SOs with their grand_totals for the distribution preview.
    """
    so_list = frappe.get_all(
        "Sales Order",
        filters={"custom_order_number": order_number},
        fields=["name", "company", "grand_total", "customer_name"],
        order_by="creation ASC",
        limit_page_length=0,
    )

    if not so_list:
        return {"sales_order": "", "company": "", "linked_orders": [], "count": 0}

    return {
        "sales_order": so_list[0].name,
        "company": so_list[0].company,
        "linked_orders": [
            {
                "name": so.name,
                "grand_total": flt(so.grand_total),
                "customer_name": so.customer_name or "",
            }
            for so in so_list
        ],
        "count": len(so_list),
    }


def _get_payment_account(mode_of_payment, company):
    """Internal helper — query Mode of Payment Account child table."""
    if not mode_of_payment or not company:
        return None

    return frappe.db.get_value(
        "Mode of Payment Account",
        {
            "parent": mode_of_payment,
            "parenttype": "Mode of Payment",
            "company": company,
        },
        "default_account",
    )
