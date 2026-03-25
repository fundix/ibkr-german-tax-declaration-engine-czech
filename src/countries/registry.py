# src/countries/registry.py
"""
Country tax plugin registry.

Provides ``get_tax_plugin()`` to look up a country module by its
ISO 3166-1 alpha-2 code (lowercase).
"""
from __future__ import annotations

from typing import Dict, Type

from src.countries.base import TaxPlugin

# Lazy mapping — avoids importing heavy modules at import time.
_PLUGIN_REGISTRY: Dict[str, str] = {
    "de": "src.countries.de.plugin.GermanTaxPlugin",
    "cz": "src.countries.cz.plugin.CzechTaxPlugin",
}


def get_tax_plugin(country_code: str, **kwargs) -> TaxPlugin:
    """
    Return an instantiated ``TaxPlugin`` for *country_code*.

    Extra *kwargs* are forwarded to the plugin constructor
    (e.g. ``vorabpauschale_items`` for the German plugin).

    Raises ``ValueError`` if the country code is not registered.
    """
    code = country_code.lower()
    if code not in _PLUGIN_REGISTRY:
        available = ", ".join(sorted(_PLUGIN_REGISTRY.keys()))
        raise ValueError(
            f"Unknown country code '{code}'. Available: {available}"
        )

    dotted_path = _PLUGIN_REGISTRY[code]
    module_path, class_name = dotted_path.rsplit(".", 1)

    import importlib
    module = importlib.import_module(module_path)
    plugin_class = getattr(module, class_name)
    return plugin_class(**kwargs)


def available_countries() -> list:
    """Return sorted list of registered country codes."""
    return sorted(_PLUGIN_REGISTRY.keys())
