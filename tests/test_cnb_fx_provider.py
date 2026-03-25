# tests/test_cnb_fx_provider.py
"""
Tests for the CNB exchange rate provider.

Covers:
1. Parsing ČNB text format
2. Rate lookup with cache hits / misses
3. Fallback for weekends/holidays
4. Failure modes (network error, malformed response, missing currency)
5. Cache persistence (load / save)
6. CZK identity rate
7. Currency code mapping
8. Mock-friendly design (subclass + inject parse results)
9. FxProvider Protocol conformance
10. Provider factory
"""
import json
import os
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, Optional, Set
from unittest.mock import patch, MagicMock

import pytest

from src.countries.base import FxProvider
from src.utils.cnb_exchange_rate_provider import CNBExchangeRateProvider
from src.utils.exchange_rate_provider import ExchangeRateProvider
from src.utils.fx_provider_factory import create_fx_provider, available_fx_providers


# ---------------------------------------------------------------------------
# Sample ČNB response text
# ---------------------------------------------------------------------------

SAMPLE_CNB_TEXT = """\
25.03.2025 #59
země|měna|množství|kód|kurz
Austrálie|dolar|1|AUD|14,536
EMU|euro|1|EUR|24,320
Japonsko|jen|100|JPY|15,123
USA|dolar|1|USD|22,345
Velká Británie|libra|1|GBP|28,910
"""

SAMPLE_CNB_TEXT_2 = """\
24.03.2025 #58
země|měna|množství|kód|kurz
EMU|euro|1|EUR|24,250
USA|dolar|1|USD|22,200
"""


# ---------------------------------------------------------------------------
# MockCNBProvider — replaces HTTP calls with canned responses
# ---------------------------------------------------------------------------

class MockCNBProvider(CNBExchangeRateProvider):
    """
    A mock CNB provider that returns pre-configured text responses
    instead of making HTTP requests.  Useful for unit tests.

    Usage::

        responses = {
            date(2025, 3, 25): SAMPLE_CNB_TEXT,
            date(2025, 3, 24): SAMPLE_CNB_TEXT_2,
        }
        provider = MockCNBProvider(responses=responses)
        rate = provider.get_rate(date(2025, 3, 25), "USD")
    """

    def __init__(
        self,
        responses: Optional[Dict[date, Optional[str]]] = None,
        **kwargs,
    ):
        self._mock_responses = responses or {}
        # Use a temp file for cache to avoid polluting the real cache
        if "cache_file_path" not in kwargs:
            kwargs["cache_file_path"] = os.path.join(
                tempfile.mkdtemp(), "mock_cnb_cache.json"
            )
        super().__init__(**kwargs)

    def _fetch_rates_for_date(self, query_date: date) -> Optional[Dict[str, Decimal]]:
        text = self._mock_responses.get(query_date)
        if text is None:
            return None
        return self._parse_cnb_text(text, query_date)


# ---------------------------------------------------------------------------
# Parsing tests
# ---------------------------------------------------------------------------

class TestCnbParsing:
    def test_parse_standard_response(self):
        rates = CNBExchangeRateProvider._parse_cnb_text(SAMPLE_CNB_TEXT, date(2025, 3, 25))
        assert rates is not None
        assert "USD" in rates
        assert "EUR" in rates
        assert "AUD" in rates
        assert "GBP" in rates
        assert "JPY" in rates

    def test_usd_rate_normalised(self):
        """1 USD = 22.345 CZK → foreign_per_czk = 1 / 22.345."""
        rates = CNBExchangeRateProvider._parse_cnb_text(SAMPLE_CNB_TEXT, date(2025, 3, 25))
        expected = Decimal("1") / Decimal("22.345")
        assert abs(rates["USD"] - expected) < Decimal("0.00001")

    def test_eur_rate_normalised(self):
        """1 EUR = 24.320 CZK → foreign_per_czk = 1 / 24.320."""
        rates = CNBExchangeRateProvider._parse_cnb_text(SAMPLE_CNB_TEXT, date(2025, 3, 25))
        expected = Decimal("1") / Decimal("24.320")
        assert abs(rates["EUR"] - expected) < Decimal("0.00001")

    def test_jpy_rate_with_amount_100(self):
        """100 JPY = 15.123 CZK → foreign_per_czk = 100 / 15.123."""
        rates = CNBExchangeRateProvider._parse_cnb_text(SAMPLE_CNB_TEXT, date(2025, 3, 25))
        expected = Decimal("100") / Decimal("15.123")
        assert abs(rates["JPY"] - expected) < Decimal("0.001")

    def test_parse_empty_response(self):
        rates = CNBExchangeRateProvider._parse_cnb_text("", date(2025, 3, 25))
        assert rates is None

    def test_parse_header_only(self):
        text = "25.03.2025 #59\nzemě|měna|množství|kód|kurz\n"
        rates = CNBExchangeRateProvider._parse_cnb_text(text, date(2025, 3, 25))
        assert rates is None

    def test_parse_malformed_line_skipped(self):
        text = (
            "25.03.2025 #59\n"
            "země|měna|množství|kód|kurz\n"
            "bad line without pipes\n"
            "USA|dolar|1|USD|22,345\n"
        )
        rates = CNBExchangeRateProvider._parse_cnb_text(text, date(2025, 3, 25))
        assert rates is not None
        assert "USD" in rates
        assert len(rates) == 1

    def test_parse_zero_rate_skipped(self):
        text = (
            "25.03.2025 #59\n"
            "země|měna|množství|kód|kurz\n"
            "Test|testcur|1|TST|0,000\n"
            "USA|dolar|1|USD|22,345\n"
        )
        rates = CNBExchangeRateProvider._parse_cnb_text(text, date(2025, 3, 25))
        assert "TST" not in rates
        assert "USD" in rates


