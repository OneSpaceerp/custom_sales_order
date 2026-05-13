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

        // View linked Journal Entry
        if (frm.doc.cogs_journal_entry) {
            frm.add_custom_button(
                __("View Journal Entry"),
                function () {
                    frappe.set_route(
                        "Form",
                        "Journal Entry",
                        frm.doc.cogs_journal_entry
                    );
                }
            );
        }

        // "Generate Journal Entry" button — only on saved documents
        if (!frm.is_new()) {
            frm.add_custom_button(
                __("Generate Journal Entry"),
                function () {
                    let action_label = frm.doc.cogs_journal_entry
                        ? __(
                              "This will cancel the existing Journal Entry ({0}) and create a new one. Continue?",
                              [frm.doc.cogs_journal_entry]
                          )
                        : __(
                              "This will create a COGS Journal Entry from the cost items. Continue?"
                          );

                    frappe.confirm(action_label, function () {
                        frm.call("generate_journal_entry").then(function (r) {
                            if (r && r.message && r.message.je) {
                                frappe.show_alert({
                                    message: __(
                                        "Journal Entry {0} created successfully.",
                                        [
                                            '<a href="/app/journal-entry/' +
                                                r.message.je +
                                                '">' +
                                                r.message.je +
                                                "</a>",
                                        ]
                                    ),
                                    indicator: "green",
                                });
                            } else {
                                frappe.show_alert({
                                    message: __(
                                        "No Journal Entry was created. Please check settings and cost items."
                                    ),
                                    indicator: "orange",
                                });
                            }
                            frm.reload_doc();
                        });
                    });
                },
                frm.doc.cogs_journal_entry ? __("Actions") : null
            );

            // Make the primary action button stand out
            if (!frm.doc.cogs_journal_entry) {
                frm.change_custom_button_type(
                    __("Generate Journal Entry"),
                    null,
                    "primary"
                );
            }
        }
    },

    // When user types an Order Number, auto-fetch the Sales Order
    custom_order_number: function (frm) {
        if (frm.doc.custom_order_number) {
            frappe.call({
                method: "custom_sales_order.sales_order_cogs.doctype.sales_order_cost.sales_order_cost.get_sales_order_from_order_number",
                args: {
                    order_number: frm.doc.custom_order_number,
                },
                callback: function (r) {
                    if (r.message && r.message.sales_order) {
                        frm.set_value("sales_order", r.message.sales_order);
                        frm.set_value("company", r.message.company);
                    } else {
                        frm.set_value("sales_order", "");
                        frm.set_value("company", "");
                        frappe.msgprint({
                            title: __("Sales Order Not Found"),
                            message: __(
                                "No Sales Order found with Order Number '{0}'.",
                                [frm.doc.custom_order_number]
                            ),
                            indicator: "red",
                        });
                    }
                },
            });
        } else {
            frm.set_value("sales_order", "");
            frm.set_value("company", "");
        }
    },

    // When user selects a Sales Order directly, fetch the order number
    sales_order: function (frm) {
        if (frm.doc.sales_order) {
            frappe.db.get_value(
                "Sales Order",
                frm.doc.sales_order,
                ["company", "custom_order_number"],
                function (r) {
                    if (r) {
                        frm.set_value("company", r.company || "");
                        if (!frm.doc.custom_order_number) {
                            frm.set_value(
                                "custom_order_number",
                                r.custom_order_number || ""
                            );
                        }
                    }
                }
            );
        }
    },
});

// Child table events
frappe.ui.form.on("Sales Order Cost Item", {
    mode_of_payment: function (frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.mode_of_payment && frm.doc.company) {
            frappe.call({
                method: "custom_sales_order.sales_order_cogs.doctype.sales_order_cost.sales_order_cost.get_payment_account",
                args: {
                    mode_of_payment: row.mode_of_payment,
                    company: frm.doc.company,
                },
                callback: function (r) {
                    if (r.message && r.message.payment_account) {
                        frappe.model.set_value(
                            cdt,
                            cdn,
                            "payment_account",
                            r.message.payment_account
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
