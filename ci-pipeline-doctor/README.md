# 🩺 AI CI/CD Pipeline Doctor

**Automatically diagnose failed CI/CD builds and get the root cause + a concrete fix — in the browser, from the CLI, or posted straight onto your Pull Request.**

When a pipeline fails, someone has to open the logs, scroll to the error, recognize the pattern, and know the fix. Pipeline Doctor does that instantly. It ships with an offline **heuristic engine** that recognizes the most common CI failure modes with **zero configuration and zero cost**, and can optionally delegate to an **LLM (Gemini / Groq)** for open-ended reasoning — behind the same interface.

> Built to run entirely free: offline by default, deployable on free tiers.

---

## ✨ Features

- **Root-cause diagnosis** — detects **24 failure patterns** across 13 categories: dependency conflicts, failing/flaky tests, Docker & Kubernetes/Helm deploy errors, Terraform/IaC, Maven-Gradle-Go-Rust builds, out-of-memory & disk, missing secrets, auth, network, lint, git, and more.
- **Deep, copy-paste fixes** — every finding includes a plain-English *"what's happening"* explanation, **numbered fix steps**, and **copy-paste-ready command snippets** (bash/yaml/json) with one-click copy — plus severity, a confidence score, and the exact log lines used as evidence.
- **Hybrid AI** — the default `hybrid` provider runs the free heuristic engine first (instant, offline) and only calls an **LLM (Groq/Gemini free tier)** when *no* pattern matches — so cost stays at zero for known failures and you get open-ended reasoning for the rest.
- **CI platform auto-detection** — recognizes GitHub Actions, GitLab CI, CircleCI, Jenkins, Travis, and Azure Pipelines from the log format.
- **History & metrics** — every analysis is saved to a local **SQLite** DB. A `/history` dashboard shows trends (top failure categories, severity mix), and a Prometheus-format `/metrics` endpoint is ready to scrape.
- **Three ways to use it**
  - 🌐 **Web UI** — paste or **drag-and-drop** a log file, click *Diagnose*, then **copy the full report as Markdown** for your PR/Slack.
  - ⌨️ **CLI** — `python -m scripts.analyze_log build.log`.
  - 🔗 **GitHub webhook** — auto-comments the diagnosis on the failing PR/commit.
- **Browsable knowledge base** — `GET /api/rules` lists everything the offline engine can detect.
- **Enterprise hygiene** — typed models (Pydantic), signature-verified webhooks, **38-test suite**, Dockerfile, and its own CI pipeline.

---

## 🏗 Architecture

```
                 ┌──────────────┐
  Web UI ─────▶  │              │
  CLI    ─────▶  │  Analyzer    │──▶  AnalysisResult
  GitHub ─────▶  │  (interface) │      (issues + fixes, ranked)
  webhook        └──────┬───────┘
                        │  selected by DOCTOR_PROVIDER
          ┌─────────────┼──────────────┐
          ▼             ▼              ▼
   HeuristicAnalyzer  GeminiAnalyzer  GroqAnalyzer
   (rules engine,     (REST, LLM)     (REST, LLM)
    offline, free)         └── fall back to heuristic on error ──┘
```

```
app/
├── main.py              # FastAPI: web UI, REST API, history, metrics, webhook
├── config.py            # env-driven settings (DOCTOR_* vars)
├── models.py            # Pydantic schemas + Markdown rendering
├── storage.py           # SQLite history + metrics aggregation
├── analyzer/
│   ├── base.py          # Analyzer interface
│   ├── factory.py       # picks the backend from settings
│   ├── heuristic.py     # offline rule-based engine
│   ├── hybrid.py        # heuristic-first, LLM-fallback (default)
│   ├── rules.py         # the 24-pattern failure knowledge base
│   ├── log_parser.py    # ANSI/timestamp cleanup, error slicing, platform detect
│   └── llm.py           # Gemini / Groq via plain REST
├── github/
│   ├── webhook.py       # HMAC signature verification + event parsing
│   └── client.py        # download run logs, post PR/commit comments
└── templates/           # index.html (analyze) + history.html (dashboard)
```

---

## 🚀 Quickstart

Requires **Python 3.11+**. No Node, no Docker needed for local use.

```bash
# 1. create a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

# 2. install
pip install -r requirements.txt

# 3. run the web app
uvicorn app.main:app --reload
#    → open http://127.0.0.1:8000
```

**Try the CLI:**

```bash
python -m scripts.analyze_log samples/docker_build_oom.log
python -m scripts.analyze_log samples/npm_dependency_conflict.log --markdown
```

**Run the tests:**

```bash
pytest -q
```

---

## 🔌 REST API

