# src/utils/fx_provider_factory.py
"""
Factory for creating exchange-rate providers by name.

Decouples country plugins from concrete provider imports.

Usage::

    provider = create_fx_provider("cnb", cache_file_path="cache/cnb.json")
    provider = create_fx_provider("ecb")  # uses defaults
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from src.utils.exchange_rate_provider import ExchangeRateProvider

logger = logging.getLogger(__name__)

_PROVIDER_MAP: Dict[str, str] = {
    "ecb": "src.utils.exchange_rate_provider.ECBExchangeRateProvider",
    "cnb": "src.utils.cnb_exchange_rate_provider.CNBExchangeRateProvider",
}


def create_fx_provider(
    provider_name: str,
    **kwargs: Any,
) -> ExchangeRateProvider:
    """
    Instantiate an ``ExchangeRateProvider`` by short name.

    Args:
        provider_name: ``"ecb"`` or ``"cnb"`` (case-insensitive).
        **kwargs: Forwarded to the provider constructor
                  (e.g. ``cache_file_path``, ``max_fallback_days_override``).

    Raises:
        ValueError: If *provider_name* is not registered.
    """
    key = provider_name.lower()
    if key not in _PROVIDER_MAP:
        available = ", ".join(sorted(_PROVIDER_MAP.keys()))
        raise ValueError(
            f"Unknown FX provider '{key}'. Available: {available}"
        )

    dotted = _PROVIDER_MAP[key]
    module_path, class_name = dotted.rsplit(".", 1)

    import importlib
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    logger.info(f"Creating FX provider: {class_name} (name={key})")
    return cls(**kwargs)


def available_fx_providers() -> list:
    """Return sorted list of registered provider short names."""
    return sorted(_PROVIDER_MAP.keys())
