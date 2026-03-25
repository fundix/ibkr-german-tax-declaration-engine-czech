# Architektonický audit repozitáře

**Datum:** 2025-03-25
**Baseline:** 182 testů PASS, verze 3.3.1

---

## 1. Identifikace funkčních oblastí

### 1.1 Parser IBKR vstupů

| Soubor | Řádky | Popis |
|--------|-------|-------|
| `src/parsers/parsing_orchestrator.py` | 32 043 B | Orchestrace parsingu všech CSV souborů |
| `src/parsers/trades_parser.py` | 1 174 B | Parser obchodů |
| `src/parsers/cash_transactions_parser.py` | 1 146 B | Parser cash transakcí |
| `src/parsers/corporate_actions_parser.py` | 1 239 B | Parser corporate actions |
| `src/parsers/positions_parser.py` | 1 360 B | Parser pozic SOY/EOY |
| `src/parsers/raw_models.py` | 14 013 B | Raw CSV modely (Pydantic) |
| `src/parsers/domain_event_factory.py` | 55 507 B | Konverze raw → domain events |

**Verdikt: 100 % core / broker-specific (IBKR).** Žádná daňová logika. Vhodné pro `brokers/ibkr/`.

### 1.2 Normalizace / Event model

| Soubor | Popis | DE-specifické? |
|--------|-------|----------------|
| `src/domain/assets.py` | Asset hierarchie (Stock, Bond, InvestmentFund, Option, Cfd, PrivateSaleAsset, CashBalance) | ⚠️ `PrivateSaleAsset` – koncept §23 EStG, ale jako abstrakce "private sale < 1y" je universální |
| `src/domain/events.py` | FinancialEvent hierarchie (Trade, CashFlow, WHT, CorpAction, OptionLifecycle, Fee, FX) | ✅ Čistý core |
| `src/domain/enums.py` | AssetCategory, FinancialEventType, RealizationType, **TaxReportingCategory**, **InvestmentFundType** | 🔴 `TaxReportingCategory` = 100 % DE (Anlage KAP řádky). `InvestmentFundType` = DE názvy (Aktienfonds…) ale koncept je universální |
| `src/domain/results.py` | RealizedGainLoss, VorabpauschaleData, LossOffsettingResult | 🔴 Těžce DE – Teilfreistellung v `__post_init__`, Vorabpauschale je čistě DE koncept |
| `src/domain/__init__.py` | Re-exporty (zatím zakomentované) | ✅ Neutrální |

### 1.3 FIFO / Matching / Lot accounting

| Soubor | Řádky | DE-specifické? |
|--------|-------|----------------|
| `src/engine/fifo_manager.py` | 952 ř. | 🔴🔴 **HLAVNÍ PROBLÉM.** FIFO lot management je core, ale `consume_long_lots_for_sale`, `consume_short_lots_for_cover`, `consume_all_lots_for_cash_merger` – každá metoda obsahuje ~40 řádků DE daňové klasifikace (TaxReportingCategory mapping, Teilfreistellung, §23 EStG). Tento blok se opakuje **3×** identicky. |
| `src/engine/calculation_engine.py` | 366 ř. | ✅ Core orchestrace, bez DE logiky (kromě komentáře "German tax") |
| `src/engine/event_processors/base_processor.py` | 34 ř. | ✅ Čistý ABC |
| `src/engine/event_processors/trade_processor.py` | 230 ř. | ✅ Core (option premium adjustment) |
| `src/engine/event_processors/corporate_action_processor.py` | 129 ř. | ⚠️ Log message "German tax: zero cost basis" na ř. 82, jinak core |
| `src/engine/event_processors/option_processor.py` | 229 ř. | 🔴 `OptionExpirationWorthlessProcessor` – hardcoduje `TaxReportingCategory.ANLAGE_KAP_TERMIN_*` (ř. 197-205) |

### 1.4 FX conversion

| Soubor | Popis | DE-specifické? |
|--------|-------|----------------|
| `src/utils/currency_converter.py` | Obecný konvertor | ✅ Core |
| `src/utils/exchange_rate_provider.py` | ECB provider + cache | ✅ Core (ECB je universální pro EUR země) |
| `src/processing/enrichment.py` | Konverze všech eventů do EUR | ✅ Core |

