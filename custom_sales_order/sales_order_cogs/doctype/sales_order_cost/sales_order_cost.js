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

        // Check if any cost item has a JE linked
        let has_journal_entries = (frm.doc.cost_items || []).some(
            (row) => row.journal_entry
        );

        // View linked Journal Entries
        if (has_journal_entries) {
            frm.add_custom_button(
                __("View Journal Entries"),
                function () {
                    // Collect all JE names from child rows
                    let je_names = (frm.doc.cost_items || [])
                        .filter((row) => row.journal_entry)
                        .map((row) => row.journal_entry);
                    frappe.set_route("List", "Journal Entry", {
                        name: ["in", je_names],
                    });
                }
            );
        }

        // "Generate Journal Entries" button — only on saved documents
        if (!frm.is_new()) {
            frm.add_custom_button(
                __("Generate Journal Entries"),
                function () {
                    let action_label = has_journal_entries
                        ? __(
                              "This will cancel all existing Journal Entries and create new ones for each cost item. Continue?"
                          )
                        : __(
                              "This will create a Journal Entry for each cost item row, using its date as the posting date. Continue?"
                          );

                    frappe.confirm(action_label, function () {
                        frm.call("generate_journal_entry").then(function (r) {
                            if (r && r.message && r.message.count > 0) {
                                frappe.show_alert({
                                    message: __(
                                        "{0} Journal Entries created successfully.",
                                        [r.message.count]
                                    ),
                                    indicator: "green",
                                });
                            } else {
                                frappe.show_alert({
                                    message: __(
                                        "No Journal Entries were created. Please check settings and cost items."
                                    ),
                                    indicator: "orange",
                                });
                            }
                            frm.reload_doc();
                        });
                    });
                },
                has_journal_entries ? __("Actions") : null
            );

            // Make the primary action button stand out
            if (!has_journal_entries) {
                frm.change_custom_button_type(
                    __("Generate Journal Entries"),
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
