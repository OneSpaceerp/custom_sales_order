// Copyright (c) 2026, Nest Software Development and contributors
// For license information, please see license.txt

/**
 * Client-side enhancements for Sales Order — COGS indicators, preview,
 * and "View COGS Entry" button.
 *
 * Injected globally via app_include_js; only activates on the Sales Order form.
 */

frappe.ui.form.on("Sales Order", {
    refresh: function (frm) {
        // Dashboard indicators
        _set_cogs_indicators(frm);

        // "View COGS Entry" button
        if (frm.doc.custom_cogs_journal_entry) {
            frm.add_custom_button(
                __("View COGS Entry"),
                function () {
                    frappe.set_route(
                        "Form",
                        "Journal Entry",
                        frm.doc.custom_cogs_journal_entry
                    );
                },
                __("COGS")
            );
        }

        // Preview on load
        _preview_cogs(frm);
    },

    custom_expected_cost: function (frm) {
        _preview_cogs(frm);
    },

    custom_actual_cost: function (frm) {
        _preview_cogs(frm);
    },

    custom_is_compleated: function (frm) {
        // Guard: warn if marking complete with zero actual cost
        if (frm.doc.custom_is_compleated && !flt(frm.doc.custom_actual_cost)) {
            frappe.msgprint({
                title: __("Missing Actual Cost"),
                message: __(
                    "You have marked this order as Completed but Actual Cost is zero. " +
                        "Please enter the Actual Cost before saving."
                ),
                indicator: "orange",
            });
        }
        _preview_cogs(frm);
    },
});

/**
 * Add dashboard indicators showing completion and COGS posting status.
 */
function _set_cogs_indicators(frm) {
    if (frm.is_new()) return;

    // Completion status
    if (frm.doc.custom_is_compleated) {
        frm.dashboard.add_indicator(__("Completed"), "green");
    } else {
        frm.dashboard.add_indicator(__("In Progress"), "blue");
    }

    // COGS posting status
    if (frm.doc.custom_cogs_journal_entry) {
        frm.dashboard.add_indicator(__("COGS Posted"), "green");
    } else {
        frm.dashboard.add_indicator(__("COGS Pending"), "orange");
    }
}

/**
 * Calculate and display a real-time COGS preview in the form intro area.
 */
function _preview_cogs(frm) {
    let expected = flt(frm.doc.custom_expected_cost) || 0;
    let actual = flt(frm.doc.custom_actual_cost) || 0;
    let completed = frm.doc.custom_is_compleated ? true : false;
    let cogs = completed ? actual : Math.max(expected, actual);
    let method = completed
        ? __("Actual Cost (Completed)")
        : __("Conservative — max(expected, actual) — In Progress");
    let revenue = flt(frm.doc.grand_total) || 0;
    let profit = revenue - cogs;
    let margin = revenue > 0 ? ((profit / revenue) * 100).toFixed(1) : "N/A";

    let msg = __(
        "COGS Preview: {0} | Method: {1} | Est. Gross Profit: {2} ({3}%)",
        [
            format_currency(cogs, frm.doc.currency),
            method,
            format_currency(profit, frm.doc.currency),
            margin,
        ]
    );
    frm.set_intro(msg, cogs > 0 ? "blue" : "orange");
}
