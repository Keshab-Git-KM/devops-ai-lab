"""Offline, rule-based analyzer. No API key, no network, deterministic.

Scans logs against :data:`app.analyzer.rules.RULES`, gathers evidence for each
matched pattern, and ranks the resulting issues. This is the default backend so
the app is fully functional and free out of the box.
"""

from __future__ import annotations

from app.analyzer.base import Analyzer
from app.analyzer.log_parser import detect_platform, error_region, split_lines
from app.analyzer.rules import RULES, Rule
from app.models import AnalysisResult, DetectedIssue, FixCommand, severity_rank


class HeuristicAnalyzer(Analyzer):
    name = "heuristic"

    #: Max evidence lines kept per matched rule.
    MAX_EVIDENCE = 6

    async def analyze(self, logs: str, context: dict | None = None) -> AnalysisResult:
        lines = split_lines(logs)
        matches: list[DetectedIssue] = []

        for rule in RULES:
            evidence = self._collect_evidence(rule, lines)
            if evidence:
                matches.append(self._to_issue(rule, evidence))

        matches.sort(key=lambda i: (severity_rank(i.severity), i.confidence), reverse=True)
        summary = self._summarize(matches, lines)

        return AnalysisResult(
            summary=summary,
            issues=matches,
            provider=self.name,
            detected_platform=detect_platform(logs),
            log_line_count=len(lines),
        )

    def _collect_evidence(self, rule: Rule, lines: list[str]) -> list[str]:
        found: list[str] = []
        for line in lines:
            if any(rx.search(line) for rx in rule.compiled):
                if line.strip() and line.strip() not in found:
                    found.append(line.strip())
            if len(found) >= self.MAX_EVIDENCE:
                break
        return found

    def _to_issue(self, rule: Rule, evidence: list[str]) -> DetectedIssue:
        # A rule with several distinct matching lines is a stronger signal.
        boost = min(0.1, 0.02 * (len(evidence) - 1))
        return DetectedIssue(
            category=rule.category,
            title=rule.title,
            severity=rule.severity,
            confidence=min(0.99, rule.confidence + boost),
            root_cause=rule.root_cause,
            explanation=rule.explanation,
            suggested_fix=rule.suggested_fix,
            fix_steps=list(rule.fix_steps),
            commands=[FixCommand(label=lbl, language=lang, code=code) for lbl, lang, code in rule.commands],
            evidence=evidence,
            docs_url=rule.docs_url,
        )

    def _summarize(self, matches: list[DetectedIssue], lines: list[str]) -> str:
        if not matches:
            region = error_region(lines)
            if region:
                return (
                    "No known failure pattern matched. The most error-like lines "
                    f"are shown below for manual review ({len(lines)} log lines scanned)."
                )
            return f"No failures detected in {len(lines)} log lines."
        top = matches[0]
        extra = f" (+{len(matches) - 1} more)" if len(matches) > 1 else ""
        return f"Most likely cause: {top.title}{extra}."
