# src/countries/de/results.py
"""
German-specific result dataclasses.

These are re-exported from ``src.domain.results`` for backward compatibility.
New code should import from here.
"""
# Re-export from canonical location (domain/results.py still holds them
# during the transition period — a future step can move them here physically).
from src.domain.results import LossOffsettingResult, VorabpauschaleData

__all__ = ["LossOffsettingResult", "VorabpauschaleData"]