### 1.5 Corporate actions

| Soubor | Popis | DE-specifické? |
|--------|-------|----------------|
| `src/engine/event_processors/corporate_action_processor.py` | Split, Merger (cash/stock), Stock Dividend, ED | ⚠️ Převážně core, viz 1.3 |
| `src/engine/fifo_manager.py` → `adjust_lots_for_split`, `add_lot_for_stock_dividend`, `consume_all_lots_for_cash_merger` | Lot adjustments | ⚠️ Split/stock div = core. Cash merger obsahuje DE tax classification |

### 1.6 Options lifecycle

| Soubor | Popis | DE-specifické? |
|--------|-------|----------------|
| `src/processing/option_trade_linker.py` | Linking option events → stock trades | ✅ Core |
| `src/engine/event_processors/option_processor.py` | Exercise, Assignment, Expiration | 🔴 Expiration processor hardcoduje DE tax categories |

### 1.7 Country-specific German tax logic

| Soubor | Co je DE-specifické |
|--------|---------------------|
| `src/domain/enums.py` → `TaxReportingCategory` | **Celý enum** – 30+ hodnot mapujících na Anlage KAP/KAP-INV/SO řádky |
| `src/domain/enums.py` → `InvestmentFundType` | Německé názvy (Aktienfonds, Mischfonds…), ale koncept partial exemption je universální |
| `src/domain/results.py` → `RealizedGainLoss.__post_init__` | Volá `get_teilfreistellung_rate_for_fund_type()`, počítá Teilfreistellung přímo v domain objektu |
| `src/domain/results.py` → `VorabpauschaleData` | 100 % DE koncept (Vorabpauschale = advance lump sum) |
| `src/domain/results.py` → `LossOffsettingResult` | DE form line values, DE conceptual balances |
| `src/utils/tax_utils.py` | `get_teilfreistellung_rate_for_fund_type()` – DE sazby (30 %, 15 %, 60 %, 80 %) |
| `src/engine/loss_offsetting.py` | **Celý modul** (232 ř.) – `LossOffsettingEngine` mapuje na Anlage KAP Zeilen, aplikuje derivative loss capping (€20k) |
| `src/engine/fifo_manager.py` | DE tax classification blok (opakovaný 3×, cca 40 ř. každý) uvnitř FIFO consume metod |
| `src/engine/event_processors/option_processor.py` | OptionExpirationWorthlessProcessor – DE tax categories |
| `src/config_example.py` → `APPLY_CONCEPTUAL_DERIVATIVE_LOSS_CAPPING` | DE-specific config flag |

### 1.8 Report / Output vrstva

| Soubor | Řádky | DE-specifické? |
|--------|-------|----------------|
| `src/reporting/console_reporter.py` | 402 ř. | 🔴 100 % DE – "Anlage KAP", "Zeile 19-24", "Quellensteuer-Ereignisse" |
| `src/reporting/pdf_generator.py` | 1489 ř. | 🔴 100 % DE – celý PDF report je pro německé daňové přiznání |
| `src/reporting/diagnostic_reports.py` | 21 543 B | ⚠️ Převážně generic diagnostic, ale používá DE enums pro display |
| `src/reporting/reporting_utils.py` | 121 ř. | 🔴 `format_date_german()`, `get_kap_inv_category_for_reporting()` = DE. Kvantizační helpers (`_q`, `_q_price`, `_q_qty`) = core |

### 1.9 Orchestrace a CLI

| Soubor | DE-specifické? |
|--------|----------------|
| `src/main.py` | 🔴 Hardcodovaný DE workflow, popis "German Tax Declaration Engine" |
| `src/pipeline_runner.py` | ✅ Core processing pipeline (parsing → enrichment → calculation) |
| `src/cli.py` | 🔴 "IBKR German Tax Declaration Engine" popis, žádný `--country` flag |
| `src/config_example.py` | ⚠️ Mix core + DE (`APPLY_CONCEPTUAL_DERIVATIVE_LOSS_CAPPING`) |

---

## 2. Cílová architektura

