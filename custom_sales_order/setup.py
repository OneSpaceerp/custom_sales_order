# Copyright (c) 2026, Nest Software Development and contributors
# For license information, please see license.txt

"""Post-install and post-migrate hooks to ensure custom fields and settings exist."""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def after_install():
    """Called once after `bench install-app custom_sales_order`."""
    _ensure_custom_fields()
    _ensure_settings()


def after_migrate():
    """Called after every `bench migrate`."""
    _ensure_custom_fields()
    _ensure_settings()


def _ensure_custom_fields():
    """Create the custom_cogs_journal_entry field on Sales Order if it doesn't exist."""
    custom_fields = {
        "Sales Order": [
            {
                "fieldname": "custom_cogs_journal_entry",
                "fieldtype": "Link",
                "options": "Journal Entry",
                "label": "COGS Journal Entry",
                "read_only": 1,
                "insert_after": "custom_is_compleated",
                "module": "Sales Order COGS",
                "translatable": 0,
            },
        ],
    }
    create_custom_fields(custom_fields, ignore_validate=True)
    frappe.db.commit()
    frappe.logger("custom_sales_order").info(
        _("Ensured custom_cogs_journal_entry field on Sales Order.")
    )


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
