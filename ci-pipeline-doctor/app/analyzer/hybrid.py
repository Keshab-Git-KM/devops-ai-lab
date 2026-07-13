"""Hybrid analyzer: fast/free heuristic first, LLM only as a fallback.

This keeps cost at zero for the common case (a known failure pattern matches)
and reaches for the LLM only when the offline engine finds nothing — which is
exactly when open-ended reasoning is worth the API call.
"""

from __future__ import annotations

from app.analyzer.base import Analyzer
from app.analyzer.heuristic import HeuristicAnalyzer
from app.models import AnalysisResult


class HybridAnalyzer(Analyzer):
    name = "hybrid"

    def __init__(self, llm: Analyzer | None = None) -> None:
        self.heuristic = HeuristicAnalyzer()
        self.llm = llm

    async def analyze(self, logs: str, context: dict | None = None) -> AnalysisResult:
        result = await self.heuristic.analyze(logs, context)

        if result.issues or self.llm is None:
            # Known pattern matched (free path), or no LLM configured.
            result.provider = "hybrid:heuristic" if self.llm else "heuristic"
            return result

        # Nothing matched — let the LLM reason about it.
        llm_result = await self.llm.analyze(logs, context)
        llm_result.provider = f"hybrid:{self.llm.name}"
        # Preserve platform detection from the (cheap) heuristic pass.
        llm_result.detected_platform = llm_result.detected_platform or result.detected_platform
        return llm_result
