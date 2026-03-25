# src/countries/cz/plugin.py
"""
Czech Republic TaxPlugin implementation.

Data flow:
1. Core pipeline produces ``RealizedGainLoss`` items and ``FinancialEvent`` items.
2. ``CzechTaxClassifier.classify()`` assigns a ``CzTaxSection`` bucket to each RGL.
3. ``CzechTaxAggregator.aggregate()`` converts each item to CZK via
   ``CzCurrencyConverter`` (direct foreign→CZK, per-event, daily ČNB rate)
   and sums the buckets into a ``TaxResult`` with audit metadata.
4. ``CzechOutputRenderer`` prints/exports the result.
"""
from __future__ import annotations

import datetime
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from src.countries.base import (
    OutputRenderer,
    TaxAggregator,
    TaxClassifier,
    TaxPlugin,
    TaxResult,
    TaxResultSection,
)
from src.countries.cz.config import CzTaxConfig
from src.countries.cz.enums import CzHoldingTestRule, CzTaxSection
from src.countries.cz.fx_policy import (
    CzCurrencyConverter,
    CzFxPolicyConfig,
    FxConversionRecord,
)
from src.countries.cz.item_builder import build_tax_items
from src.countries.cz.tax_items import CzTaxItem, CzTaxItemType, CzWhtRecord
from src.domain.assets import Asset
from src.domain.enums import AssetCategory, FinancialEventType
from src.domain.events import (
    CashFlowEvent,
    FinancialEvent,
    WithholdingTaxEvent,
)
from src.domain.results import RealizedGainLoss
from src.identification.asset_resolver import AssetResolver
from src.utils.exchange_rate_provider import ExchangeRateProvider
from src.utils.type_utils import parse_ibkr_date

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CzechTaxClassifier
# ---------------------------------------------------------------------------

class CzechTaxClassifier:
    """
    Assigns a ``CzTaxSection`` to each ``RealizedGainLoss``.

    The section is stored in ``rgl.tax_reporting_category`` as a *string*
    (the enum name) because the core ``RealizedGainLoss`` field is typed
    ``Optional[TaxReportingCategory]`` (German enum).  During this skeleton
    phase we store the CZ section name in a new attribute instead.

    PLACEHOLDER: holding-period test logic is simplified;
    full implementation needs acquisition-date analysis.
    """

    def __init__(self, config: Optional[CzTaxConfig] = None):
        self.config = config or CzTaxConfig()

    # ---- public API (satisfies TaxClassifier Protocol) ----

    def classify(
        self,
        rgl: RealizedGainLoss,
        asset: Optional[Asset] = None,
    ) -> None:
        """Classify *rgl* in-place for Czech tax purposes.

        Sets ``rgl.cz_tax_section`` (a dynamic attribute) to a
        ``CzTaxSection`` enum value.  Also sets
        ``net_gain_loss_after_teilfreistellung_eur`` to ``gross_gain_loss_eur``
        (CZ has no partial exemption for funds).
        """
        cat = rgl.asset_category_at_realization
        section = self._map_category_to_section(cat)

        # Holding-period exemption check for securities
        if section == CzTaxSection.CZ_10_SECURITIES:
            if self._is_exempt_by_holding_test(rgl):
                section = CzTaxSection.CZ_EXEMPT_TIME_TEST

        # Store CZ section as dynamic attribute (core RGL has no CZ field)
        rgl.cz_tax_section = section  # type: ignore[attr-defined]

        # CZ has no Teilfreistellung — net = gross
        if rgl.gross_gain_loss_eur is not None:
            rgl.net_gain_loss_after_teilfreistellung_eur = rgl.gross_gain_loss_eur
        else:
            rgl.net_gain_loss_after_teilfreistellung_eur = None

    # ---- internals ----

    @staticmethod
    def _map_category_to_section(cat: AssetCategory) -> CzTaxSection:
        """Map core ``AssetCategory`` → ``CzTaxSection``."""
        _MAP = {
            AssetCategory.STOCK: CzTaxSection.CZ_10_SECURITIES,
            AssetCategory.BOND: CzTaxSection.CZ_10_SECURITIES,
            AssetCategory.INVESTMENT_FUND: CzTaxSection.CZ_10_SECURITIES,
            AssetCategory.OPTION: CzTaxSection.CZ_10_OPTIONS,
            AssetCategory.CFD: CzTaxSection.CZ_10_OPTIONS,
            AssetCategory.PRIVATE_SALE_ASSET: CzTaxSection.CZ_10_SECURITIES,
        }
        return _MAP.get(cat, CzTaxSection.CZ_10_SECURITIES)

    def _is_exempt_by_holding_test(self, rgl: RealizedGainLoss) -> bool:
        """PLACEHOLDER: simplified 3-year test.

        Full implementation needs:
        - acquisition date vs. 2014-01-01 threshold
        - annual CZK 100k limit (2025+ amendment)
        - fund-specific rules
        """
        threshold_days = self.config.holding_test_years * 365
        if rgl.holding_period_days is not None and rgl.holding_period_days > threshold_days:
            return True
        return False


