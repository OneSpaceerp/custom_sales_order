# Copyright (c) 2026, Nest Software Development and contributors
# For license information, please see license.txt

app_name = "custom_sales_order"
app_title = "Custom Sales Order COGS"
app_publisher = "Nest Software Development"
app_description = "Dynamic COGS Engine — posts Journal Entries from Sales Order cost fields"
app_email = "dev@nestsoftware.com"
app_license = "MIT"
required_apps = ["frappe", "erpnext"]

# --------------------------------------------------------------------------
# Client-side includes
# --------------------------------------------------------------------------
app_include_js = ["/assets/custom_sales_order/js/custom_sales_order.js"]

# --------------------------------------------------------------------------
# DocType class overrides
# --------------------------------------------------------------------------
override_doctype_class = {
    "Sales Order": "custom_sales_order.overrides.sales_order.CustomSalesOrder"
}

# --------------------------------------------------------------------------
# Fixtures — deployed via bench migrate
# --------------------------------------------------------------------------
fixtures = [
    {
        "dt": "Custom Field",
        "filters": [["module", "=", "Sales Order COGS"]],
    },
]

# --------------------------------------------------------------------------
# Installation / migration hooks
# --------------------------------------------------------------------------
after_install = "custom_sales_order.setup.after_install"
after_migrate = "custom_sales_order.setup.after_migrate"
