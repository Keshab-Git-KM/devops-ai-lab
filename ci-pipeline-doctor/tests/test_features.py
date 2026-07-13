"""Tests for storage/history, metrics, hybrid analyzer, and new rules."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app import storage
from app.analyzer.heuristic import HeuristicAnalyzer
from app.analyzer.hybrid import HybridAnalyzer
from app.main import app

client = TestClient(app)


def analyze(text: str):
    return asyncio.run(HeuristicAnalyzer().analyze(text))


# ── New failure patterns ───────────────────────────────────────────────
def test_detects_terraform():
    r = analyze("Error acquiring the state lock\nError: Invalid resource")
    assert any(i.category == "iac" for i in r.issues)


def test_detects_kubernetes():
    r = analyze("Back-off restarting failed container\nImagePullBackOff")
    assert any(i.category == "deploy" and "Kubernetes" in i.title for i in r.issues)


def test_detects_gradle():
    r = analyze("FAILURE: Build failed with an exception\nBUILD FAILED")
    assert any(i.category == "build" for i in r.issues)


def test_detects_rust():
    r = analyze("error[E0308]: mismatched types\nerror: could not compile `app`")
    assert any("Rust" in i.title for i in r.issues)


def test_detects_go():
    r = analyze("# example.com/app\n./main.go:14:6: undefined: doThing")
    assert any("Go" in i.title for i in r.issues)


def test_detects_docker_registry_auth():
    r = analyze("The push refers to repository [registry/app]\n"
                "denied: requested access to the resource is denied\n"
                "unauthorized: authentication required")
    assert any(i.category == "auth" for i in r.issues)


# ── SQLite storage / history ───────────────────────────────────────────
def test_record_and_recent():
    result = analyze("ImagePullBackOff")
    storage.record_analysis(result)
    rows = storage.recent(10)
    assert rows and rows[0]["issue_count"] >= 1
    assert rows[0]["top_severity"] is not None


def test_metrics_aggregate():
    storage.record_analysis(analyze("npm ERR! code ERESOLVE"))
    storage.record_analysis(analyze("No space left on device"))
    m = storage.metrics()
    assert m["total_analyses"] >= 2
    assert m["total_issues"] >= 2
    assert m["by_severity"]


def test_history_endpoint():
    client.post("/api/analyze", json={"logs": "npm ERR! code ERESOLVE"})
    resp = client.get("/api/history")
    assert resp.status_code == 200
    body = resp.json()
    assert body["metrics"]["total_analyses"] >= 1
    assert isinstance(body["analyses"], list)


def test_history_page_renders():
    resp = client.get("/history")
    assert resp.status_code == 200
    assert "Dashboard" in resp.text


# ── Prometheus metrics endpoint ────────────────────────────────────────
def test_metrics_endpoint_format():
    client.post("/api/analyze", json={"logs": "FATAL ERROR: JavaScript heap out of memory"})
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "pipeline_doctor_analyses_total" in resp.text
    assert "pipeline_doctor_issues_by_severity" in resp.text
    assert "pipeline_doctor_clean_runs_total" in resp.text
    assert "pipeline_doctor_analyses_by_platform" in resp.text
    assert resp.headers["content-type"].startswith("text/plain")


def test_dashboard_aggregates():
    storage.record_analysis(analyze("npm ERR! code ERESOLVE"))
    storage.record_analysis(analyze("No space left on device"))
    storage.record_analysis(analyze("build succeeded, all good"))  # clean run
    d = storage.dashboard()
    assert d["total_analyses"] >= 3
    assert d["clean_runs"] >= 1
    assert isinstance(d["top_issues"], list)
    assert isinstance(d["timeline"], list) and d["timeline"]
    assert "by_platform" in d and "recent" in d


def test_dashboard_endpoint():
    client.post("/api/analyze", json={"logs": "ImagePullBackOff"})
    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    body = resp.json()
    assert "top_issues" in body and "timeline" in body and "by_platform" in body


def test_dashboard_page_renders():
    resp = client.get("/history")
    assert resp.status_code == 200
    assert "Analytics" in resp.text


# ── Hybrid analyzer ────────────────────────────────────────────────────
class _StubLLM(HeuristicAnalyzer):
    """Stand-in LLM that always 'finds' something, to prove the fallback path."""

    name = "stub-llm"

    async def analyze(self, logs, context=None):
        from app.models import AnalysisResult, DetectedIssue, Severity

        return AnalysisResult(
            summary="LLM reasoned about it",
            issues=[DetectedIssue(category="ai", title="AI finding", severity=Severity.medium,
                                  confidence=0.6, root_cause="x", suggested_fix="y")],
            provider="stub-llm",
        )


def test_hybrid_uses_heuristic_when_pattern_matches():
    hybrid = HybridAnalyzer(llm=_StubLLM())
    result = asyncio.run(hybrid.analyze("npm ERR! code ERESOLVE"))
    assert result.provider == "hybrid:heuristic"
    assert result.primary_issue.category == "dependency"


def test_hybrid_falls_back_to_llm_when_nothing_matches():
    hybrid = HybridAnalyzer(llm=_StubLLM())
    result = asyncio.run(hybrid.analyze("everything is totally fine, build succeeded"))
    assert result.provider == "hybrid:stub-llm"
    assert result.primary_issue.title == "AI finding"


def test_hybrid_without_llm_is_plain_heuristic():
    hybrid = HybridAnalyzer(llm=None)
    result = asyncio.run(hybrid.analyze("build succeeded, all good"))
    assert result.provider == "heuristic"
    assert result.issues == []