```
src/
├── core/                           # Country-agnostic základ
│   ├── __init__.py
│   ├── domain/
│   │   ├── assets.py               # Asset hierarchy (beze změn)
│   │   ├── events.py               # FinancialEvent hierarchy (beze změn)
│   │   ├── enums.py                # AssetCategory, FinancialEventType, RealizationType
│   │   └── results.py              # RealizedGainLoss (BEZ Teilfreistellung v __post_init__)
│   │                               #   + nový TaxClassificationResult dataclass
│   ├── engine/
│   │   ├── calculation_engine.py   # Orchestrace (beze změn)
│   │   ├── fifo_manager.py         # FIFO lots – core FIFO bez tax classification
│   │   │                           #   consume metody vrací "raw" RGL bez tax_reporting_category
│   │   │                           #   tax classification se dělá post-hoc přes TaxClassifier Protocol
│   │   └── event_processors/       # Všechny procesory (beze změn, kromě option_processor)
│   ├── processing/
│   │   ├── enrichment.py           # FX enrichment (beze změn)
│   │   ├── option_trade_linker.py  # (beze změn)
│   │   └── withholding_tax_linker.py  # (beze změn)
│   ├── identification/
│   │   └── asset_resolver.py       # (beze změn)
│   ├── classification/
│   │   └── asset_classifier.py     # (beze změn)
│   ├── utils/
│   │   ├── currency_converter.py
│   │   ├── exchange_rate_provider.py
│   │   ├── sorting_utils.py
│   │   └── type_utils.py
│   ├── pipeline_runner.py          # Core pipeline (beze změn)
│   └── config.py                   # Core config (precision, paths, tax_year)
│
├── brokers/
│   └── ibkr/
│       ├── __init__.py
│       ├── parsers/                # Přesun z src/parsers/
│       │   ├── parsing_orchestrator.py
│       │   ├── trades_parser.py
│       │   ├── cash_transactions_parser.py
│       │   ├── corporate_actions_parser.py
│       │   ├── positions_parser.py
│       │   ├── raw_models.py
│       │   └── domain_event_factory.py
│       └── input_data_spec.md
│
├── countries/
│   ├── __init__.py
│   ├── base.py                     # TaxPlugin Protocol, TaxClassifier Protocol
│   ├── registry.py                 # get_tax_plugin("de") → GermanTaxPlugin
│   │
│   ├── de/
│   │   ├── __init__.py
│   │   ├── enums.py                # TaxReportingCategory (DE), InvestmentFundType (DE names)
│   │   ├── tax_rules.py            # Teilfreistellung rates, §23 EStG rules, Vorabpauschale
│   │   ├── tax_classifier.py       # Implementuje TaxClassifier Protocol
│   │   │                           #   classify_rgl(rgl, asset_cat, ...) → TaxReportingCategory
│   │   ├── loss_offsetting.py      # LossOffsettingEngine (přesun z src/engine/)
│   │   ├── results.py              # VorabpauschaleData, LossOffsettingResult
│   │   ├── reporting/
│   │   │   ├── console_reporter.py
│   │   │   ├── pdf_generator.py
│   │   │   └── reporting_utils.py  # format_date_german, get_kap_inv_category_for_reporting
│   │   └── plugin.py               # GermanTaxPlugin(TaxPlugin)
│   │
│   └── cz/
│       ├── __init__.py
│       ├── enums.py                # CZ tax categories (Příloha č. 2, §10 ZDP...)
│       ├── tax_rules.py            # CZ pravidla (3-letý time test, 15% flat...)
│       ├── tax_classifier.py       # CZ implementace TaxClassifier
│       ├── loss_offsetting.py      # CZ agregace (nebo empty/TODO)
│       ├── results.py              # CZ result dataclasses
│       ├── reporting/
│       │   ├── console_reporter.py
│       │   └── reporting_utils.py
│       └── plugin.py               # CzechTaxPlugin(TaxPlugin)
│
├── outputs/                        # Sdílené reporting utilities
│   ├── __init__.py
│   ├── base_reporter.py            # Abstract base pro reportéry
│   └── quantization.py             # _q, _q_price, _q_qty (core helpers)
│
├── main.py                         # Dispatch: --country de|cz → plugin
└── cli.py                          # + --country argument
```