# ---------------------------------------------------------------------------
# Lookup tests (via MockCNBProvider)
# ---------------------------------------------------------------------------

class TestCnbLookup:
    def setup_method(self):
        self.responses = {
            date(2025, 3, 25): SAMPLE_CNB_TEXT,
            date(2025, 3, 24): SAMPLE_CNB_TEXT_2,
        }
        self.provider = MockCNBProvider(responses=self.responses)

    def test_czk_returns_one(self):
        rate = self.provider.get_rate(date(2025, 3, 25), "CZK")
        assert rate == Decimal("1.0")

    def test_czk_case_insensitive(self):
        rate = self.provider.get_rate(date(2025, 3, 25), "czk")
        assert rate == Decimal("1.0")

    def test_usd_lookup(self):
        rate = self.provider.get_rate(date(2025, 3, 25), "USD")
        assert rate is not None
        expected = Decimal("1") / Decimal("22.345")
        assert abs(rate - expected) < Decimal("0.00001")

    def test_eur_lookup(self):
        rate = self.provider.get_rate(date(2025, 3, 25), "EUR")
        assert rate is not None
        expected = Decimal("1") / Decimal("24.320")
        assert abs(rate - expected) < Decimal("0.00001")

    def test_unknown_currency_returns_none(self):
        rate = self.provider.get_rate(date(2025, 3, 25), "XYZ")
        assert rate is None

    def test_cache_hit_no_refetch(self):
        """Second call for the same date should use cache (not call fetch)."""
        self.provider.get_rate(date(2025, 3, 25), "USD")  # populates cache
        # Replace responses so fetch would fail
        self.provider._mock_responses = {}
        rate = self.provider.get_rate(date(2025, 3, 25), "USD")
        assert rate is not None  # served from cache


# ---------------------------------------------------------------------------
# Fallback tests
# ---------------------------------------------------------------------------

class TestCnbFallback:
    def test_fallback_to_previous_day(self):
        """If target date has no data, fall back to previous day."""
        responses = {
            # No data for March 26 (Wednesday missing)
            date(2025, 3, 25): SAMPLE_CNB_TEXT,
        }
        provider = MockCNBProvider(responses=responses)
        rate = provider.get_rate(date(2025, 3, 26), "USD")
        assert rate is not None

    def test_weekend_fallback(self):
        """Saturday → Friday → data."""
        responses = {
            date(2025, 3, 21): SAMPLE_CNB_TEXT,  # Friday
        }
        provider = MockCNBProvider(
            responses=responses, max_fallback_days_override=3
        )
        rate = provider.get_rate(date(2025, 3, 23), "USD")  # Sunday
        assert rate is not None

    def test_fallback_exhausted(self):
        """If no data within fallback window, return None."""
        provider = MockCNBProvider(
            responses={}, max_fallback_days_override=2
        )
        rate = provider.get_rate(date(2025, 3, 25), "USD")
        assert rate is None

    def test_max_fallback_days_respected(self):
        """Data exists 3 days back but max_fallback is 1 → None."""
        responses = {
            date(2025, 3, 22): SAMPLE_CNB_TEXT,
        }
        provider = MockCNBProvider(
            responses=responses, max_fallback_days_override=1
        )
        rate = provider.get_rate(date(2025, 3, 25), "USD")
        assert rate is None


# ---------------------------------------------------------------------------
# Cache persistence tests
# ---------------------------------------------------------------------------

