# Copyright (c) 2026, Nest Software Development and contributors
# For license information, please see license.txt

"""
Custom Sales Order controller override.

Injects COGS Journal Entry creation / cancellation into the standard
Sales Order lifecycle. Registered in hooks.py via ``override_doctype_class``.
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
    # Private helpers
    # ------------------------------------------------------------------

    def _sync_cogs_journal_entry(self):
        """Create or replace the COGS Journal Entry linked to this SO."""
        try:
            # 1. Read settings
            settings = frappe.get_single("Custom Sales Order Settings")

            # 2. Master switch
            if not settings.enable_cogs_je:
                return

            # 3. Account validation
            if not settings.cogs_account or not settings.cost_clearing_account:
                frappe.log_error(
                    title=_("Custom Sales Order Settings: accounts not configured"),
                    message=_(
                        "COGS Account and Cost Clearing Account must both be set "
                        "in Custom Sales Order Settings before COGS JEs can be posted."
                    ),
                )
                return

            # 4. Read cost fields
            expected = flt(self.get("custom_expected_cost") or 0)
            actual = flt(self.get("custom_actual_cost") or 0)
            completed = cint(self.get("custom_is_compleated") or 0)

            # 5. Calculate COGS
            cogs_value = calculate_cogs(expected, actual, completed)

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
            if cogs_value == 0:
                frappe.db.set_value(
                    "Sales Order",
                    self.name,
                    "custom_cogs_journal_entry",
                    None,
                    update_modified=False,
                )
                return

            # 8. Create new JE
            remark = describe_cogs_method(expected, actual, completed)
            je = frappe.new_doc("Journal Entry")
            je.posting_date = self.transaction_date
            je.company = self.company
            je.user_remark = _("COGS for {0} | {1}").format(self.name, remark)

            je.append(
                "accounts",
                {
                    "account": settings.cogs_account,
                    "debit_in_account_currency": cogs_value,
                    "credit_in_account_currency": 0,
                    "reference_type": "Sales Order",
                    "reference_name": self.name,
                },
            )
            je.append(
                "accounts",
                {
                    "account": settings.cost_clearing_account,
                    "debit_in_account_currency": 0,
                    "credit_in_account_currency": cogs_value,
                    "reference_type": "Sales Order",
                    "reference_name": self.name,
                },
            )

            je.insert(ignore_permissions=True)
            je.submit()

            logger.info(
                "Created COGS JE %s (amount=%s) for SO %s",
                je.name,
                cogs_value,
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