---

## 3. Konkrétní soubory k přesunu nebo rozdělení

### 3.1 Soubory k PŘESUNU (beze změn obsahu)

| Stávající umístění | Cílové umístění | Poznámka |
|---------------------|-----------------|----------|
| `src/parsers/*` | `src/brokers/ibkr/parsers/*` | Celý adresář, 7 souborů |
| `src/engine/loss_offsetting.py` | `src/countries/de/loss_offsetting.py` | 100 % DE logika |
| `src/reporting/console_reporter.py` | `src/countries/de/reporting/console_reporter.py` | 100 % DE |
| `src/reporting/pdf_generator.py` | `src/countries/de/reporting/pdf_generator.py` | 100 % DE |
| `src/utils/tax_utils.py` | `src/countries/de/tax_rules.py` | 100 % DE (Teilfreistellung sazby) |

### 3.2 Soubory k ROZDĚLENÍ

| Soubor | Co zůstane v core | Co se extrahuje do countries/de/ |
|--------|-------------------|----------------------------------|
| **`src/domain/enums.py`** | `AssetCategory`, `FinancialEventType`, `RealizationType` | `TaxReportingCategory` → `countries/de/enums.py`. `InvestmentFundType` – ponechat v core (užito v classification), ale zvážit přejmenování na anglické názvy. |
| **`src/domain/results.py`** | `RealizedGainLoss` BEZ Teilfreistellung logiky v `__post_init__`. TF pole zůstanou jako `Optional`, ale nebudou automaticky plněna. | `VorabpauschaleData` → `countries/de/results.py`. `LossOffsettingResult` → `countries/de/results.py`. Teilfreistellung výpočet → `countries/de/tax_classifier.py` |
| **`src/engine/fifo_manager.py`** | FIFO lot management, consume metody vracejí "raw" RGL bez `tax_reporting_category` a bez `teilfreistellung_*` | Tax classification blok (3× ~40 ř.) → extrahovat do callable `TaxClassifier.classify_rgl()` |
| **`src/engine/event_processors/option_processor.py`** | Exercise/Assignment procesory | `OptionExpirationWorthlessProcessor` ř. 197-205 – DE tax category assignment → delegovat na TaxClassifier |
| **`src/reporting/reporting_utils.py`** | `_q()`, `_q_price()`, `_q_qty()`, `create_paragraph()`, `create_table()` → `src/outputs/quantization.py` | `format_date_german()` → `countries/de/reporting/`. `get_kap_inv_category_for_reporting()` → `countries/de/reporting/` |
| **`src/reporting/diagnostic_reports.py`** | Většina je generická | Případný DE-specific formatting |

### 3.3 Soubory k ÚPRAVĚ (bez přesunu)

| Soubor | Změna |
|--------|-------|
| `src/main.py` | Přidat country plugin dispatch |
| `src/cli.py` | Přidat `--country de\|cz` argument |
| `src/config_example.py` | Rozdělit na core config + country config |
| `src/pipeline_runner.py` | Přidat `tax_plugin` parametr |
| `src/engine/calculation_engine.py` | Přidat `tax_classifier` parametr pro post-processing RGL |

---

## 4. Riziková místa – DE logika promíchaná s core

### 🔴 KRITICKÉ (musí se řešit pro čistou separaci)

**R1: `fifo_manager.py` – 3× duplikovaný DE tax classification blok**
- Řádky 444-503, 568-631, 715-775
- Uvnitř `consume_long_lots_for_sale`, `consume_short_lots_for_cover`, `consume_all_lots_for_cash_merger`
- **Problém:** FIFO operace (core) a daňová klasifikace (DE) jsou provázané ve smyčce přes loty
- **Řešení:** Extrahovat tax classification do samostatné callable, kterou FIFO metody volají přes injektovaný callback/Protocol
- **Riziko:** Nejvyšší – 952 ř. soubor, hodně testů závisí na přesné RGL struktuře

