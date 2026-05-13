# Copyright (c) 2026, Nest Software Development and contributors
# For license information, please see license.txt

"""
Custom Sales Order controller override.

Injects COGS Journal Entry creation / cancellation into the standard
Sales Order lifecycle. The JE is driven by ``Sales Order Cost Item``
rows (child table inside ``Sales Order Cost`` documents linked to this SO).

Registered in hooks.py via ``override_doctype_class``.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from erpnext.selling.doctype.sales_order.sales_order import SalesOrder

from custom_sales_order.utils.cogs_engine import (
    calculate_cogs,
    describe_cogs_method,
    validate_costs,
)

logger = frappe.logger("custom_sales_order")


class CustomSalesOrder(SalesOrder):
    """Extended Sales Order with automatic COGS Journal Entry posting."""

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    def validate(self):
        """Validate cost fields before save."""
        super().validate()

        expected = flt(self.get("custom_expected_cost") or 0)
        actual = flt(self.get("custom_actual_cost") or 0)
        completed = cint(self.get("custom_is_compleated") or 0)

        warnings = validate_costs(expected, actual, completed)
        for msg in warnings:
            if msg.startswith("ERROR"):
                frappe.throw(_(msg))
            elif msg.startswith("WARNING"):
                frappe.msgprint(_(msg), indicator="orange")

    def on_update(self):
        """Sync the COGS JE after every save."""
        if hasattr(super(), "on_update"):
            super().on_update()
        self._sync_cogs_journal_entry()

    def on_cancel(self):
        """Cancel the linked COGS JE when the Sales Order is cancelled."""
        super().on_cancel()
        self._cancel_cogs_journal_entry()

    # ------------------------------------------------------------------
    # Public whitelisted method — called from client JS
    # ------------------------------------------------------------------

    @frappe.whitelist()
    def generate_cogs_je(self):
        """Explicitly (re)generate the COGS Journal Entry from cost lines.

        Called via ``frm.call("generate_cogs_je")`` from the client.
        """
        self._sync_cogs_journal_entry()
        frappe.db.commit()
        # Reload the JE name from DB since _sync uses set_value (doesn't update self)
        je_name = frappe.db.get_value(
            "Sales Order", self.name, "custom_cogs_journal_entry"
        )
        return {"je": je_name}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_cost_items(self):
        """Fetch all cost item rows from Sales Order Cost documents linked to this SO.

        Returns a list of dicts with keys:
        description, amount, cost_date, mode_of_payment, payment_account
        """
        return frappe.db.sql(
            """
            SELECT
                ci.description,
                ci.amount,
                ci.cost_date,
                ci.mode_of_payment,
                ci.payment_account
            FROM `tabSales Order Cost Item` ci
            INNER JOIN `tabSales Order Cost` sc ON sc.name = ci.parent
            WHERE sc.sales_order = %s
            ORDER BY ci.cost_date ASC, ci.idx ASC
            """,
            self.name,
            as_dict=True,
        )

    def _sync_cogs_journal_entry(self):
        """Create or replace the COGS Journal Entry from Sales Order Cost items."""
        try:
            # 1. Read settings
            settings = frappe.get_single("Custom Sales Order Settings")

            # 2. Master switch
            if not settings.enable_cogs_je:
                return

            # 3. COGS account validation
            if not settings.cogs_account:
                frappe.log_error(
                    title=_("Custom Sales Order Settings: COGS account not configured"),
                    message=_(
                        "COGS Account must be set in Custom Sales Order Settings "
                        "before COGS JEs can be posted."
                    ),
                )
                return

            # 4. Fetch all cost items for this SO
            cost_items = self._get_cost_items()

            # 5. Calculate total COGS
            if cost_items:
                total_cogs = flt(sum(flt(c.amount) for c in cost_items), 2)
            else:
                # Legacy fallback — field-based calculation
                expected = flt(self.get("custom_expected_cost") or 0)
                actual = flt(self.get("custom_actual_cost") or 0)
                completed = cint(self.get("custom_is_compleated") or 0)
                total_cogs = calculate_cogs(expected, actual, completed)

            # 6. Cancel old JE if present
            old_je = self.get("custom_cogs_journal_entry")
            if old_je and frappe.db.exists("Journal Entry", old_je):
                je_doc = frappe.get_doc("Journal Entry", old_je)
                if je_doc.docstatus == 1:
                    je_doc.cancel()
                    logger.info(
                        "Cancelled old COGS JE %s for SO %s", old_je, self.name
                    )

            # 7. If COGS is zero, clear the link and return
            if total_cogs == 0:
                frappe.db.set_value(
                    "Sales Order",
                    self.name,
                    "custom_cogs_journal_entry",
                    None,
                    update_modified=False,
                )
                return

            # 8. Build the Journal Entry
            je = frappe.new_doc("Journal Entry")
            je.posting_date = self.transaction_date
            je.company = self.company

            # --- Build remark ---
            if cost_items:
                remark_parts = []
                for c in cost_items:
                    desc = c.description or c.mode_of_payment or "Cost"
                    remark_parts.append(f"{desc}: {flt(c.amount, 2)}")
                remark = " | ".join(remark_parts)
                je.user_remark = _("COGS for {0} | {1}").format(self.name, remark)
            else:
                expected = flt(self.get("custom_expected_cost") or 0)
                actual = flt(self.get("custom_actual_cost") or 0)
                completed = cint(self.get("custom_is_compleated") or 0)
                remark = describe_cogs_method(expected, actual, completed)
                je.user_remark = _("COGS for {0} | {1}").format(self.name, remark)

            # --- DEBIT side: COGS Account for the total ---
            je.append(
                "accounts",
                {
                    "account": settings.cogs_account,
                    "debit_in_account_currency": total_cogs,
                    "credit_in_account_currency": 0,
                    "reference_type": "Sales Order",
                    "reference_name": self.name,
                },
            )

            # --- CREDIT side ---
            if cost_items:
                # Group amounts by payment account
                account_totals = {}
                for c in cost_items:
                    acct = c.payment_account or settings.cost_clearing_account
                    if not acct:
                        frappe.throw(
                            _(
                                "Cost item '{0}' has no payment account and no "
                                "Cost Clearing Account is set in Settings. "
                                "Please configure a Mode of Payment Account or "
                                "set a fallback Cost Clearing Account."
                            ).format(c.description or "Unnamed")
                        )
                    account_totals[acct] = flt(
                        account_totals.get(acct, 0) + flt(c.amount), 2
                    )

                for acct, amount in account_totals.items():
                    je.append(
                        "accounts",
                        {
                            "account": acct,
                            "debit_in_account_currency": 0,
                            "credit_in_account_currency": amount,
                            "reference_type": "Sales Order",
                            "reference_name": self.name,
                        },
                    )
            else:
                # Legacy fallback — single clearing account
                clearing_acct = settings.cost_clearing_account
                if not clearing_acct:
                    frappe.log_error(
                        title=_("Missing Cost Clearing Account"),
                        message=_(
                            "No cost items found and no Cost Clearing Account "
                            "configured in Settings for SO {0}."
                        ).format(self.name),
                    )
                    return

                je.append(
                    "accounts",
                    {
                        "account": clearing_acct,
                        "debit_in_account_currency": 0,
                        "credit_in_account_currency": total_cogs,
                        "reference_type": "Sales Order",
                        "reference_name": self.name,
                    },
                )

            je.insert(ignore_permissions=True)
            je.submit()

            logger.info(
                "Created COGS JE %s (amount=%s, items=%s) for SO %s",
                je.name,
                total_cogs,
                len(cost_items) or "legacy",
                self.name,
            )

            # 9. Link the JE back to the SO
            frappe.db.set_value(
                "Sales Order",
                self.name,
                "custom_cogs_journal_entry",
                je.name,
                update_modified=False,
            )

        except Exception as e:
            frappe.log_error(
                title=_("COGS JE Error for {0}").format(self.name),
                message=frappe.get_traceback(with_context=True),
            )
            logger.error(
                "Failed to sync COGS JE for SO %s: %s", self.name, str(e)
            )

    def _cancel_cogs_journal_entry(self):
        """Cancel and unlink the COGS Journal Entry on SO cancellation."""
        try:
            je_name = self.get("custom_cogs_journal_entry")
            if je_name and frappe.db.exists("Journal Entry", je_name):
                je_doc = frappe.get_doc("Journal Entry", je_name)
                if je_doc.docstatus == 1:
                    je_doc.cancel()
                    logger.info(
                        "Cancelled COGS JE %s on SO %s cancellation",
                        je_name,
                        self.name,
                    )

            frappe.db.set_value(
                "Sales Order",
                self.name,
                "custom_cogs_journal_entry",
                None,
                update_modified=False,
            )

        except Exception as e:
            frappe.log_error(
                title=_("COGS JE Cancel Error for {0}").format(self.name),
                message=frappe.get_traceback(with_context=True),
            )
            logger.error(
                "Failed to cancel COGS JE for SO %s: %s", self.name, str(e)
            )