class TestCnbCachePersistence:
    def test_cache_written_on_fetch(self):
        tmp_dir = tempfile.mkdtemp()
        cache_path = os.path.join(tmp_dir, "test_cnb_cache.json")

        responses = {date(2025, 3, 25): SAMPLE_CNB_TEXT}
        provider = MockCNBProvider(
            responses=responses, cache_file_path=cache_path
        )
        provider.get_rate(date(2025, 3, 25), "USD")

        assert os.path.exists(cache_path)
        with open(cache_path, "r") as fh:
            data = json.load(fh)
        assert "2025-03-25" in data
        assert "USD" in data["2025-03-25"]

    def test_cache_loaded_on_init(self):
        tmp_dir = tempfile.mkdtemp()
        cache_path = os.path.join(tmp_dir, "preloaded.json")

        # Write a pre-populated cache
        cache_data = {
            "2025-03-25": {"USD": "0.04477", "EUR": "0.04112"}
        }
        with open(cache_path, "w") as fh:
            json.dump(cache_data, fh)

        provider = MockCNBProvider(
            responses={}, cache_file_path=cache_path
        )
        rate = provider.get_rate(date(2025, 3, 25), "USD")
        assert rate == Decimal("0.04477")

    def test_corrupt_cache_handled(self):
        tmp_dir = tempfile.mkdtemp()
        cache_path = os.path.join(tmp_dir, "corrupt.json")
        with open(cache_path, "w") as fh:
            fh.write("{{{invalid json")

        # Should not raise — logs error and starts with empty cache
        provider = MockCNBProvider(
            responses={date(2025, 3, 25): SAMPLE_CNB_TEXT},
            cache_file_path=cache_path,
        )
        rate = provider.get_rate(date(2025, 3, 25), "USD")
        assert rate is not None


# ---------------------------------------------------------------------------
# Currency code mapping
# ---------------------------------------------------------------------------

class TestCnbCurrencyCodeMapping:
    def test_cnh_mapped_to_cny(self):
        """CNH (offshore yuan) should be mapped to CNY."""
        provider = MockCNBProvider(responses={})
        assert provider._get_effective_currency_code("CNH") == "CNY"

    def test_custom_mapping(self):
        provider = MockCNBProvider(
            responses={},
            currency_code_mapping_override={"XXX": "YYY"},
        )
        assert provider._get_effective_currency_code("XXX") == "YYY"
        assert provider._get_effective_currency_code("USD") == "USD"


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------

class TestCnbProtocolConformance:
    def test_is_exchange_rate_provider(self):
        provider = MockCNBProvider(responses={})
        assert isinstance(provider, ExchangeRateProvider)

    def test_is_fx_provider_protocol(self):
        provider = MockCNBProvider(responses={})
        assert isinstance(provider, FxProvider)

    def test_get_max_fallback_days(self):
        provider = MockCNBProvider(
            responses={}, max_fallback_days_override=5
        )
        assert provider.get_max_fallback_days() == 5

    def test_get_currency_code_mapping(self):
        provider = MockCNBProvider(responses={})
        mapping = provider.get_currency_code_mapping()
        assert isinstance(mapping, dict)
        assert "CNH" in mapping


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

class TestFxProviderFactory:
    def test_available_providers(self):
        providers = available_fx_providers()
        assert "ecb" in providers
        assert "cnb" in providers

    def test_create_cnb(self):
        tmp = os.path.join(tempfile.mkdtemp(), "factory_test.json")
        provider = create_fx_provider("cnb", cache_file_path=tmp)
        assert isinstance(provider, CNBExchangeRateProvider)

    def test_create_ecb(self):
        tmp = os.path.join(tempfile.mkdtemp(), "factory_ecb.json")
        provider = create_fx_provider("ecb", cache_file_path=tmp)
        from src.utils.exchange_rate_provider import ECBExchangeRateProvider
        assert isinstance(provider, ECBExchangeRateProvider)

    def test_case_insensitive(self):
        tmp = os.path.join(tempfile.mkdtemp(), "factory_ci.json")
        provider = create_fx_provider("CNB", cache_file_path=tmp)
        assert isinstance(provider, CNBExchangeRateProvider)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown FX provider"):
            create_fx_provider("nonexistent")


# ---------------------------------------------------------------------------
# Conversion math sanity
# ---------------------------------------------------------------------------

class TestCnbConversionMath:
    """Verify that the CurrencyConverter logic works with CNB rates."""

    def test_usd_to_czk_conversion(self):
        """
        100 USD → CZK via CNB rate.
        CNB says 1 USD = 22.345 CZK.
        Our rate = 1/22.345 (foreign per CZK).
        CZK amount = foreign_amount / rate = 100 / (1/22.345) = 2234.5 CZK.
        """
        responses = {date(2025, 3, 25): SAMPLE_CNB_TEXT}
        provider = MockCNBProvider(responses=responses)

        rate = provider.get_rate(date(2025, 3, 25), "USD")
        assert rate is not None

        usd_amount = Decimal("100")
        czk_amount = usd_amount / rate  # same logic as CurrencyConverter
        expected_czk = Decimal("2234.5")
        assert abs(czk_amount - expected_czk) < Decimal("0.1")

    def test_eur_to_czk_conversion(self):
        """
        50 EUR → CZK.
        CNB says 1 EUR = 24.320 CZK.
        CZK = 50 / (1/24.320) = 50 * 24.320 = 1216.0 CZK.
        """
        responses = {date(2025, 3, 25): SAMPLE_CNB_TEXT}
        provider = MockCNBProvider(responses=responses)

        rate = provider.get_rate(date(2025, 3, 25), "EUR")
        assert rate is not None

        eur_amount = Decimal("50")
        czk_amount = eur_amount / rate
        expected_czk = Decimal("1216.0")
        assert abs(czk_amount - expected_czk) < Decimal("0.1")
