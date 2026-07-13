"""Utilities for cleaning and slicing raw CI logs."""

from __future__ import annotations

import re

# Strip common CI log prefixes: ANSI colours and leading ISO timestamps that
# GitHub Actions / GitLab prepend to every line.
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_TIMESTAMP = re.compile(r"^\s*\d{4}-\d{2}-\d{2}T[\d:.]+Z?\s+")

_ERROR_HINT = re.compile(r"error|fail|fatal|exception|traceback|denied|not found", re.IGNORECASE)

# Signatures used to guess which CI system produced the logs.
_PLATFORM_SIGNATURES: tuple[tuple[str, re.Pattern], ...] = (
    ("GitHub Actions", re.compile(r"##\[group\]|/home/runner/work|actions/checkout", re.I)),
    ("GitLab CI", re.compile(r"section_start:\d+|Running with gitlab-runner|CI_JOB_ID", re.I)),
    ("CircleCI", re.compile(r"circleci|\.circleci/config", re.I)),
    ("Jenkins", re.compile(r"\[Pipeline\]|Jenkinsfile|Started by user", re.I)),
    ("Travis CI", re.compile(r"travis_fold:|travis_time:", re.I)),
    ("Azure Pipelines", re.compile(r"##vso\[|Azure Pipelines", re.I)),
)


def detect_platform(logs: str) -> str | None:
    """Best-effort guess of the CI platform from characteristic log markers."""
    for name, rx in _PLATFORM_SIGNATURES:
        if rx.search(logs):
            return name
    return None


def clean_line(line: str) -> str:
    line = _ANSI.sub("", line)
    line = _TIMESTAMP.sub("", line)
    return line.rstrip()


def split_lines(logs: str) -> list[str]:
    """Normalize logs into a list of cleaned, non-empty-ish lines."""
    return [clean_line(ln) for ln in logs.splitlines()]


def error_region(lines: list[str], max_lines: int = 12) -> list[str]:
    """Return the most likely error-bearing slice of the log.

    Heuristic: find the last line that looks like an error and return a small
    window ending there — CI failures usually surface near the end.
    """
    hits = [i for i, ln in enumerate(lines) if _ERROR_HINT.search(ln)]
    if not hits:
        return [ln for ln in lines[-max_lines:] if ln.strip()]
    last = hits[-1]
    start = max(0, last - max_lines + 3)
    end = min(len(lines), last + 3)
    return [ln for ln in lines[start:end] if ln.strip()]
