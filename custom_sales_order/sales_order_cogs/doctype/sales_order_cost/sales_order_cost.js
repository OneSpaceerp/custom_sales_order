// Copyright (c) 2026, Nest Software Development and contributors
// For license information, please see license.txt

frappe.ui.form.on("Sales Order Cost", {
    refresh: function (frm) {
        // Link back to the parent Sales Order
        if (frm.doc.sales_order) {
            frm.add_custom_button(
                __("View Sales Order"),
                function () {
                    frappe.set_route("Form", "Sales Order", frm.doc.sales_order);
                }
            );
        }
    },

    sales_order: function (frm) {
        // Auto-fetch company from the Sales Order
        if (frm.doc.sales_order) {
            frappe.db.get_value(
                "Sales Order",
                frm.doc.sales_order,
                "company",
                function (r) {
                    if (r && r.company) {
                        frm.set_value("company", r.company);
                    }
                }
            );
        } else {
            frm.set_value("company", "");
            frm.set_value("payment_account", "");
        }
    },

    mode_of_payment: function (frm) {
        // Auto-fetch payment account from Mode of Payment Account
        if (frm.doc.mode_of_payment && frm.doc.company) {
            frappe.call({
                method: "frappe.client.get_value",
                args: {
                    doctype: "Mode of Payment Account",
                    filters: {
                        parent: frm.doc.mode_of_payment,
                        company: frm.doc.company,
                    },
                    fieldname: "default_account",
                },
                callback: function (r) {
                    if (r.message && r.message.default_account) {
                        frm.set_value("payment_account", r.message.default_account);
                    } else {
                        frm.set_value("payment_account", "");
                        frappe.msgprint({
                            title: __("Payment Account Not Found"),
                            message: __(
                                "No default account configured for Mode of Payment '{0}' in company '{1}'. " +
                                "Please set it up in the Mode of Payment master.",
                                [frm.doc.mode_of_payment, frm.doc.company]
                            ),
                            indicator: "orange",
                        });
                    }
                },
            });
        } else {
            frm.set_value("payment_account", "");
        }
    },
});
