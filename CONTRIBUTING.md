# Contributing

## Setup

```bash
git clone https://github.com/fundix/ibkr-german-tax-declaration-engine-czech.git
cd ibkr-german-tax-declaration-engine-czech
uv sync
uv run pytest  # should pass 444+ tests
```

## Core Principles

1. **Country logic stays in `countries/xx/`.** Never add tax rules to `domain/`, `engine/`, `parsers/`, or `utils/`.
2. **Small, safe commits.** Each change should pass `uv run pytest` before committing.
3. **Tests for every new interface.** New modules need tests. Refactors need regression tests.
4. **Document policy assumptions.** If a tax rule is uncertain, add an explicit note — don't silently pick an interpretation.
5. **No unnecessary dependencies.** Check `pyproject.toml` before adding packages.

## Running Tests

```bash
uv run pytest                    # all tests
uv run pytest tests/test_cz_*   # CZ plugin tests only
uv run pytest tests/test_fifo_* # FIFO core tests only
uv run pytest -v --tb=short     # verbose with short tracebacks
uv run pytest -x                # stop on first failure
```

## Adding a New Country Plugin

1. Create `src/countries/xx/__init__.py` and `src/countries/xx/plugin.py`.
2. Implement the `TaxPlugin` Protocol (see `src/countries/base.py`).
3. Register in `src/countries/registry.py`.
4. Add tests in `tests/test_xx_*.py`.
5. The `--country xx` CLI flag will work automatically.

See [docs/architecture.md](docs/architecture.md) for the full layer diagram.

## Adding Country-Specific Tax Logic

Follow the CZ plugin pattern:

```
tax_items.py       → Item model with audit fields
item_builder.py    → Converts core RGLs/events to country items
time_test.py       → Exemption evaluator (in-place)
annual_limit.py    → Another evaluator (in-place)
loss_offsetting.py → Netting computation
foreign_tax_credit.py → FTC computation
tax_liability.py   → Rate application + FTC finalization
form_mapping.py    → DAP-oriented output (reads liability, no recomputation)
exporters/         → JSON, XLSX (reads TaxResult, no tax logic)
```

Each step reads the previous step's output. No step should recompute what an earlier step determined.

## Coding Style

- Use `Decimal` for all financial amounts. Initialize from strings: `Decimal("0.15")`.
- Use dataclasses for models. Add `to_dict()` for JSON/XLSX export.
- Use `Optional` with explicit `None` handling — don't silently drop missing data.
- Prefer explicit over clever. Tax code needs to be auditable.

## Documenting Policy Uncertainty

When implementing a tax rule where the interpretation is uncertain:

```python
# POLICY ASSUMPTION: <description of the assumption>
# Alternative interpretation: <what else it could mean>
# Reference: §XX ZDP / SZDZ <country>
```

For runtime output, add notes to `limitation_notes` or `tax_review_note` fields so they appear in exports.

## Pull Request Checklist

- [ ] `uv run pytest` passes with zero failures
- [ ] No country-specific logic added to core modules
- [ ] New modules have tests
- [ ] Policy assumptions are documented in code and output notes
- [ ] No hardcoded tax rates outside of config
