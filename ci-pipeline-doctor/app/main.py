"""FastAPI application: web UI, REST API, and GitHub webhook receiver."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

from app import __version__, storage
from app.analyzer import get_analyzer
from app.config import settings
from app.github.client import GitHubClient
from app.github.webhook import extract_run_context, is_failed_run, verify_signature
from app.models import AnalysisResult, AnalyzeRequest

BASE_DIR = Path(__file__).resolve().parent
SAMPLES_DIR = BASE_DIR.parent / "samples"
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title=settings.app_name, version=__version__)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {"app_name": settings.app_name, "provider": settings.provider},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "version": __version__, "provider": settings.provider}


@app.get("/api/rules")
async def list_rules():
    """Expose the heuristic knowledge base (what the offline engine can detect)."""
    from app.analyzer.rules import RULES

    by_category: dict[str, list] = {}
    for r in RULES:
        by_category.setdefault(r.category, []).append(
            {"id": r.id, "title": r.title, "severity": r.severity.value}
        )
    return {"count": len(RULES), "categories": by_category}


@app.get("/api/samples")
async def list_samples():
    if not SAMPLES_DIR.exists():
        return {"samples": []}
    return {"samples": sorted(p.stem for p in SAMPLES_DIR.glob("*.log"))}


@app.get("/api/samples/{name}")
async def get_sample(name: str):
    # Guard against path traversal — only allow known sample stems.
    path = SAMPLES_DIR / f"{name}.log"
    if not path.exists() or path.parent != SAMPLES_DIR:
        raise HTTPException(status_code=404, detail="Sample not found")
    return {"name": name, "logs": path.read_text(encoding="utf-8", errors="replace")}


def _record(result: AnalysisResult) -> None:
    """Persist an analysis; never let storage errors break the request."""
    if not settings.enable_history:
        return
    try:
        storage.record_analysis(result)
    except Exception:  # noqa: BLE001 - history is best-effort
        pass


@app.post("/api/analyze", response_model=AnalysisResult)
async def analyze(req: AnalyzeRequest):
    analyzer = get_analyzer()
    result = await analyzer.analyze(req.logs, req.context)
    _record(result)
    return result


@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    return templates.TemplateResponse(
        request, "history.html", {"app_name": settings.app_name}
    )


@app.get("/api/history")
async def history_data(limit: int = 25):
    limit = max(1, min(limit, 200))
    return {"analyses": storage.recent(limit), "metrics": storage.metrics()}


@app.get("/api/dashboard")
async def dashboard_data():
    return storage.dashboard()


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Prometheus-format metrics scraped from the analysis history."""
    m = storage.metrics()
    lines = [
        "# HELP pipeline_doctor_analyses_total Total analyses performed.",
        "# TYPE pipeline_doctor_analyses_total counter",
        f"pipeline_doctor_analyses_total {m['total_analyses']}",
        "# HELP pipeline_doctor_issues_total Total issues detected.",
        "# TYPE pipeline_doctor_issues_total counter",
        f"pipeline_doctor_issues_total {m['total_issues']}",
        "# HELP pipeline_doctor_clean_runs_total Analyses where no issue was found.",
        "# TYPE pipeline_doctor_clean_runs_total counter",
        f"pipeline_doctor_clean_runs_total {m['clean_runs']}",
        "# HELP pipeline_doctor_issues_by_category Issues detected per category.",
        "# TYPE pipeline_doctor_issues_by_category counter",
    ]
    for cat, n in sorted(m["by_category"].items()):
        lines.append(f'pipeline_doctor_issues_by_category{{category="{cat}"}} {n}')
    lines += [
        "# HELP pipeline_doctor_issues_by_severity Issues detected per severity.",
        "# TYPE pipeline_doctor_issues_by_severity counter",
    ]
    for sev, n in sorted(m["by_severity"].items()):
        lines.append(f'pipeline_doctor_issues_by_severity{{severity="{sev}"}} {n}')
    lines += [
        "# HELP pipeline_doctor_analyses_by_platform Analyses per detected CI platform.",
        "# TYPE pipeline_doctor_analyses_by_platform counter",
    ]
    for plat, n in sorted(m["by_platform"].items()):
        lines.append(f'pipeline_doctor_analyses_by_platform{{platform="{plat}"}} {n}')
    return "\n".join(lines) + "\n"


@app.post("/webhook/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str | None = Header(default=None),
):
    raw = await request.body()
    if not verify_signature(raw, x_hub_signature_256, settings.github_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid signature")

    body = json.loads(raw or b"{}")

    if x_github_event == "ping":
        return {"status": "pong"}

    if not is_failed_run(x_github_event, body):
        return {"status": "ignored", "reason": "not a failed workflow_run"}

    ctx = extract_run_context(body)

    if not settings.github_token:
        # Local/dev mode: we can't fetch logs or comment without a token.
        return JSONResponse(
            {"status": "accepted", "note": "No GITHUB_TOKEN set; skipping fetch+comment.", "context": ctx}
        )

    client = GitHubClient(settings.github_token)
    logs = await client.get_run_logs(ctx["repo_full_name"], ctx["run_id"])
    result = await get_analyzer().analyze(logs, ctx)
    _record(result)
    comment = result.to_markdown()

    if ctx.get("pr_number"):
        await client.comment_on_pr(ctx["repo_full_name"], ctx["pr_number"], comment)
        target = f"PR #{ctx['pr_number']}"
    else:
        await client.comment_on_commit(ctx["repo_full_name"], ctx["head_sha"], comment)
        target = f"commit {ctx['head_sha'][:7]}"

    return {"status": "commented", "target": target, "issues": len(result.issues)}
