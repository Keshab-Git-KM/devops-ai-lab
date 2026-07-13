"""Analyzer package: pluggable backends that turn logs into a diagnosis."""

from app.analyzer.factory import get_analyzer

__all__ = ["get_analyzer"]
