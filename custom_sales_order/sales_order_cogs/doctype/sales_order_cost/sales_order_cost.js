// Copyright (c) 2026, Nest Software Development and contributors
// For license information, please see license.txt

frappe.ui.form.on("Sales Order Cost", {
    refresh: function (frm) {
        // Show linked Sales Orders distribution preview
        _render_linked_sales_orders(frm);

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

    // When user types an Order Number, auto-fetch the Sales Order(s)
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

                        // Store linked orders data for rendering
                        frm._linked_orders = r.message.linked_orders || [];
                        _render_linked_sales_orders(frm);

                        // Show info about multiple SOs
                        if (r.message.count > 1) {
                            frappe.show_alert({
                                message: __(
                                    "Order #{0} is linked to {1} Sales Orders. Costs will be distributed proportionally by Grand Total.",
                                    [
                                        frm.doc.custom_order_number,
                                        r.message.count,
                                    ]
                                ),
                                indicator: "blue",
                            });
                        }
                    } else {
                        frm.set_value("sales_order", "");
                        frm.set_value("company", "");
                        frm._linked_orders = [];
                        _render_linked_sales_orders(frm);
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
            frm._linked_orders = [];
            _render_linked_sales_orders(frm);
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
        _render_linked_sales_orders(frm);
    },

    cost_items_remove: function (frm) {
        _compute_total(frm);
        _render_linked_sales_orders(frm);
    },
});

function _compute_total(frm) {
    let total = 0;
    (frm.doc.cost_items || []).forEach(function (row) {
        total += flt(row.amount);
    });
    frm.set_value("total_amount", flt(total, 2));
}

/**
 * Render the linked Sales Orders table showing proportional cost distribution.
 * Fetches SO data from the server if not already cached.
 */
function _render_linked_sales_orders(frm) {
    let wrapper = frm.fields_dict.linked_sales_orders;
    if (!wrapper || !wrapper.$wrapper) return;

    // If we don't have linked orders data yet, fetch it
    if (!frm._linked_orders && frm.doc.custom_order_number) {
        frappe.call({
            method: "custom_sales_order.sales_order_cogs.doctype.sales_order_cost.sales_order_cost.get_sales_order_from_order_number",
            args: { order_number: frm.doc.custom_order_number },
            async: false,
            callback: function (r) {
                if (r.message) {
                    frm._linked_orders = r.message.linked_orders || [];
                }
            },
        });
    }

    let linked = frm._linked_orders || [];

    // Only show if multiple SOs are linked
    if (linked.length <= 1) {
        wrapper.$wrapper.html("");
        return;
    }

    let total_cost = flt(frm.doc.total_amount) || 0;
    let total_grand = linked.reduce(
        (sum, so) => sum + flt(so.grand_total),
        0
    );

    let rows_html = linked
        .map(function (so) {
            let pct =
                total_grand > 0
                    ? ((flt(so.grand_total) / total_grand) * 100).toFixed(1)
                    : (100 / linked.length).toFixed(1);
            let allocated =
                total_grand > 0
                    ? ((flt(so.grand_total) / total_grand) * total_cost).toFixed(
                          2
                      )
                    : (total_cost / linked.length).toFixed(2);

            return (
                "<tr>" +
                '<td><a href="/app/sales-order/' +
                so.name +
                '">' +
                so.name +
                "</a></td>" +
                "<td>" +
                (so.customer_name || "-") +
                "</td>" +
                "<td class='text-right'>" +
                format_currency(so.grand_total, frm.doc.currency) +
                "</td>" +
                "<td class='text-right'>" +
                pct +
                "%</td>" +
                "<td class='text-right font-weight-bold'>" +
                format_currency(allocated, frm.doc.currency) +
                "</td>" +
                "</tr>"
            );
        })
        .join("");

    let html =
        '<div class="frappe-control" style="margin-top: 8px; margin-bottom: 8px;">' +
        '<div class="alert alert-info" style="padding: 8px 12px; margin-bottom: 8px;">' +
        '<strong>' + __("Multiple Sales Orders") + '</strong> — ' +
        __("{0} Sales Orders share Order #{1}. Costs are distributed proportionally by Grand Total.", [
            linked.length,
            frm.doc.custom_order_number,
        ]) +
        "</div>" +
        '<table class="table table-bordered table-sm" style="font-size: 12px;">' +
        "<thead><tr>" +
        "<th>" + __("Sales Order") + "</th>" +
        "<th>" + __("Customer") + "</th>" +
        '<th class="text-right">' + __("Grand Total") + "</th>" +
        '<th class="text-right">' + __("Share %") + "</th>" +
        '<th class="text-right">' + __("Allocated Cost") + "</th>" +
        "</tr></thead>" +
        "<tbody>" +
        rows_html +
        "</tbody>" +
        "</table></div>";

    wrapper.$wrapper.html(html);
}
