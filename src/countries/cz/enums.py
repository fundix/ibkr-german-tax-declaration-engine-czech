# src/countries/cz/enums.py
"""
Czech Republic tax reporting categories.

Maps to sections of the Czech personal income tax return
(Přiznání k dani z příjmů fyzických osob):

- §8 ZDP — Příjmy z kapitálového majetku (capital income)
  - Dividendy, úroky
- §10 ZDP — Ostatní příjmy (other income)
  - Prodej cenných papírů, opce, deriváty

Note: These are placeholder categories. The final mapping to specific
form lines (Příloha č. 2, etc.) requires detailed Czech tax law review.
"""
from enum import Enum, auto


class CzTaxSection(Enum):
    """High-level Czech tax form sections for income classification."""

    # §8 ZDP — Příjmy z kapitálového majetku
    CZ_8_DIVIDENDS = auto()      # Dividendy ze zahraničí
    CZ_8_INTEREST = auto()       # Úroky ze zahraničí

    # §10 ZDP — Ostatní příjmy
    CZ_10_SECURITIES = auto()    # Prodej cenných papírů (akcie, dluhopisy, fondy)
    CZ_10_OPTIONS = auto()       # Opce a deriváty

    # Exempt / non-taxable
    CZ_EXEMPT_TIME_TEST = auto() # Osvobozeno – splněn časový test (§4/1/w ZDP)
    CZ_EXEMPT_OTHER = auto()     # Osvobozeno – jiný důvod


class CzHoldingTestRule(Enum):
    """
    Holding period rules for Czech tax exemption (§4 odst. 1 písm. w ZDP).

    PLACEHOLDER: actual thresholds depend on acquisition date
    and legislative changes (2014 → 3 years, pre-2014 → 6 months).
    """
    SECURITIES_3Y = auto()       # Cenné papíry nabyté po 1.1.2014: 3 roky
    SECURITIES_OLD_6M = auto()   # Cenné papíry nabyté před 1.1.2014: 6 měsíců
    NOT_APPLICABLE = auto()      # Časový test se neuplatňuje (deriváty, úroky…)
