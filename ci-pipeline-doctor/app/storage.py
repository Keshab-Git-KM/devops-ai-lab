"""Lightweight SQLite persistence for analysis history and metrics.

Uses Python's built-in ``sqlite3`` — no server, no dependency, just a local
file (default: ``data/doctor.db``). Every analysis is recorded so we can show
a history dashboard and expose Prometheus metrics.

The schema is created on demand (``CREATE TABLE IF NOT EXISTS`` on each
connect), so there is no separate migration step and tests can point
``settings.db_path`` at a temp file freely.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.models import AnalysisResult

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at     TEXT    NOT NULL,
    provider       TEXT,
    platform       TEXT,
    log_line_count INTEGER,
    issue_count    INTEGER,
    top_title      TEXT,
    top_severity   TEXT,
    summary        TEXT
);
CREATE TABLE IF NOT EXISTS issues (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id INTEGER NOT NULL,
    category    TEXT,
    severity    TEXT,
    title       TEXT,
    FOREIGN KEY (analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
);
"""


def _db_path() -> Path:
    p = Path(settings.db_path)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@contextmanager
def _db():
    """Open a connection, ensure schema, commit on success, and always close.

    ``with sqlite3.connect(...)`` only commits — it does not close — which on
    Windows leaves the file locked. This wrapper closes explicitly.
    """
    conn = sqlite3.connect(_db_path(), timeout=5.0)  # wait out brief write locks
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def record_analysis(result: AnalysisResult) -> int:
    """Persist one analysis and its issues. Returns the new analysis id."""
    top = result.primary_issue
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _db() as conn:
        cur = conn.execute(
            """INSERT INTO analyses
               (created_at, provider, platform, log_line_count, issue_count,
                top_title, top_severity, summary)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now,
                result.provider,
                result.detected_platform,
                result.log_line_count,
                len(result.issues),
                top.title if top else None,
                top.severity.value if top else None,
                result.summary,
            ),
        )
        analysis_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO issues (analysis_id, category, severity, title) VALUES (?, ?, ?, ?)",
            [(analysis_id, i.category, i.severity.value, i.title) for i in result.issues],
        )
    return analysis_id


def recent(limit: int = 25) -> list[dict]:
    """Return the most recent analyses (newest first)."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM analyses ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


_SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]


def metrics() -> dict:
    """Aggregate counters for the /metrics endpoint."""
    with _db() as conn:
        total_analyses = conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
        total_issues = conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
        clean_runs = conn.execute(
            "SELECT COUNT(*) FROM analyses WHERE issue_count = 0"
        ).fetchone()[0]
        by_category = _group(conn, "issues", "category")
        by_severity = _group(conn, "issues", "severity")
        by_platform = {
            r["platform"]: r["n"]
            for r in conn.execute(
                "SELECT COALESCE(platform,'unknown') platform, COUNT(*) n "
                "FROM analyses GROUP BY platform"
            ).fetchall()
        }
    return {
        "total_analyses": total_analyses,
        "total_issues": total_issues,
        "clean_runs": clean_runs,
        "by_category": by_category,
        "by_severity": by_severity,
        "by_platform": by_platform,
    }


def _group(conn, table: str, col: str) -> dict[str, int]:
    return {
        r[col]: r["n"]
        for r in conn.execute(
            f"SELECT {col}, COUNT(*) n FROM {table} GROUP BY {col} ORDER BY n DESC"
        ).fetchall()
    }


def dashboard(recent_limit: int = 15, timeline_days: int = 14, top_n: int = 8) -> dict:
    """Rich aggregates for the visual analytics dashboard."""
    m = metrics()
    with _db() as conn:
        top_issues = [
            {"title": r["title"], "count": r["n"], "severity": r["severity"]}
            for r in conn.execute(
                "SELECT title, severity, COUNT(*) n FROM issues "
                "GROUP BY title ORDER BY n DESC, title LIMIT ?",
                (top_n,),
            ).fetchall()
        ]
        timeline = [
            {"date": r["d"], "count": r["n"]}
            for r in conn.execute(
                "SELECT substr(created_at,1,10) d, COUNT(*) n FROM analyses "
                "GROUP BY d ORDER BY d DESC LIMIT ?",
                (timeline_days,),
            ).fetchall()
        ]
        timeline.reverse()  # oldest → newest for left-to-right charting
    # Severity ordered by seriousness for stable chart order.
    severity_ordered = {s: m["by_severity"].get(s, 0) for s in _SEVERITY_ORDER if m["by_severity"].get(s)}
    m["by_severity"] = severity_ordered
    m["top_issues"] = top_issues
    m["timeline"] = timeline
    m["recent"] = recent(recent_limit)
    return m
