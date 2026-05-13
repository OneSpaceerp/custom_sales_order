// Copyright (c) 2026, Nest Software Development and contributors
// For license information, please see license.txt

frappe.ui.form.on("Custom Sales Order Settings", {
    refresh: function (frm) {
        frm.set_intro(
            __(
                "Configure the GL accounts used when posting COGS Journal Entries from Sales Orders."
            ),
            "blue"
        );
    },
});
