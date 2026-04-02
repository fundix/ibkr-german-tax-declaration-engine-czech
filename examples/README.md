# Examples

This directory contains instructions for running the engine on your own IBKR data.

> **No sample IBKR data is included** — IBKR Flex Query reports contain personal financial data that cannot be shared publicly. Instead, this guide shows you how to prepare your own data and what output to expect.

## Quick Start (CZ)

```bash
# 1. Place your IBKR CSV files in data/
#    - trades.csv
#    - cash_transactions.csv
#    - positions_start_of_year.csv
#    - positions_end_of_year.csv
#    - corporate_actions.csv

# 2. Edit src/config.py: set TAX_YEAR, file paths

# 3. Run with CZ plugin + JSON/XLSX export
uv run python -m src.main --country cz --report-tax-declaration \
    --output-json cz_report.json \
    --output-xlsx cz_report.xlsx

# 4. Run with DE plugin (default)
uv run python -m src.main --report-tax-declaration
```

## Expected CZ JSON Output Structure

```json
{
  "metadata": {
    "country": "cz",
    "tax_year": 2024,
    "export_version": "1.0",
    "currency": "CZK",
    "fx_policy": {"mode": "DAILY", "source": "cnb"}
  },
  "sections": {
    "cz_8_dividends": {
      "label": "§8 ZDP – Dividendy",
      "line_items": {
        "gross_dividends_czk": "24500.00",
        "wht_paid_czk": "3675.00"
      }
    },
    "cz_10_summary": {
      "label": "§10 ZDP – Souhrnný přehled",
      "line_items": {
        "sec_taxable_gains_czk": "120000.00",
        "sec_taxable_losses_czk": "15000.00",
        "sec_net_taxable_czk": "105000.00",
        "opt_net_taxable_czk": "8000.00",
        "combined_net_taxable_czk": "113000.00"
      }
    },
    "cz_tax_liability": {
      "label": "Daňová povinnost (§16 + §38f ZDP)",
      "line_items": {
        "combined_taxable_base_czk": "137500.00",
        "gross_czech_tax_czk": "20625.00",
        "final_creditable_ftc_czk": "3675.00",
        "final_czech_tax_after_credit_czk": "16950.00"
      }
    }
  },
  "items": ["... one CzTaxItem per dividend, disposal, option ..."],
  "warnings": {
    "pending_review_count": 0,
    "unlinked_wht_count": 0
  }
}
```

## Expected CZ XLSX Sheets

| Sheet | Content |
|-------|---------|
| Summary | All section aggregates + liability + FTC |
| Securities | Stock/bond/ETF disposals with taxability |
| Options | Option close/expiry items |
| Dividends | Dividend items + FTC columns |
| Interest | Interest items |
| WithholdingTax | All WHT records (linked + unlinked) |
| PendingReview | Items needing manual review |
| Metadata | FX policy, config snapshot |

## Input Data Format

See `input_data_spec.md` in the project root for detailed CSV column specifications.

**Critical:** The trades CSV **must** include the `Open/CloseIndicator` column.

## Test Run (no real data needed)

To verify the installation works without IBKR data:

```bash
uv run pytest             # runs 444+ tests with synthetic data
uv run pytest -v -x       # verbose, stop on first failure
```