**R2: `results.py` → `RealizedGainLoss.__post_init__` volá Teilfreistellung**
- Řádky 79-107
- Import `from src.utils.tax_utils import get_teilfreistellung_rate_for_fund_type` na ř. 11
- **Problém:** Domain objekt přímo závisí na DE daňové funkci
- **Řešení:** Odstranit automatický výpočet z `__post_init__`, nechat Teilfreistellung pole Optional, plnit je z DE tax classifier
- **Riziko:** Střední – testy ověřují tyto automaticky počítané hodnoty

**R3: `option_processor.py` → `OptionExpirationWorthlessProcessor`**
- Řádky 197-205
- Hardcoduje `TaxReportingCategory.ANLAGE_KAP_TERMIN_GEWINN/VERLUST`
- **Řešení:** Delegovat na injektovaný TaxClassifier
- **Riziko:** Nízké – izolovaný blok

### ⚠️ STŘEDNÍ

**R4: `InvestmentFundType` enum – DE názvy v core**
- Používáno v `asset_classifier.py`, `domain_event_factory.py`, `fifo_manager.py`
- **Řešení fáze 1:** Ponechat v core, přidat anglické aliasy. Fáze 2: přejmenovat.
- **Riziko:** Nízké funkčně, ale vizuálně "contaminated"

**R5: Import chain `src.config` je globální singleton**
- Importován ve 15+ modulech přes `import src.config as config`
- **Problém:** Country-specific config hodnoty (DE loss capping) jsou v globálním configu
- **Řešení:** Rozdělit config na core + country overlay, nebo inject přes pipeline context

**R6: `reporting_utils.py` – mix core + DE**
- `_q()`, `_q_price()`, `_q_qty()` jsou core
- `format_date_german()`, `get_kap_inv_category_for_reporting()` jsou DE
- **Řešení:** Rozdělit na 2 moduly

### ✅ NÍZKÉ

**R7: String references v logování a komentářích**
- "German tax: zero cost basis" v `corporate_action_processor.py`
- "Anlage KAP", "Zeile" v log messages
- **Řešení:** Čistit postupně, nefunkční dopad

---

## 5. Postup refaktoru v 8 krocích

### Krok 1: Definice TaxPlugin Protocol (nový kód, nic nerozbije)
**Soubory:** nový `src/countries/__init__.py`, `src/countries/base.py`
- Definovat `TaxClassifier` Protocol: `classify_rgl(rgl_data, asset_category, ...) → tax_category`
- Definovat `TaxPlugin` Protocol: tax_classifier, loss_offsetting_engine_class, reporter_class
- **Riziko:** Žádné – čistě additivní
- **Test:** Unit test pro Protocol interface

### Krok 2: Extrakce DE tax classification do samostatné funkce
**Soubory:** nový `src/countries/de/__init__.py`, `src/countries/de/tax_classifier.py`
- Extrahovat 3× duplikovaný blok z `fifo_manager.py` do `GermanTaxClassifier.classify_rgl()`
- `fifo_manager.py`: consume metody volají injektovaný `tax_classifier` místo inline logiky
- Přesunout `src/utils/tax_utils.py` obsah do `src/countries/de/tax_rules.py`
- Ponechat re-export v `src/utils/tax_utils.py` pro zpětnou kompatibilitu
- **Riziko:** 🔴 Nejvyšší – nutné pečlivé testování, všechny FIFO testy musí projít
- **Test:** Spustit celou test suite, porovnat RGL výstupy

### Krok 3: Vyčistit `RealizedGainLoss.__post_init__`
**Soubory:** `src/domain/results.py`, `src/countries/de/tax_classifier.py`
- Odstranit přímé volání `get_teilfreistellung_rate_for_fund_type()` z `__post_init__`
- Teilfreistellung výpočet přesunout do DE tax classifier (post-processing)
- Ponechat TF pole v RGL jako Optional (zpětná kompatibilita)
- **Riziko:** Střední – testy ověřují automatický výpočet TF
- **Test:** `test_group6_loss_offsetting.py`, `test_fifo_groups.py`

