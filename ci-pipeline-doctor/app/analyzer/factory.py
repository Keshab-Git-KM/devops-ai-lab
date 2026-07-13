"""Select the active analyzer backend based on settings.

Falls back to the heuristic analyzer whenever a chosen LLM provider is
misconfigured (missing key), so the service never fails to start.
"""

from __future__ import annotations

from app.analyzer.base import Analyzer
from app.analyzer.heuristic import HeuristicAnalyzer
from app.config import settings


def _build_llm() -> Analyzer | None:
    """Instantiate an LLM analyzer if a key is configured (Groq preferred)."""
    if settings.groq_api_key:
        from app.analyzer.llm import GroqAnalyzer

        return GroqAnalyzer(settings.groq_api_key, settings.groq_model)
    if settings.gemini_api_key:
        from app.analyzer.llm import GeminiAnalyzer

        return GeminiAnalyzer(settings.gemini_api_key, settings.gemini_model)
    return None


def get_analyzer() -> Analyzer:
    provider = (settings.provider or "heuristic").lower()

    if provider == "gemini" and settings.gemini_api_key:
        from app.analyzer.llm import GeminiAnalyzer

        return GeminiAnalyzer(settings.gemini_api_key, settings.gemini_model)

    if provider == "groq" and settings.groq_api_key:
        from app.analyzer.llm import GroqAnalyzer

        return GroqAnalyzer(settings.groq_api_key, settings.groq_model)

    if provider == "hybrid":
        from app.analyzer.hybrid import HybridAnalyzer

        return HybridAnalyzer(_build_llm())

    return HeuristicAnalyzer()
