# Changelog

All notable changes to this project will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [4.0.0] - 2026-04-02

### Added

**Multi-country architecture**
- Plugin system with `TaxPlugin` / `TaxClassifier` / `TaxAggregator` / `OutputRenderer` Protocols
- Country registry with `--country de|cz` CLI flag
- FX provider factory supporting ECB and ČNB providers

**Czech Republic plugin (`countries/cz/`)**
- Per-event CZK conversion via ČNB daily rates with full audit trail
- §8 ZDP bucket classification (dividends, interest)
- §10 ZDP bucket classification (securities, options)
- Holding-period time test (§4/1/w ZDP, configurable 3-year rule)
- Annual exempt limit (CZK 100k for disposal proceeds, 2025+ amendment)
- §10 loss offsetting (securities and options netted separately)
- Foreign tax credit (§38f ZDP, per-item caps + proportional finalization)
- Tax liability computation (15% / 23% rates with configurable threshold)
- DAP-oriented form mapping with stable internal line codes
- JSON and XLSX audit exports
- `CzTaxItem` model with full audit trail (FX, WHT, taxability, exemption)
- Withholding tax linking (explicit ID match + asset/date proximity)
- Unlinked WHT preserved as standalone audit items

**Core refactoring**
- German tax classification extracted from `fifo_manager.py` into `GermanTaxClassifier`
- `RealizedGainLoss.__post_init__` cleaned — no more auto-calculated Teilfreistellung
- Calculation engine accepts injectable `tax_classifier` callback
- `ExchangeRateProvider` base class satisfies `FxProvider` Protocol

**Documentation**
- `README.md` rewritten for multi-country use
- `docs/architecture.md` — layer diagram, separation of concerns
- `docs/cz-plugin.md` — CZ features, limitations, policy assumptions
- `docs/development.md` — test structure, debugging, mock patterns
- `CONTRIBUTING.md` — setup, coding style, PR checklist

### Changed
- Project name: `ibkr-german-tax-declaration-engine` → `ibkr-tax-declaration-engine`
- Version jump from 3.3.1 to 4.0.0 (breaking: multi-country architecture)
- `pipeline_runner.py` now accepts `country_code` parameter
- German plugin is the default (`--country de`)

### Known Limitations
- CZ: Treaty credit caps are placeholder values — verify per-treaty
- CZ: Jednotný kurz (uniform/annual rate) not implemented
- CZ: Pre-2014 acquisition rule (6-month test) not implemented
- CZ: Expense deduction (§10/4 ZDP) not implemented
- CZ: Loss carryforward not implemented
- CZ: Elevated-rate threshold applies to IBKR income only
- CZ: RGL disposal amounts use EUR→CZK (core converts to EUR first)
- CZ: Official form line references not verified (`official_line_ref=None`)
- Core: Stock-for-stock merger FIFO logic not fully implemented
- DE: Sparer-Pauschbetrag, solidarity surcharge, church tax not calculated

## [3.3.1] - Previous

German-only release. See git history for details.
