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
        // Auto-fetch company and order number from the Sales Order
        if (frm.doc.sales_order) {
            frappe.db.get_value(
                "Sales Order",
                frm.doc.sales_order,
                ["company", "custom_order_number"],
                function (r) {
                    if (r) {
                        frm.set_value("company", r.company || "");
                        frm.set_value("custom_order_number", r.custom_order_number || "");
                    }
                }
            );
        } else {
            frm.set_value("company", "");
            frm.set_value("custom_order_number", "");
        }
    },
});

// Child table events
frappe.ui.form.on("Sales Order Cost Item", {
    mode_of_payment: function (frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.mode_of_payment && frm.doc.company) {
            frappe.call({
                method: "frappe.client.get_value",
                args: {
                    doctype: "Mode of Payment Account",
                    filters: {
                        parent: row.mode_of_payment,
                        company: frm.doc.company,
                    },
                    fieldname: "default_account",
                },
                callback: function (r) {
                    if (r.message && r.message.default_account) {
                        frappe.model.set_value(
                            cdt,
                            cdn,
                            "payment_account",
                            r.message.default_account
                        );
                    } else {
                        frappe.model.set_value(cdt, cdn, "payment_account", "");
                        frappe.msgprint({
                            title: __("Payment Account Not Found"),
                            message: __(
                                "No default account configured for Mode of Payment '{0}' in company '{1}'.",
                                [row.mode_of_payment, frm.doc.company]
                            ),
                            indicator: "orange",
                        });
                    }
                },
            });
        } else {
            frappe.model.set_value(cdt, cdn, "payment_account", "");
        }
    },

    amount: function (frm) {
        _compute_total(frm);
    },

    cost_items_remove: function (frm) {
        _compute_total(frm);
    },
});

function _compute_total(frm) {
    let total = 0;
    (frm.doc.cost_items || []).forEach(function (row) {
        total += flt(row.amount);
    });
    frm.set_value("total_amount", flt(total, 2));
}