### Krok 4: Přesun DE-specifických enums a results
**Soubory:** `src/domain/enums.py`, `src/countries/de/enums.py`, `src/countries/de/results.py`
- Přesunout `TaxReportingCategory` do `countries/de/enums.py`
- Přesunout `VorabpauschaleData`, `LossOffsettingResult` do `countries/de/results.py`
- Ponechat re-exporty v původních modulech pro zpětnou kompatibilitu
- **Riziko:** Nízké (re-exporty zachovají funkčnost)
- **Test:** Celá test suite

### Krok 5: Přesun DE loss offsetting a reportingu
**Soubory:** `src/engine/loss_offsetting.py` → `src/countries/de/loss_offsetting.py`, reporting files
- Přesunout `LossOffsettingEngine`
- Přesunout `console_reporter.py`, `pdf_generator.py`
- Rozdělit `reporting_utils.py` na core (`outputs/`) + DE
- Ponechat re-exporty
- **Riziko:** Nízké (čistý přesun + re-export)
- **Test:** `test_group6_loss_offsetting.py`

### Krok 6: Implementace GermanTaxPlugin a wiring
**Soubory:** nový `src/countries/de/plugin.py`, update `src/main.py`, `src/cli.py`
- GermanTaxPlugin zapojuje všechny DE komponenty
- `--country de` flag v CLI (default = de pro zpětnou kompatibilitu)
- `main.py` používá plugin dispatch
- **Riziko:** Střední – mění orchestraci
- **Test:** Celá test suite + manuální smoke test

### Krok 7: Vytvoření CZ country plugin skeleton
**Soubory:** nové `src/countries/cz/*`
- Placeholder implementace `CzechTaxPlugin`
- CZ enums (základní kategorie: §10 ZDP, Příloha č. 2)
- CZ tax classifier skeleton (3-letý time test pro cenné papíry)
- CZ loss offsetting skeleton
- **Riziko:** Žádné – čistě additivní
- **Test:** Unit testy pro CZ plugin interface

### Krok 8: Přesun IBKR parsers do brokers/ibkr/
**Soubory:** `src/parsers/*` → `src/brokers/ibkr/parsers/*`
- Poslední krok – největší počet souborů, ale nejmenší riziko
- Re-exporty z `src/parsers/` pro zpětnou kompatibilitu
- **Riziko:** Nízké (čistý přesun)
- **Test:** Celá test suite

---

## Doporučené pořadí implementace

```
Priorita  Krok  Riziko     Důvod pořadí
────────  ────  ─────────  ──────────────────────────────────────────
   1       1    žádné      Foundation – Protocol definice, nic nerozbije
   2       2    🔴 vysoké  Klíčová separace: DE logika ven z fifo_manager
   3       3    střední    Čistý domain model bez DE závislostí
   4       4    nízké      Enum/result re-organizace, re-exporty chrání
   5       5    nízké      Čistý přesun existujícího kódu
   6       6    střední    Wiring – konečně fungující plugin architektura
   7       7    žádné      CZ skeleton – additivní práce
   8       8    nízké      Parser přesun – kosmetika, velký diff ale safe
```

**Doporučení:** Kroky 1-3 udělat jako první sprint (jádro refaktoru). Kroky 4-6 jako druhý sprint. Kroky 7-8 jako třetí sprint.

Mezi každým krokem spustit `uv run pytest` a ověřit 182 testů PASS.

---

## Poznámky k CZ daňovému modulu

Bez upřesnění zadání připravuji pouze rozšiřitelnou strukturu. Klíčové CZ koncepty, které budou potřeba:

- **Time test:** 3 roky pro cenné papíry (§4 odst. 1 písm. w ZDP), vs. DE 1 rok (§23 EStG)
- **Flat tax:** 15 % / 23 % (od 2024), vs. DE Abgeltungsteuer 25 % + Soli
- **Fondy:** ČR nemá Teilfreistellung – celý výnos je zdanitelný
- **Deriváty:** ČR §10 odst. 1 písm. b) bod 3 ZDP – jiná kategorizace než DE
- **WHT credit:** ČR §38f ZDP – metoda zápočtu, vs. DE Anrechnungsmethode
- **Cílová měna:** CZK (ne EUR) – je potřeba rozšířit FX enrichment

⚠️ *Toto jsou technické poznámky, ne daňové poradenství. Konkrétní CZ daňové interpretace vyžadují upřesnění.*