# ---------------------------------------------------------------------------
# CzechTaxAggregator
# ---------------------------------------------------------------------------

class CzechTaxAggregator:
    """
    Builds ``CzTaxItem`` objects from core outputs, then aggregates
    them into CZ ``TaxResult`` sections.

    Every amount is converted to CZK **per-event** via ``CzCurrencyConverter``.
    Individual ``CzTaxItem``s (with full audit trail) are stored in
    ``TaxResult.country_result["items"]`` for downstream use (time test,
    WHT credit, JSON/XLSX export).

    PLACEHOLDER: expense deduction rules (§10/4 ZDP) not applied.
    """

    def __init__(
        self,
        config: Optional[CzTaxConfig] = None,
        fx_converter: Optional[CzCurrencyConverter] = None,
    ):
        self.config = config or CzTaxConfig()
        self._fx = fx_converter

    def aggregate(
        self,
        realized_gains_losses: List[RealizedGainLoss],
        financial_events: List[FinancialEvent],
        asset_resolver: AssetResolver,
        tax_year: int,
    ) -> TaxResult:
        TWO = Decimal("0.01")
        ZERO = Decimal(0)

        # --- Build individual tax items with FX + WHT linking ---
        items, fx_records = build_tax_items(
            realized_gains_losses=realized_gains_losses,
            financial_events=financial_events,
            asset_resolver=asset_resolver,
            fx=self._fx,
        )

        # --- Aggregate by section ---
        dividend_amt = ZERO
        dividend_wht = ZERO
        interest_amt = ZERO

        sec_gains = ZERO
        sec_losses = ZERO
        opt_gains = ZERO
        opt_losses = ZERO

        # Determine amount field: CZK if converter available, else EUR
        has_fx = self._fx is not None

        for it in items:
            if it.section == CzTaxSection.CZ_8_DIVIDENDS:
                amt = (it.amount_czk if has_fx else it.amount_eur) or ZERO
                dividend_amt += amt
                dividend_wht += it.total_wht_czk() if has_fx else sum(
                    (r.original_amount for r in it.wht_records), ZERO
                )

            elif it.section == CzTaxSection.CZ_8_INTEREST:
                amt = (it.amount_czk if has_fx else it.amount_eur) or ZERO
                interest_amt += amt

            elif it.section == CzTaxSection.CZ_10_SECURITIES:
                gl = (it.gain_loss_czk if has_fx else it.gain_loss_eur) or ZERO
                if gl >= ZERO:
                    sec_gains += gl
                else:
                    sec_losses += gl.copy_abs()

            elif it.section == CzTaxSection.CZ_10_OPTIONS:
                gl = (it.gain_loss_czk if has_fx else it.gain_loss_eur) or ZERO
                if gl >= ZERO:
                    opt_gains += gl
                else:
                    opt_losses += gl.copy_abs()

        cur = "CZK" if has_fx else "EUR"

        # --- Build TaxResult sections ---
        sections: Dict[str, TaxResultSection] = {}

        sections["cz_8_dividends"] = TaxResultSection(
            section_key="cz_8_dividends",
            label=self.config.section_labels.get("cz_8_dividends", "§8 – Dividendy"),
            line_items={
                f"gross_dividends_{cur.lower()}": dividend_amt.quantize(TWO),
                f"wht_paid_{cur.lower()}": dividend_wht.quantize(TWO),
            },
            notes=([] if has_fx else ["no FX converter — amounts in EUR"]),
        )

        sections["cz_8_interest"] = TaxResultSection(
            section_key="cz_8_interest",
            label=self.config.section_labels.get("cz_8_interest", "§8 – Úroky"),
            line_items={
                f"gross_interest_{cur.lower()}": interest_amt.quantize(TWO),
            },
            notes=([] if has_fx else ["no FX converter — amounts in EUR"]),
        )

        sections["cz_10_securities"] = TaxResultSection(
            section_key="cz_10_securities",
            label=self.config.section_labels.get("cz_10_securities", "§10 – Cenné papíry"),
            line_items={
                f"taxable_gains_{cur.lower()}": sec_gains.quantize(TWO),
                f"deductible_losses_{cur.lower()}": sec_losses.quantize(TWO),
                f"net_{cur.lower()}": (sec_gains - sec_losses).quantize(TWO),
            },
            notes=["PLACEHOLDER: expense deduction rules (§10/4 ZDP) not applied"],
        )

        sections["cz_10_options"] = TaxResultSection(
            section_key="cz_10_options",
            label=self.config.section_labels.get("cz_10_options", "§10 – Opce a deriváty"),
            line_items={
                f"taxable_gains_{cur.lower()}": opt_gains.quantize(TWO),
                f"deductible_losses_{cur.lower()}": opt_losses.quantize(TWO),
                f"net_{cur.lower()}": (opt_gains - opt_losses).quantize(TWO),
            },
            notes=[],
        )

        return TaxResult(
            country_code="cz",
            tax_year=tax_year,
            sections=sections,
            country_result={
                "items": items,
                "fx_conversion_records": fx_records,
                "fx_policy": self.config.fx_policy,
                "currency": cur,
            },
        )


