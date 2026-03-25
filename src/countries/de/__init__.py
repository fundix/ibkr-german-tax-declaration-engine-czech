# src/countries/de/__init__.py
"""
German tax module (Anlage KAP, KAP-INV, SO).

Wraps existing German-specific logic behind the TaxPlugin Protocol.
"""
from src.countries.de.plugin import GermanTaxPlugin

__all__ = ["GermanTaxPlugin"]
