# Copyright (c) 2026, Nest Software Development and contributors
# For license information, please see license.txt

"""Post-install and post-migrate hooks to ensure the Settings singleton exists."""

import frappe
from frappe import _


def after_install():
    """Called once after `bench install-app custom_sales_order`."""
    _ensure_settings()


def after_migrate():
    """Called after every `bench migrate`."""
    _ensure_settings()


def _ensure_settings():
    """Create the Custom Sales Order Settings singleton if it does not yet exist."""
    if frappe.db.exists("DocType", "Custom Sales Order Settings"):
        if not frappe.db.exists(
            "Custom Sales Order Settings", "Custom Sales Order Settings"
        ):
            frappe.new_doc("Custom Sales Order Settings").insert(
                ignore_permissions=True
            )
            frappe.db.commit()
            frappe.logger("custom_sales_order").info(
                _("Custom Sales Order Settings singleton created.")
            )
