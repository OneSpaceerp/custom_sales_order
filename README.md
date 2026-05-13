# Custom Sales Order COGS

Dynamic COGS Engine for ERPNext v16 — automatically posts Journal Entries from Sales Order cost fields.

## Overview

This custom Frappe/ERPNext application adds automatic Cost of Goods Sold (COGS) tracking to Sales Orders. It reads three pre-existing custom fields on Sales Order (`custom_expected_cost`, `custom_actual_cost`, `custom_is_compleated`) and creates submitted Journal Entries to record COGS in the General Ledger.

## COGS Calculation Logic

| Scenario | Method | COGS Value |
|---|---|---|
| Order In Progress | Conservative | `max(expected_cost, actual_cost)` |
| Order Completed | Actual | `actual_cost` |

## Features

- **Automatic Journal Entries** — COGS JEs are created/updated on every Sales Order save
- **Settings Singleton** — Configure COGS Account, Cost Clearing Account, and master enable switch
- **Dashboard Indicators** — Completion status and COGS posting status on the SO form
- **Real-time COGS Preview** — See estimated COGS, gross profit, and margin % before saving
- **Script Report** — Sales Order COGS Summary with Company, Customer, Date, and Status filters
- **Error Isolation** — JE failures are logged but never block the Sales Order save

## Installation

```bash
bench get-app https://github.com/OneSpaceerp/custom_sales_order
bench --site your-site install-app custom_sales_order
bench --site your-site migrate
```

## Configuration

After installation, navigate to **Custom Sales Order Settings** and configure:

1. **COGS Account** — The expense account to debit (e.g., Cost of Goods Sold)
2. **Cost Clearing Account** — The offset credit account (e.g., GRNI or Cost Clearing)
3. **Enable COGS Journal Entry Posting** — Master switch (enabled by default)

## Prerequisites

The following custom fields must already exist on the Sales Order DocType:

| Field | Type |
|---|---|
| `custom_expected_cost` | Currency |
| `custom_actual_cost` | Currency |
| `custom_is_compleated` | Check |

## License

MIT

## Publisher

Nest Software Development
