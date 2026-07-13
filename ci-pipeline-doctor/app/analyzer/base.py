"""Analyzer interface. Every backend (heuristic, Gemini, Groq) implements this."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import AnalysisResult


class Analyzer(ABC):
    """Turns raw CI logs into a structured :class:`AnalysisResult`."""

    #: Short identifier reported in responses (e.g. "heuristic", "gemini").
    name: str = "base"

    @abstractmethod
    async def analyze(self, logs: str, context: dict | None = None) -> AnalysisResult:
        """Analyze ``logs`` and return a diagnosis.

        ``context`` may carry optional metadata such as repo name, workflow,
        or job id. Implementations must not raise on malformed logs — they
        should degrade to a best-effort result instead.
        """
        raise NotImplementedError
