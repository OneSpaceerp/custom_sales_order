# Copyright (c) 2026, Nest Software Development and contributors
# For license information, please see license.txt

"""
Sales Order COGS Summary — Script Report.

Displays each Sales Order alongside its expected/actual costs, the COGS
that would (or has been) posted, gross profit, and margin percentage.
Includes cost item count from the Sales Order Cost child tables.
"""

import frappe
from frappe import _
from frappe.utils import flt

from custom_sales_order.utils.cogs_engine import calculate_cogs


def execute(filters=None):
    """Entry point called by the Frappe report runner.

    Returns
    -------
    tuple[list[dict], list[dict]]
        ``(columns, data)``
    """
    filters = filters or {}
    columns = _get_columns()
    data = _get_data(filters)
    return columns, data


# ---------------------------------------------------------------------------
# Column definitions
# ---------------------------------------------------------------------------


def _get_columns():
    """Return the report column list in the specified order."""
    return [
        {
            "fieldname": "sales_order",
            "label": _("Sales Order"),
            "fieldtype": "Link",
            "options": "Sales Order",
            "width": 160,
        },
        {
            "fieldname": "customer",
            "label": _("Customer"),
            "fieldtype": "Link",
            "options": "Customer",
            "width": 140,
        },
        {
            "fieldname": "transaction_date",
            "label": _("Order Date"),
            "fieldtype": "Date",
            "width": 110,
        },
        {
            "fieldname": "grand_total",
            "label": _("Revenue"),
            "fieldtype": "Currency",
            "options": "Company:company:default_currency",
            "width": 130,
        },
        {
            "fieldname": "expected_cost",
            "label": _("Expected Cost"),
            "fieldtype": "Currency",
            "options": "Company:company:default_currency",
            "width": 130,
        },
        {
            "fieldname": "actual_cost",
            "label": _("Actual Cost"),
            "fieldtype": "Currency",
            "options": "Company:company:default_currency",
            "width": 130,
        },
        {
            "fieldname": "cost_item_count",
            "label": _("Cost Items"),
            "fieldtype": "Int",
            "width": 90,
        },
        {
            "fieldname": "cogs_applied",
            "label": _("COGS Applied"),
            "fieldtype": "Currency",
            "options": "Company:company:default_currency",
            "width": 130,
        },
        {
            "fieldname": "gross_profit",
            "label": _("Gross Profit"),
            "fieldtype": "Currency",
            "options": "Company:company:default_currency",
            "width": 130,
        },
        {
            "fieldname": "margin_pct",
            "label": _("Margin %"),
            "fieldtype": "Percent",
            "width": 100,
        },
        {
            "fieldname": "status",
            "label": _("Status"),
            "fieldtype": "Data",
            "width": 100,
        },
        {
            "fieldname": "cogs_je",
            "label": _("COGS Journal Entry"),
            "fieldtype": "Link",
            "options": "Journal Entry",
            "width": 160,
        },
    ]


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def _get_data(filters):
    """Fetch Sales Orders and compute COGS / profit metrics."""
    conditions = ["so.docstatus < 2"]  # exclude cancelled / trashed
    values = {}

    if filters.get("company"):
        conditions.append("so.company = %(company)s")
        values["company"] = filters["company"]

    if filters.get("customer"):
        conditions.append("so.customer = %(customer)s")
        values["customer"] = filters["customer"]

    if filters.get("from_date"):
        conditions.append("so.transaction_date >= %(from_date)s")
        values["from_date"] = filters["from_date"]

    if filters.get("to_date"):
        conditions.append("so.transaction_date <= %(to_date)s")
        values["to_date"] = filters["to_date"]

    status_filter = filters.get("status")
    if status_filter == "In Progress":
        conditions.append("so.custom_is_compleated = 0")
    elif status_filter == "Completed":
        conditions.append("so.custom_is_compleated = 1")

    where_clause = " AND ".join(conditions)

    rows = frappe.db.sql(
        f"""
        SELECT
            so.name                              AS sales_order,
            so.customer,
            so.transaction_date,
            so.grand_total,
            so.company,
            COALESCE(so.custom_expected_cost, 0) AS expected_cost,
            COALESCE(so.custom_actual_cost, 0)   AS actual_cost,
            so.custom_is_compleated              AS is_completed,
            so.custom_cogs_journal_entry         AS cogs_je,
            (
                SELECT COUNT(*)
                FROM `tabSales Order Cost Item` ci
                INNER JOIN `tabSales Order Cost` sc ON sc.name = ci.parent
                WHERE sc.sales_order = so.name
            ) AS cost_item_count,
            (
                SELECT COALESCE(SUM(ci.amount), 0)
                FROM `tabSales Order Cost Item` ci
                INNER JOIN `tabSales Order Cost` sc ON sc.name = ci.parent
                WHERE sc.sales_order = so.name
            ) AS cost_item_total
        FROM `tabSales Order` so
        WHERE {where_clause}
        ORDER BY so.transaction_date DESC
        """,
        values,
        as_dict=True,
    )

    data = []
    for r in rows:
        # Use cost item total if cost items exist, otherwise use engine calculation
        if r.cost_item_count and r.cost_item_count > 0:
            cogs = flt(r.cost_item_total, 2)
        else:
            cogs = calculate_cogs(
                flt(r.expected_cost), flt(r.actual_cost), bool(r.is_completed)
            )

        revenue = flt(r.grand_total)
        profit = flt(revenue - cogs, 2)
        margin_pct = flt(profit / revenue * 100, 2) if revenue else 0

        data.append(
            {
                "sales_order": r.sales_order,
                "customer": r.customer,
                "transaction_date": r.transaction_date,
                "grand_total": revenue,
                "expected_cost": flt(r.expected_cost, 2),
                "actual_cost": flt(r.actual_cost, 2),
                "cost_item_count": r.cost_item_count or 0,
                "cogs_applied": flt(cogs, 2),
                "gross_profit": profit,
                "margin_pct": margin_pct,
                "status": _("Completed") if r.is_completed else _("In Progress"),
                "cogs_je": r.cogs_je,
            }
        )

    return data
