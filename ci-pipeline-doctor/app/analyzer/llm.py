"""LLM-backed analyzers (Gemini, Groq) via plain REST — no vendor SDKs.

These are optional: they are only selected when ``DOCTOR_PROVIDER`` is set to
``gemini``/``groq`` *and* the matching API key is present. On any error they
fall back to the heuristic analyzer so a build diagnosis is always produced.

Wiring a real key is a later step — see the README's "Enable AI" section.
"""

from __future__ import annotations

import json

import httpx

from app.analyzer.base import Analyzer
from app.analyzer.heuristic import HeuristicAnalyzer
from app.analyzer.log_parser import detect_platform, split_lines
from app.models import AnalysisResult, DetectedIssue, FixCommand, Severity

_SYSTEM_PROMPT = """You are a senior DevOps engineer diagnosing a failed CI/CD build.
Given raw build logs, identify the most likely root cause(s) and concrete, copy-paste fixes.
Respond with ONLY a JSON object of the form:
{"summary": str,
 "issues": [{"category": str, "title": str,
             "severity": "critical|high|medium|low|info",
             "confidence": float 0..1,
             "root_cause": str,
             "explanation": str,        // deeper: what is happening and why
             "suggested_fix": str,      // one-line summary
             "fix_steps": [str, ...],   // ordered concrete steps
             "commands": [{"label": str, "language": "bash|yaml|json|...", "code": str}],
             "evidence": [str, ...]}]}
Commands must be exact and copy-paste ready. Keep evidence to the few most relevant log
lines. No prose outside the JSON."""

# Only the tail of very long logs is sent, to stay within token limits.
_MAX_LOG_CHARS = 12000


def _trim(logs: str) -> str:
    return logs if len(logs) <= _MAX_LOG_CHARS else logs[-_MAX_LOG_CHARS:]


def _parse_commands(raw: list) -> list[FixCommand]:
    cmds = []
    for c in raw or []:
        try:
            cmds.append(
                FixCommand(
                    label=c.get("label", "Run this"),
                    language=c.get("language", "bash"),
                    code=c["code"],
                )
            )
        except (KeyError, TypeError):
            continue
    return cmds


def _result_from_json(data: dict, provider: str, line_count: int, platform: str | None) -> AnalysisResult:
    issues = []
    for raw in data.get("issues", []):
        try:
            issues.append(
                DetectedIssue(
                    category=raw.get("category", "general"),
                    title=raw["title"],
                    severity=Severity(raw.get("severity", "medium")),
                    confidence=float(raw.get("confidence", 0.6)),
                    root_cause=raw.get("root_cause", ""),
                    explanation=raw.get("explanation", ""),
                    suggested_fix=raw.get("suggested_fix", ""),
                    fix_steps=list(raw.get("fix_steps", []))[:8],
                    commands=_parse_commands(raw.get("commands", [])),
                    evidence=list(raw.get("evidence", []))[:6],
                )
            )
        except (KeyError, ValueError):
            continue
    return AnalysisResult(
        summary=data.get("summary", "AI diagnosis."),
        issues=issues,
        provider=provider,
        detected_platform=platform,
        log_line_count=line_count,
    )


class _LLMAnalyzer(Analyzer):
    """Shared logic; subclasses implement the provider-specific HTTP call."""

    async def _complete(self, prompt: str) -> str:  # pragma: no cover - network
        raise NotImplementedError

    async def analyze(self, logs: str, context: dict | None = None) -> AnalysisResult:
        line_count = len(split_lines(logs))
        platform = detect_platform(logs)
        prompt = f"{_SYSTEM_PROMPT}\n\nLOGS:\n{_trim(logs)}"
        try:
            raw = await self._complete(prompt)
            text = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
            return _result_from_json(json.loads(text), self.name, line_count, platform)
        except Exception:  # noqa: BLE001 - always degrade gracefully
            fallback = await HeuristicAnalyzer().analyze(logs, context)
            fallback.summary = f"[{self.name} unavailable — used offline analyzer] {fallback.summary}"
            fallback.provider = f"{self.name}->heuristic"
            return fallback


class GeminiAnalyzer(_LLMAnalyzer):
    name = "gemini"

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    async def _complete(self, prompt: str) -> str:  # pragma: no cover - network
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]


class GroqAnalyzer(_LLMAnalyzer):
    name = "groq"

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    async def _complete(self, prompt: str) -> str:  # pragma: no cover - network
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        }
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]
