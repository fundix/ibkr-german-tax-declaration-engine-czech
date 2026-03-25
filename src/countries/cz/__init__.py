# src/countries/cz/__init__.py
"""
Czech Republic tax module.

Provides a skeleton TaxPlugin for Czech tax declarations
(Přiznání k dani z příjmů fyzických osob – §8, §10 ZDP).
"""
from src.countries.cz.plugin import CzechTaxPlugin

__all__ = ["CzechTaxPlugin"]
