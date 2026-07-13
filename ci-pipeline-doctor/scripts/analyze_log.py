"""CLI: analyze a local log file and print the diagnosis.

Usage:
    python -m scripts.analyze_log samples/npm_dependency_conflict.log
    python -m scripts.analyze_log samples/python_test_failure.log --markdown
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow running as a plain script (python scripts/analyze_log.py ...).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Ensure UTF-8 output so em-dashes/emoji render on legacy Windows consoles.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):  # pragma: no cover - older/odd streams
    pass

from app.analyzer import get_analyzer  # noqa: E402


async def _run(path: Path, as_markdown: bool) -> int:
    logs = path.read_text(encoding="utf-8", errors="replace")
    result = await get_analyzer().analyze(logs, {"source": str(path)})

    if as_markdown:
        print(result.to_markdown())
        return 0

    print(f"\n  Provider : {result.provider}")
    if result.detected_platform:
        print(f"  Platform : {result.detected_platform}")
    print(f"  Summary  : {result.summary}")
    print(f"  Scanned  : {result.log_line_count} lines\n")
    for i, issue in enumerate(result.issues, 1):
        print(f"  [{i}] {issue.title}  ({issue.severity.value}, {int(issue.confidence*100)}%)")
        print(f"      cause : {issue.root_cause}")
        if issue.explanation:
            print(f"      why   : {issue.explanation}")
        print(f"      fix   : {issue.suggested_fix}")
        for n, step in enumerate(issue.fix_steps, 1):
            print(f"        {n}. {step}")
        for cmd in issue.commands:
            print(f"      $ ({cmd.label})")
            for line in cmd.code.splitlines():
                print(f"          {line}")
        print()
    if not result.issues:
        print("  No known failure patterns matched.\n")
    return 0 if result.issues else 2


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose a CI/CD build log.")
    parser.add_argument("logfile", type=Path, help="Path to a log file.")
    parser.add_argument("--markdown", action="store_true", help="Emit a Markdown report.")
    args = parser.parse_args()

    if not args.logfile.exists():
        parser.error(f"file not found: {args.logfile}")
    raise SystemExit(asyncio.run(_run(args.logfile, args.markdown)))


if __name__ == "__main__":
    main()
