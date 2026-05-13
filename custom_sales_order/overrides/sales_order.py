# Copyright (c) 2026, Nest Software Development and contributors
# For license information, please see license.txt

"""
Custom Sales Order controller override.

Injects COGS Journal Entry creation / cancellation into the standard
Sales Order lifecycle. The JE is now driven by ``Sales Order Cost`` line
items — each cost line specifies a description, amount, date, and Mode of
Payment whose default account becomes the credit leg of the JE.

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

    def _sync_cogs_journal_entry(self):
        """Create or replace the COGS Journal Entry from Sales Order Cost lines."""
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

            # 4. Fetch all cost lines for this SO
            cost_lines = frappe.get_all(
                "Sales Order Cost",
                filters={"sales_order": self.name},
                fields=["name", "description", "amount", "cost_date",
                        "mode_of_payment", "payment_account"],
                order_by="cost_date asc",
            )

            # 5. Calculate total COGS from cost lines
            total_cogs = flt(sum(flt(c.amount) for c in cost_lines), 2)

            # 6. If no cost lines, fall back to the legacy field-based calculation
            if not cost_lines:
                expected = flt(self.get("custom_expected_cost") or 0)
                actual = flt(self.get("custom_actual_cost") or 0)
                completed = cint(self.get("custom_is_compleated") or 0)
                total_cogs = calculate_cogs(expected, actual, completed)

            # 7. Cancel old JE if present
            old_je = self.get("custom_cogs_journal_entry")
            if old_je and frappe.db.exists("Journal Entry", old_je):
                je_doc = frappe.get_doc("Journal Entry", old_je)
                if je_doc.docstatus == 1:
                    je_doc.cancel()
                    logger.info(
                        "Cancelled old COGS JE %s for SO %s", old_je, self.name
                    )

            # 8. If COGS is zero, clear the link and return
            if total_cogs == 0:
                frappe.db.set_value(
                    "Sales Order",
                    self.name,
                    "custom_cogs_journal_entry",
                    None,
                    update_modified=False,
                )
                return

            # 9. Build the Journal Entry
            je = frappe.new_doc("Journal Entry")
            je.posting_date = self.transaction_date
            je.company = self.company

            # --- DEBIT side: COGS Account for the total ---
            if cost_lines:
                remark_parts = []
                for c in cost_lines:
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

            # --- CREDIT side: grouped by payment account ---
            if cost_lines:
                # Group amounts by payment account
                account_totals = {}
                for c in cost_lines:
                    acct = c.payment_account or settings.cost_clearing_account
                    if not acct:
                        frappe.throw(
                            _(
                                "Cost line '{0}' has no payment account and no "
                                "Cost Clearing Account is set in Settings. "
                                "Please configure a Mode of Payment Account or "
                                "set a fallback Cost Clearing Account."
                            ).format(c.description or c.name)
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
                            "No cost lines found and no Cost Clearing Account "
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
                "Created COGS JE %s (amount=%s, lines=%s) for SO %s",
                je.name,
                total_cogs,
                len(cost_lines) or "legacy",
                self.name,
            )

            # 10. Link the JE back to the SO
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
