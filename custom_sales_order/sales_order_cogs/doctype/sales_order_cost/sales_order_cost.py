# Copyright (c) 2026, Nest Software Development and contributors
# For license information, please see license.txt

"""
Sales Order Cost controller.

Each record represents a single expense/cost line against a Sales Order.
When cost lines are created, updated, or deleted the linked Sales Order's
``custom_actual_cost`` is recalculated as the sum of all its cost lines.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

logger = frappe.logger("custom_sales_order")


class SalesOrderCost(Document):
    """Individual cost/expense entry linked to a Sales Order."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def validate(self):
        """Validate amount and resolve the payment account from Mode of Payment."""
        self._validate_amount()
        self._resolve_payment_account()

    def on_update(self):
        """Recalculate the SO's actual cost whenever a cost line is saved."""
        self._sync_actual_cost()

    def on_trash(self):
        """Recalculate the SO's actual cost when a cost line is deleted."""
        self._sync_actual_cost(exclude_self=True)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate_amount(self):
        """Ensure amount is positive."""
        if flt(self.amount) <= 0:
            frappe.throw(
                _("Amount must be greater than zero."),
                title=_("Invalid Amount"),
            )

    def _resolve_payment_account(self):
        """Fetch the default account from Mode of Payment Account for this company."""
        if not self.mode_of_payment or not self.company:
            self.payment_account = None
            return

        account = frappe.db.get_value(
            "Mode of Payment Account",
            {"parent": self.mode_of_payment, "company": self.company},
            "default_account",
        )

        if account:
            self.payment_account = account
        else:
            frappe.msgprint(
                _(
                    "No default account found for Mode of Payment '{0}' "
                    "in company '{1}'. Please configure it in the Mode of Payment "
                    "master or set a Cost Clearing Account in Custom Sales Order Settings."
                ).format(self.mode_of_payment, self.company),
                indicator="orange",
                title=_("Payment Account Not Found"),
            )
            self.payment_account = None

    def _sync_actual_cost(self, exclude_self=False):
        """Update the Sales Order's custom_actual_cost with the sum of all linked costs.

        Parameters
        ----------
        exclude_self : bool
            If ``True``, exclude this document's amount from the total
            (used in ``on_trash`` before the record is actually deleted).
        """
        if not self.sales_order:
            return

        try:
            total = flt(
                frappe.db.sql(
                    """
                    SELECT COALESCE(SUM(amount), 0)
                    FROM `tabSales Order Cost`
                    WHERE sales_order = %s
                    """,
                    self.sales_order,
                )[0][0]
            )

            if exclude_self:
                total = flt(total - flt(self.amount))

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