| Method | Path                   | Description                                   |
|--------|------------------------|-----------------------------------------------|
| `GET`  | `/`                    | Web dashboard                                 |
| `GET`  | `/health`              | Liveness + active provider                    |
| `POST` | `/api/analyze`         | Analyze raw logs → JSON diagnosis             |
| `GET`  | `/history`             | History dashboard (trends + recent runs)      |
| `GET`  | `/api/history`         | Recent analyses + aggregate metrics (JSON)    |
| `GET`  | `/metrics`             | Prometheus-format metrics                     |
| `GET`  | `/api/rules`           | Browse the detectable failure patterns        |
| `GET`  | `/api/samples`         | List bundled sample logs                      |
| `GET`  | `/api/samples/{name}`  | Fetch a sample's contents                     |
| `POST` | `/webhook/github`      | GitHub `workflow_run` receiver                |

**Example:**

```bash
curl -X POST http://127.0.0.1:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"logs": "npm ERR! code ERESOLVE\nnpm ERR! could not resolve dependency"}'
```

```json
{
  "summary": "Most likely cause: npm dependency conflict (ERESOLVE).",
  "issues": [{
    "category": "dependency",
    "title": "npm dependency conflict (ERESOLVE)",
    "severity": "high",
    "confidence": 0.87,
    "root_cause": "npm could not build a consistent dependency tree ...",
    "suggested_fix": "Reconcile the conflicting versions ...",
    "evidence": ["npm ERR! code ERESOLVE", "npm ERR! could not resolve dependency"]
  }],
  "provider": "heuristic"
}
```

Interactive API docs are auto-generated at **`/docs`**.

---

## 🤖 Enable AI (free, optional)

The default provider is **`hybrid`**: it runs the offline rules first and only calls an LLM when nothing matches. Without a key it behaves exactly like the offline engine — so it's already useful. To light up the AI fallback, add a **free** key (copy `.env.example` → `.env`):

**Groq — recommended (free, fast, no credit card):** get a key at <https://console.groq.com/keys>
```env
DOCTOR_PROVIDER=hybrid
DOCTOR_GROQ_API_KEY=your_key_here
```

**Google Gemini (free tier):** get a key at <https://aistudio.google.com/apikey>
```env
DOCTOR_PROVIDER=hybrid
DOCTOR_GEMINI_API_KEY=your_key_here
```

Set `DOCTOR_PROVIDER=groq` (or `gemini`) to force the LLM on *every* request instead of only as a fallback. Either way, if an LLM call fails, the app automatically degrades to the heuristic engine — you never get a blank result.

## 📊 History & metrics

Every analysis is recorded to a local **SQLite** database (`data/doctor.db` by default — no server, created automatically).

- **`/history`** — a dashboard of recent runs plus trends: total analyses, issues found, top categories, and severity mix.
- **`/metrics`** — Prometheus text format, ready for a Grafana/Prometheus stack:
  ```
  pipeline_doctor_analyses_total 42
  pipeline_doctor_issues_by_category{category="dependency"} 17
  pipeline_doctor_issues_by_severity{severity="critical"} 5
  ```

**Where to see the raw data:** open `data/doctor.db` with any SQLite viewer (VS Code's *SQLite* extension, [DB Browser for SQLite](https://sqlitebrowser.org/), or `sqlite3 data/doctor.db "SELECT * FROM analyses;"`). Disable persistence with `DOCTOR_ENABLE_HISTORY=false`.

---

## 🔗 GitHub integration

Turn it into a bot that comments on failing builds:

1. Deploy the app (see below) so it has a public URL.
2. In your repo: **Settings → Webhooks → Add webhook**
   - **Payload URL:** `https://your-app/webhook/github`
   - **Content type:** `application/json`
   - **Secret:** a random string → set the same value as `DOCTOR_GITHUB_WEBHOOK_SECRET`
   - **Events:** *Workflow runs*
3. Set `DOCTOR_GITHUB_TOKEN` to a token with `repo` scope (used to read logs and post comments).

On any failed `workflow_run`, the Doctor downloads the logs, diagnoses them, and posts a Markdown comment on the associated PR (or commit). Webhook signatures are verified with HMAC-SHA256.

---

## ☁️ Deploy (free tiers)

**Docker:**
```bash
docker build -t pipeline-doctor .
docker run -p 8000:8000 pipeline-doctor
```

Any container host with a free tier works (Render, Railway, Fly.io, Hugging Face Spaces). The image respects the platform's `$PORT`.

---

## 🧭 Roadmap

- [ ] More failure patterns (Terraform, Gradle/Maven, Go, Rust, pytest-xdist)
- [ ] Confidence tuning from real-world logs
- [ ] Slack notifications
- [ ] History dashboard of past diagnoses
- [ ] GitLab CI + Jenkins receivers

---

## 🛠 Tech stack

FastAPI · Pydantic · Jinja2 · httpx · pytest · Docker · GitHub Actions

## 📄 License

MIT
