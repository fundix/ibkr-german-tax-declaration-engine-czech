# tests/test_country_plugin_interface.py
"""
Tests for the country tax plugin foundation layer.

Verifies:
1. Protocol definitions are usable at runtime.
2. GermanTaxPlugin satisfies TaxPlugin Protocol.
3. GermanTaxClassifier produces correct TaxReportingCategory for each AssetCategory.
4. GermanTaxAggregator wraps LossOffsettingEngine and returns a TaxResult.
5. Registry lookup works.
6. FxProvider Protocol is satisfied by existing ExchangeRateProvider.
"""
import uuid
from decimal import Decimal
from typing import List

import pytest

from src.countries.base import (
    FxProvider,
    OutputRenderer,
    TaxAggregator,
    TaxClassifier,
    TaxPlugin,
    TaxResult,
    TaxResultSection,
)
from src.countries.de.plugin import (
    GermanOutputRenderer,
    GermanTaxAggregator,
    GermanTaxClassifier,
    GermanTaxPlugin,
    _kap_inv_gain_category,
)
from src.countries.registry import get_tax_plugin, available_countries
from src.domain.assets import Asset
from src.domain.enums import (
    AssetCategory,
    InvestmentFundType,
    RealizationType,
    TaxReportingCategory,
)
from src.domain.results import RealizedGainLoss
from src.utils.exchange_rate_provider import (
    ECBExchangeRateProvider,
    ExchangeRateProvider,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rgl(
    asset_category: AssetCategory,
    gross_gain_loss: Decimal,
    holding_period_days: int = 100,
    fund_type: InvestmentFundType = None,
    realization_type: RealizationType = RealizationType.LONG_POSITION_SALE,
) -> RealizedGainLoss:
    """Create a minimal RealizedGainLoss for classification tests."""
    return RealizedGainLoss(
        originating_event_id=uuid.uuid4(),
        asset_internal_id=uuid.uuid4(),
        asset_category_at_realization=asset_category,
        acquisition_date="2023-01-15",
        realization_date="2023-06-20",
        realization_type=realization_type,
        quantity_realized=Decimal("10"),
        unit_cost_basis_eur=Decimal("100"),
        unit_realization_value_eur=Decimal("100") + gross_gain_loss / Decimal("10"),
        total_cost_basis_eur=Decimal("1000"),
        total_realization_value_eur=Decimal("1000") + gross_gain_loss,
        gross_gain_loss_eur=gross_gain_loss,
        holding_period_days=holding_period_days,
        fund_type_at_sale=fund_type,
    )


# ---------------------------------------------------------------------------
# Protocol conformance tests
# ---------------------------------------------------------------------------

class TestProtocolConformance:
    """Verify that concrete classes satisfy their respective Protocols."""

    def test_german_tax_classifier_is_tax_classifier(self):
        assert isinstance(GermanTaxClassifier(), TaxClassifier)

    def test_german_tax_aggregator_is_tax_aggregator(self):
        agg = GermanTaxAggregator()
        assert isinstance(agg, TaxAggregator)

    def test_german_output_renderer_is_output_renderer(self):
        renderer = GermanOutputRenderer()
        assert isinstance(renderer, OutputRenderer)

    def test_german_tax_plugin_is_tax_plugin(self):
        plugin = GermanTaxPlugin()
        assert isinstance(plugin, TaxPlugin)

    def test_ecb_provider_is_fx_provider(self):
        """ExchangeRateProvider base class satisfies FxProvider Protocol."""
        assert issubclass(ExchangeRateProvider, FxProvider) or isinstance(
            ExchangeRateProvider(), FxProvider
        )


# ---------------------------------------------------------------------------
# GermanTaxPlugin tests
# ---------------------------------------------------------------------------

class TestGermanTaxPlugin:
    def test_country_code(self):
        plugin = GermanTaxPlugin()
        assert plugin.country_code == "de"

    def test_get_tax_classifier_returns_instance(self):
        plugin = GermanTaxPlugin()
        classifier = plugin.get_tax_classifier()
        assert isinstance(classifier, GermanTaxClassifier)

    def test_get_tax_aggregator_returns_instance(self):
        plugin = GermanTaxPlugin()
        aggregator = plugin.get_tax_aggregator()
        assert isinstance(aggregator, GermanTaxAggregator)

    def test_get_output_renderer_returns_instance(self):
        plugin = GermanTaxPlugin()
        renderer = plugin.get_output_renderer()
        assert isinstance(renderer, GermanOutputRenderer)


# ---------------------------------------------------------------------------
# GermanTaxClassifier tests
# ---------------------------------------------------------------------------

class TestGermanTaxClassifier:
    """Verify classification logic matches the existing inline code in fifo_manager."""

    def setup_method(self):
        self.classifier = GermanTaxClassifier()

    def test_stock_gain(self):
        rgl = _make_rgl(AssetCategory.STOCK, Decimal("500"))
        self.classifier.classify(rgl)
        assert rgl.tax_reporting_category == TaxReportingCategory.ANLAGE_KAP_AKTIEN_GEWINN

    def test_stock_loss(self):
        rgl = _make_rgl(AssetCategory.STOCK, Decimal("-300"))
        self.classifier.classify(rgl)
        assert rgl.tax_reporting_category == TaxReportingCategory.ANLAGE_KAP_AKTIEN_VERLUST

    def test_bond_gain(self):
        rgl = _make_rgl(AssetCategory.BOND, Decimal("200"))
        self.classifier.classify(rgl)
        assert rgl.tax_reporting_category == TaxReportingCategory.ANLAGE_KAP_SONSTIGE_KAPITALERTRAEGE

    def test_bond_loss(self):
        rgl = _make_rgl(AssetCategory.BOND, Decimal("-150"))
        self.classifier.classify(rgl)
        assert rgl.tax_reporting_category == TaxReportingCategory.ANLAGE_KAP_SONSTIGE_VERLUSTE

    def test_option_gain(self):
        rgl = _make_rgl(AssetCategory.OPTION, Decimal("1000"))
        self.classifier.classify(rgl)
        assert rgl.tax_reporting_category == TaxReportingCategory.ANLAGE_KAP_TERMIN_GEWINN

    def test_option_loss(self):
        rgl = _make_rgl(AssetCategory.OPTION, Decimal("-800"))
        self.classifier.classify(rgl)
        assert rgl.tax_reporting_category == TaxReportingCategory.ANLAGE_KAP_TERMIN_VERLUST

    def test_cfd_gain(self):
        rgl = _make_rgl(AssetCategory.CFD, Decimal("50"))
        self.classifier.classify(rgl)
        assert rgl.tax_reporting_category == TaxReportingCategory.ANLAGE_KAP_TERMIN_GEWINN

    def test_cfd_loss(self):
        rgl = _make_rgl(AssetCategory.CFD, Decimal("-50"))
        self.classifier.classify(rgl)
        assert rgl.tax_reporting_category == TaxReportingCategory.ANLAGE_KAP_TERMIN_VERLUST

    def test_investment_fund_aktienfonds(self):
        rgl = _make_rgl(
            AssetCategory.INVESTMENT_FUND,
            Decimal("400"),
            fund_type=InvestmentFundType.AKTIENFONDS,
        )
        self.classifier.classify(rgl)
        assert rgl.tax_reporting_category == TaxReportingCategory.ANLAGE_KAP_INV_AKTIENFONDS_GEWINN_GROSS
        assert rgl.teilfreistellung_rate_applied == Decimal("0.30")

    def test_investment_fund_mischfonds(self):
        rgl = _make_rgl(
            AssetCategory.INVESTMENT_FUND,
            Decimal("400"),
            fund_type=InvestmentFundType.MISCHFONDS,
        )
        self.classifier.classify(rgl)
        assert rgl.tax_reporting_category == TaxReportingCategory.ANLAGE_KAP_INV_MISCHFONDS_GEWINN_GROSS
        assert rgl.teilfreistellung_rate_applied == Decimal("0.15")

    def test_investment_fund_immobilienfonds(self):
        rgl = _make_rgl(
            AssetCategory.INVESTMENT_FUND,
            Decimal("400"),
            fund_type=InvestmentFundType.IMMOBILIENFONDS,
        )
        self.classifier.classify(rgl)
        assert rgl.tax_reporting_category == TaxReportingCategory.ANLAGE_KAP_INV_IMMOBILIENFONDS_GEWINN_GROSS
        assert rgl.teilfreistellung_rate_applied == Decimal("0.60")

    def test_investment_fund_auslands_immobilienfonds(self):
        rgl = _make_rgl(
            AssetCategory.INVESTMENT_FUND,
            Decimal("400"),
            fund_type=InvestmentFundType.AUSLANDS_IMMOBILIENFONDS,
        )
        self.classifier.classify(rgl)
        assert rgl.tax_reporting_category == TaxReportingCategory.ANLAGE_KAP_INV_AUSLANDS_IMMOBILIENFONDS_GEWINN_GROSS
        assert rgl.teilfreistellung_rate_applied == Decimal("0.80")

    def test_investment_fund_sonstige(self):
        rgl = _make_rgl(
            AssetCategory.INVESTMENT_FUND,
            Decimal("400"),
            fund_type=InvestmentFundType.SONSTIGE_FONDS,
        )
        self.classifier.classify(rgl)
        assert rgl.tax_reporting_category == TaxReportingCategory.ANLAGE_KAP_INV_SONSTIGE_FONDS_GEWINN_GROSS
        assert rgl.teilfreistellung_rate_applied == Decimal("0.00")

    def test_investment_fund_none_fund_type(self):
        rgl = _make_rgl(
            AssetCategory.INVESTMENT_FUND,
            Decimal("400"),
            fund_type=None,
        )
        self.classifier.classify(rgl)
        assert rgl.fund_type_at_sale == InvestmentFundType.NONE
        assert rgl.tax_reporting_category == TaxReportingCategory.ANLAGE_KAP_INV_SONSTIGE_FONDS_GEWINN_GROSS

    def test_private_sale_within_speculation_period(self):
        rgl = _make_rgl(
            AssetCategory.PRIVATE_SALE_ASSET,
            Decimal("200"),
            holding_period_days=180,
        )
        self.classifier.classify(rgl)
        assert rgl.is_taxable_under_section_23 is True
        assert rgl.tax_reporting_category == TaxReportingCategory.SECTION_23_ESTG_TAXABLE_GAIN

    def test_private_sale_loss_within_speculation_period(self):
        rgl = _make_rgl(
            AssetCategory.PRIVATE_SALE_ASSET,
            Decimal("-100"),
            holding_period_days=180,
        )
        self.classifier.classify(rgl)
        assert rgl.is_taxable_under_section_23 is True
        assert rgl.tax_reporting_category == TaxReportingCategory.SECTION_23_ESTG_TAXABLE_LOSS

    def test_private_sale_exempt_holding_period_met(self):
        rgl = _make_rgl(
            AssetCategory.PRIVATE_SALE_ASSET,
            Decimal("200"),
            holding_period_days=400,
        )
        self.classifier.classify(rgl)
        assert rgl.is_taxable_under_section_23 is False
        assert rgl.tax_reporting_category == TaxReportingCategory.SECTION_23_ESTG_EXEMPT_HOLDING_PERIOD_MET

    def test_stock_zero_gain(self):
        """Zero gain should classify as GEWINN (>= 0 check)."""
        rgl = _make_rgl(AssetCategory.STOCK, Decimal("0"))
        self.classifier.classify(rgl)
        assert rgl.tax_reporting_category == TaxReportingCategory.ANLAGE_KAP_AKTIEN_GEWINN


# ---------------------------------------------------------------------------
# KAP-INV category mapping
# ---------------------------------------------------------------------------

class TestKapInvGainCategory:
    def test_all_fund_types_mapped(self):
        for ft in InvestmentFundType:
            cat = _kap_inv_gain_category(ft)
            assert isinstance(cat, TaxReportingCategory)
            assert "KAP_INV" in cat.name


# ---------------------------------------------------------------------------
# TaxResult dataclass
# ---------------------------------------------------------------------------

class TestTaxResult:
    def test_construction(self):
        section = TaxResultSection(
            section_key="test",
            label="Test Section",
            line_items={"line_1": Decimal("100.00")},
        )
        result = TaxResult(
            country_code="de",
            tax_year=2023,
            sections={"test": section},
            country_result=None,
        )
        assert result.country_code == "de"
        assert result.tax_year == 2023
        assert "test" in result.sections
        assert result.sections["test"].line_items["line_1"] == Decimal("100.00")

    def test_empty_construction(self):
        result = TaxResult(country_code="cz", tax_year=2024)
        assert result.sections == {}
        assert result.country_result is None


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_get_german_plugin(self):
        plugin = get_tax_plugin("de")
        assert isinstance(plugin, GermanTaxPlugin)
        assert plugin.country_code == "de"

    def test_get_german_plugin_uppercase(self):
        plugin = get_tax_plugin("DE")
        assert isinstance(plugin, GermanTaxPlugin)

    def test_unknown_country_raises(self):
        with pytest.raises(ValueError, match="Unknown country code"):
            get_tax_plugin("xx")

    def test_available_countries(self):
        codes = available_countries()
        assert "de" in codes

    def test_kwargs_forwarded(self):
        plugin = get_tax_plugin("de", eoy_mismatch_count=5)
        assert plugin._eoy_mismatch_count == 5


# ---------------------------------------------------------------------------
# FxProvider Protocol
# ---------------------------------------------------------------------------

class TestFxProviderProtocol:
    def test_exchange_rate_provider_base_is_fx_provider(self):
        """The existing base class structurally matches FxProvider."""
        provider = ExchangeRateProvider()
        assert isinstance(provider, FxProvider)

    def test_mock_provider_is_fx_provider(self):
        from tests.support.mock_providers import MockECBExchangeRateProvider
        provider = MockECBExchangeRateProvider()
        assert isinstance(provider, FxProvider)
