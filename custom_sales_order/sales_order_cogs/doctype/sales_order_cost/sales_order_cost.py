# Copyright (c) 2026, Nest Software Development and contributors
# For license information, please see license.txt

"""
Sales Order Cost controller.

A single Sales Order Cost document holds multiple cost line items
(child table ``cost_items`` → Sales Order Cost Item). On every save/delete
the linked Sales Order's ``custom_actual_cost`` is recalculated as the sum
of all cost items across all Sales Order Cost documents for that SO.

The Journal Entry is generated directly from this document, with:
  - Debit: COGS Account (from settings) for the total amount
  - Credit: Grouped by payment account (from Mode of Payment per company)
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
        """Sync the SO's actual cost whenever this document is saved."""
        self._sync_actual_cost()

    def on_trash(self):
        """Cancel linked JE and sync SO actual cost when this document is deleted."""
        self._cancel_journal_entry()
        self._sync_actual_cost(exclude_self=True)

    # ------------------------------------------------------------------
    # Public whitelisted methods — called from client JS
    # ------------------------------------------------------------------

    @frappe.whitelist()
    def generate_journal_entry(self):
        """Create (or recreate) the COGS Journal Entry from this document's cost items.

        Called via ``frm.call("generate_journal_entry")`` from the client.
        """
        self._create_journal_entry()
        frappe.db.commit()
        return {"je": self.cogs_journal_entry}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_sales_order(self):
        """If custom_order_number is set but sales_order is not, look up the SO.
        If sales_order is set, fetch the order number from it.
        """
        if self.custom_order_number and not self.sales_order:
            # Look up SO by custom_order_number
            so_name = frappe.db.get_value(
                "Sales Order",
                {"custom_order_number": self.custom_order_number},
                "name",
            )
            if so_name:
                self.sales_order = so_name
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

        # Always fetch company from SO
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
        """Update the Sales Order's custom_actual_cost with the sum of all
        cost items across ALL Sales Order Cost documents for this SO.

        Parameters
        ----------
        exclude_self : bool
            If True, exclude this document's total from the sum
            (used in on_trash before the record is deleted).
        """
        if not self.sales_order:
            return

        try:
            # Sum cost_items.amount from all Sales Order Cost docs for this SO
            total = flt(
                frappe.db.sql(
                    """
                    SELECT COALESCE(SUM(ci.amount), 0)
                    FROM `tabSales Order Cost Item` ci
                    INNER JOIN `tabSales Order Cost` sc ON sc.name = ci.parent
                    WHERE sc.sales_order = %s
                    """,
                    self.sales_order,
                )[0][0]
            )

            if exclude_self:
                total = flt(total - flt(self.total_amount))

            frappe.db.set_value(
                "Sales Order",
                self.sales_order,
                "custom_actual_cost",
                total,
                update_modified=False,
            )

            logger.info(
                "Updated custom_actual_cost for SO %s to %s",
                self.sales_order,
                total,
            )

        except Exception:
            frappe.log_error(
                title=_("Failed to sync actual cost for SO {0}").format(
                    self.sales_order
                ),
                message=frappe.get_traceback(with_context=True),
            )

    def _create_journal_entry(self):
        """Create the COGS Journal Entry from this document's cost items.

        - Debit: COGS Account for the total amount
        - Credit: One line per distinct payment account, grouped and summed
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
                    "Please set it before generating a Journal Entry."
                )
            )

        if not self.cost_items or len(self.cost_items) == 0:
            frappe.throw(_("No cost items found. Please add cost items first."))

        total_amount = flt(self.total_amount, 2)
        if total_amount <= 0:
            frappe.throw(_("Total amount must be greater than zero."))

        # 2. Cancel old JE if present
        self._cancel_journal_entry()

        # 3. Build the Journal Entry
        je = frappe.new_doc("Journal Entry")
        je.posting_date = self.posting_date
        je.company = self.company

        # Build remark from cost item descriptions
        remark_parts = []
        for item in self.cost_items:
            desc = item.description or item.mode_of_payment or "Cost"
            remark_parts.append(f"{desc}: {flt(item.amount, 2)}")
        remark = " | ".join(remark_parts)
        je.user_remark = _("COGS for SO {0} — {1} | {2}").format(
            self.sales_order or "", self.name, remark
        )

        # --- DEBIT side: COGS Account for the total ---
        je.append(
            "accounts",
            {
                "account": settings.cogs_account,
                "debit_in_account_currency": total_amount,
                "credit_in_account_currency": 0,
                "reference_type": "Sales Order",
                "reference_name": self.sales_order,
            },
        )

        # --- CREDIT side: grouped by payment account ---
        account_totals = {}
        for item in self.cost_items:
            acct = item.payment_account or settings.cost_clearing_account
            if not acct:
                frappe.throw(
                    _(
                        "Row {0} ('{1}'): No payment account and no Cost Clearing "
                        "Account in Settings. Please configure a Mode of Payment "
                        "Account or set a fallback in Settings."
                    ).format(item.idx, item.description or "Unnamed")
                )
            account_totals[acct] = flt(
                account_totals.get(acct, 0) + flt(item.amount), 2
            )

        for acct, amount in account_totals.items():
            je.append(
                "accounts",
                {
                    "account": acct,
                    "debit_in_account_currency": 0,
                    "credit_in_account_currency": amount,
                    "reference_type": "Sales Order",
                    "reference_name": self.sales_order,
                },
            )

        je.insert(ignore_permissions=True)
        je.submit()

        logger.info(
            "Created COGS JE %s (amount=%s) from %s for SO %s",
            je.name,
            total_amount,
            self.name,
            self.sales_order,
        )

        # 4. Link the JE to this document and to the SO
        self.db_set("cogs_journal_entry", je.name, update_modified=False)
        self.cogs_journal_entry = je.name

        if self.sales_order:
            frappe.db.set_value(
                "Sales Order",
                self.sales_order,
                "custom_cogs_journal_entry",
                je.name,
                update_modified=False,
            )

    def _cancel_journal_entry(self):
        """Cancel the linked Journal Entry if it exists and is submitted."""
        je_name = self.cogs_journal_entry
        if not je_name:
            return

        if frappe.db.exists("Journal Entry", je_name):
            je_doc = frappe.get_doc("Journal Entry", je_name)
            if je_doc.docstatus == 1:
                je_doc.cancel()
                logger.info(
                    "Cancelled JE %s from %s", je_name, self.name
                )

        self.db_set("cogs_journal_entry", None, update_modified=False)
        self.cogs_journal_entry = None

        # Clear SO link too
        if self.sales_order:
            # Only clear if the SO still points to this JE
            so_je = frappe.db.get_value(
                "Sales Order", self.sales_order, "custom_cogs_journal_entry"
            )
            if so_je == je_name:
                frappe.db.set_value(
                    "Sales Order",
                    self.sales_order,
                    "custom_cogs_journal_entry",
                    None,
                    update_modified=False,
                )


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
    """Look up a Sales Order by its custom_order_number field.

    Returns the SO name and company, or empty values if not found.
    """
    result = frappe.db.get_value(
        "Sales Order",
        {"custom_order_number": order_number},
        ["name", "company"],
        as_dict=True,
    )
    if result:
        return {"sales_order": result.name, "company": result.company}
    return {"sales_order": "", "company": ""}


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
