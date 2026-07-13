"""Tests for the heuristic analyzer, webhook helpers, and API."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.analyzer.heuristic import HeuristicAnalyzer
from app.github.webhook import extract_run_context, is_failed_run, verify_signature
from app.main import app
from app.models import Severity

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def analyze(text: str):
    return asyncio.run(HeuristicAnalyzer().analyze(text))


# ── Heuristic detection ────────────────────────────────────────────────
def test_detects_npm_eresolve():
    result = analyze("npm ERR! code ERESOLVE\nnpm ERR! could not resolve dependency")
    assert result.issues
    assert result.primary_issue.category == "dependency"
    assert "npm" in result.primary_issue.title.lower()


def test_detects_oom_as_critical():
    result = analyze("FATAL ERROR: JavaScript heap out of memory\nexit code 137")
    top = result.primary_issue
    assert top.severity == Severity.critical
    assert top.category == "resources"


def test_detects_test_failure():
    result = analyze("FAILED tests/test_invoice.py::test_total - AssertionError: assert 100 == 110")
    assert any(i.category == "tests" for i in result.issues)


def test_clean_logs_yield_no_issues():
    result = analyze("All checks passed\nBuild succeeded in 12s")
    assert result.issues == []
    assert "No failures" in result.summary or "No known" in result.summary


def test_confidence_within_bounds():
    result = analyze("npm ERR! code ERESOLVE\nnpm ERR! ERESOLVE could not resolve")
    for issue in result.issues:
        assert 0.0 <= issue.confidence <= 1.0


@pytest.mark.parametrize("sample", ["npm_dependency_conflict", "python_test_failure",
                                    "docker_build_oom", "missing_env_secret"])
def test_all_samples_detect_something(sample):
    text = (SAMPLES / f"{sample}.log").read_text(encoding="utf-8")
    result = analyze(text)
    assert result.issues, f"expected a diagnosis for {sample}"


def test_issue_has_actionable_fix_details():
    result = analyze("npm ERR! code ERESOLVE\nnpm ERR! could not resolve dependency")
    top = result.primary_issue
    assert top.explanation, "expected a deeper explanation"
    assert top.fix_steps, "expected ordered fix steps"
    assert top.commands, "expected copy-paste commands"
    assert top.commands[0].code.strip(), "command code must not be empty"


def test_markdown_includes_commands_and_explanation():
    result = analyze("No space left on device")
    md = result.to_markdown()
    assert "Pipeline Doctor" in md
    assert "What's happening" in md
    assert "```" in md  # a command block is rendered


def test_severity_counts_computed():
    result = analyze("FATAL ERROR: JavaScript heap out of memory")
    assert result.severity_counts.get("critical", 0) >= 1


def test_platform_detection_github():
    result = analyze("##[group]Run npm ci\n/home/runner/work/app\nnpm ERR! code ERESOLVE")
    assert result.detected_platform == "GitHub Actions"


def test_platform_detection_none_for_plain_logs():
    result = analyze("some generic build output\nAssertionError: boom")
    assert result.detected_platform is None


# ── Webhook helpers ────────────────────────────────────────────────────
def test_signature_skipped_without_secret():
    assert verify_signature(b"{}", None, None) is True


def test_signature_rejects_bad_value():
    assert verify_signature(b"{}", "sha256=deadbeef", "topsecret") is False


def test_is_failed_run_true_on_failure():
    body = {"action": "completed", "workflow_run": {"conclusion": "failure"}}
    assert is_failed_run("workflow_run", body) is True


def test_is_failed_run_false_on_success():
    body = {"action": "completed", "workflow_run": {"conclusion": "success"}}
    assert is_failed_run("workflow_run", body) is False


def test_extract_run_context_reads_pr():
    body = {
        "repository": {"full_name": "acme/app"},
        "workflow_run": {"id": 99, "head_sha": "abc123", "name": "CI",
                         "pull_requests": [{"number": 7}], "html_url": "http://x"},
    }
    ctx = extract_run_context(body)
    assert ctx["repo_full_name"] == "acme/app"
    assert ctx["pr_number"] == 7


# ── API ────────────────────────────────────────────────────────────────
client = TestClient(app)


def test_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_analyze_endpoint():
    resp = client.post("/api/analyze", json={"logs": "npm ERR! code ERESOLVE"})
    assert resp.status_code == 200
    assert resp.json()["issues"]


def test_analyze_rejects_empty_logs():
    resp = client.post("/api/analyze", json={"logs": ""})
    assert resp.status_code == 422


def test_samples_listing():
    resp = client.get("/api/samples")
    assert resp.status_code == 200
    assert "npm_dependency_conflict" in resp.json()["samples"]


def test_rules_catalog_endpoint():
    resp = client.get("/api/rules")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] >= 15
    assert "dependency" in body["categories"]


def test_analyze_response_includes_rich_fields():
    resp = client.post("/api/analyze", json={"logs": "npm ERR! code ERESOLVE"})
    data = resp.json()
    assert "severity_counts" in data
    issue = data["issues"][0]
    assert "commands" in issue and issue["commands"]
    assert "fix_steps" in issue and issue["fix_steps"]


def test_webhook_ping():
    resp = client.post("/webhook/github", json={"zen": "hi"}, headers={"X-GitHub-Event": "ping"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "pong"
