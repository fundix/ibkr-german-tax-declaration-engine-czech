# Architecture

## Layered Design

The project separates concerns into distinct layers. Country-specific tax logic must **never** leak into core modules.

```
┌─────────────────────────────────────────────────┐
│  CLI / main.py                                  │  Orchestration
├─────────────────────────────────────────────────┤
│  countries/de/  │  countries/cz/                │  Country plugins
│  (TaxPlugin)    │  (TaxPlugin)                  │
├─────────────────────────────────────────────────┤
│  countries/base.py                              │  Protocol interfaces
├─────────────────────────────────────────────────┤
│  engine/         │  processing/                 │  Core pipeline
│  (FIFO, calc)    │  (enrichment, linking)       │
├─────────────────────────────────────────────────┤
│  parsers/        │  domain/                     │  Data layer
│  (IBKR CSV)      │  (assets, events, results)   │
├─────────────────────────────────────────────────┤
│  utils/                                         │  FX providers, helpers
└─────────────────────────────────────────────────┘
```

## Layer Responsibilities

### Core (country-agnostic)

| Module | What it does | What it must NOT do |
|--------|-------------|---------------------|
| `domain/` | Asset, event, result dataclasses | Reference any country-specific enum or rule |
| `parsers/` | Parse IBKR CSV into domain objects | Apply tax classification |
| `engine/` | FIFO lot management, gain/loss calculation | Hardcode tax categories |
| `processing/` | FX enrichment, option/WHT linking | Apply Teilfreistellung or time tests |
| `utils/` | FX providers (ECB, ČNB), helpers | Contain tax policy |

The calculation engine accepts an optional `tax_classifier` callback. Country plugins inject their classifier here — the engine itself is country-agnostic.

### Country Plugins

Each plugin implements the `TaxPlugin` Protocol from `countries/base.py`:

```python
class TaxPlugin(Protocol):
    country_code: str
    def get_tax_classifier(self) -> TaxClassifier: ...
    def get_tax_aggregator(self) -> TaxAggregator: ...
    def get_output_renderer(self) -> OutputRenderer: ...
```

A plugin's internal layers follow a strict pipeline:

```
Items → Classification → Time test → Annual limit → Loss offsetting
    → FTC → Tax liability → Form mapping → Export
```

Each step reads the output of the previous step. No step recomputes what an earlier step already determined.

### Separation: Economic Facts vs. Tax Classification vs. Tax Liability

| Layer | Example | Changes business data? |
|-------|---------|----------------------|
| **Economic facts** | `RealizedGainLoss`, `CashFlowEvent` | Core pipeline produces these |
| **Tax classification** | `CzTaxItem.is_taxable`, `cz_tax_section` | Plugin annotates items in-place |
| **Tax liability** | `CzTaxLiabilitySummary.gross_czech_tax` | Plugin computes from annotations |
| **Form mapping** | `CzFormLine("CZ_DAP_8_DIVIDENDS", ...)` | Reads liability, no recomputation |
| **Export** | JSON file, XLSX workbook | Serialises models, no tax logic |

## How to Add a New Country Plugin

1. Create `src/countries/xx/` with `__init__.py` and `plugin.py`.
2. Implement `TaxPlugin` Protocol (classifier, aggregator, renderer).
3. Register in `src/countries/registry.py`:
   ```python
   _PLUGIN_REGISTRY["xx"] = "src.countries.xx.plugin.XxTaxPlugin"
   ```
4. The CLI `--country xx` flag works automatically.
5. Add tests in `tests/test_xx_*.py`.

## How to Add a New FX Provider

1. Subclass `ExchangeRateProvider` in `src/utils/`.
2. Implement `get_rate(date, currency)` returning foreign-units-per-1-home-currency.
3. Register in `src/utils/fx_provider_factory.py`:
   ```python
   _PROVIDER_MAP["xxx"] = "src.utils.xxx_provider.XxxProvider"
   ```

## How to Add a New Exporter

1. Create a module in the country's `exporters/` directory.
2. Read from `TaxResult` and `country_result` — never recompute tax figures.
3. Expose a simple function like `export_xx_to_format(tax_result, output)`.