# ---------------------------------------------------------------------------
# CzechOutputRenderer
# ---------------------------------------------------------------------------

class CzechOutputRenderer:
    """
    Renders a CZ ``TaxResult`` to console / PDF.

    PLACEHOLDER: only console output implemented (simple dump).
    PDF generation is a future step.
    """

    def render_console(
        self,
        tax_result: TaxResult,
        realized_gains_losses: List[RealizedGainLoss],
        financial_events: List[FinancialEvent],
        asset_resolver: AssetResolver,
    ) -> None:
        cr = tax_result.country_result or {}
        cur = cr.get("currency", "EUR")
        policy = cr.get("fx_policy")
        policy_desc = f" | FX: {policy.source} / {policy.mode.name.lower()}" if policy else ""

        print(f"\n--- Přehled pro daňové přiznání ČR za rok {tax_result.tax_year}{policy_desc} ---")
        print(f"--- Částky v {cur} ---\n")

        for key, section in tax_result.sections.items():
            print(f"  {section.label}")
            for item_key, value in section.line_items.items():
                print(f"    {item_key}: {value}")
            for note in section.notes:
                print(f"    ⚠ {note}")
            print()

        fx_records = cr.get("fx_conversion_records", [])
        if fx_records:
            print(f"  FX konverzí provedeno: {len(fx_records)}")

        print("--- Konec přehledu ---\n")

    def render_pdf(
        self,
        tax_result: TaxResult,
        realized_gains_losses: List[RealizedGainLoss],
        financial_events: List[FinancialEvent],
        asset_resolver: AssetResolver,
        output_path: str,
    ) -> None:
        logger.warning(
            f"CZ PDF report generation is not implemented yet. "
            f"Output path '{output_path}' ignored."
        )


# ---------------------------------------------------------------------------
# CzechTaxPlugin
# ---------------------------------------------------------------------------

class CzechTaxPlugin:
    """
    Czech Republic tax plugin implementing the ``TaxPlugin`` Protocol.

    Usage::

        plugin = CzechTaxPlugin()
        classifier = plugin.get_tax_classifier()
        aggregator = plugin.get_tax_aggregator()
        renderer  = plugin.get_output_renderer()

    To enable CZK conversion, supply an ``ExchangeRateProvider``
    (typically ``CNBExchangeRateProvider``) or let the plugin
    create one from the configured ``fx_policy.source``::

        from src.utils.fx_provider_factory import create_fx_provider
        provider = create_fx_provider("cnb")
        plugin = CzechTaxPlugin(fx_provider=provider)
    """

    def __init__(
        self,
        config: Optional[CzTaxConfig] = None,
        fx_provider: Optional[ExchangeRateProvider] = None,
        **kwargs,
    ):
        self._config = config or CzTaxConfig()
        self._fx_provider = fx_provider
        # Accept and ignore unknown kwargs for registry compatibility
        if kwargs:
            logger.debug(f"CzechTaxPlugin ignoring unknown kwargs: {list(kwargs.keys())}")

    @property
    def country_code(self) -> str:
        return "cz"

    @property
    def config(self) -> CzTaxConfig:
        return self._config

    def get_tax_classifier(self) -> CzechTaxClassifier:
        return CzechTaxClassifier(config=self._config)

    def get_tax_aggregator(self) -> CzechTaxAggregator:
        fx_converter: Optional[CzCurrencyConverter] = None
        if self._fx_provider is not None:
            fx_converter = CzCurrencyConverter(
                provider=self._fx_provider,
                policy=self._config.fx_policy,
            )
        return CzechTaxAggregator(config=self._config, fx_converter=fx_converter)

    def get_output_renderer(self) -> CzechOutputRenderer:
        return CzechOutputRenderer()
