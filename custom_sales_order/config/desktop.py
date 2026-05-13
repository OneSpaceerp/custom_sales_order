# Copyright (c) 2026, Nest Software Development and contributors
# For license information, please see license.txt

from frappe import _


def get_data():
    return [
        {
            "module_name": "Sales Order COGS",
            "color": "#1B3A6B",
            "icon": "octicon octicon-graph",
            "type": "module",
            "label": _("Sales Order COGS"),
            "description": _(
                "Dynamic COGS Engine — Journal Entry automation from Sales Orders"
            ),
        },
    ]
