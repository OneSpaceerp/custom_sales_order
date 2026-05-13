# Copyright (c) 2026, Nest Software Development and contributors
# For license information, please see license.txt

"""
Sales Order Cost controller.

A single Sales Order Cost document holds multiple cost line items
(child table ``cost_items`` → Sales Order Cost Item). On every save/delete
the linked Sales Order's ``custom_actual_cost`` is recalculated as the sum
of all cost items across all Sales Order Cost documents for that SO.
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
        self._fetch_order_number()
        self._resolve_payment_accounts()
        self._compute_total()

    def on_update(self):
        """Sync the SO's actual cost whenever this document is saved."""
        self._sync_actual_cost()

    def on_trash(self):
        """Sync the SO's actual cost when this document is deleted."""
        self._sync_actual_cost(exclude_self=True)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_order_number(self):
        """Copy the SO's custom_order_number (naming_series based) for easy filtering."""
        if self.sales_order:
            order_number = frappe.db.get_value(
                "Sales Order", self.sales_order, "custom_order_number"
            )
            self.custom_order_number = order_number or ""

    def _resolve_payment_accounts(self):
        """For each cost item, resolve the payment account from Mode of Payment."""
        if not self.cost_items:
            return

        for item in self.cost_items:
            if not item.mode_of_payment or not self.company:
                item.payment_account = None
                continue

            account = frappe.db.get_value(
                "Mode of Payment Account",
                {"parent": item.mode_of_payment, "company": self.company},
                "default_account",
            )

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
