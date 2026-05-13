# Copyright (c) 2026, Nest Software Development and contributors
# For license information, please see license.txt

"""
Patch: Ensure Custom Sales Order Settings singleton exists.

Idempotent — safe to run multiple times.
"""

import frappe


def execute():
    """Create the settings singleton if the DocType exists but has no record."""
    if frappe.db.exists("DocType", "Custom Sales Order Settings"):
        if not frappe.db.exists(
            "Custom Sales Order Settings", "Custom Sales Order Settings"
        ):
            frappe.new_doc("Custom Sales Order Settings").insert(
                ignore_permissions=True
            )
            frappe.db.commit()
