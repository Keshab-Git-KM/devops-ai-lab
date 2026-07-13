"""Verify and interpret GitHub webhook deliveries."""

from __future__ import annotations

import hashlib
import hmac


def verify_signature(payload: bytes, signature_header: str | None, secret: str | None) -> bool:
    """Validate the ``X-Hub-Signature-256`` header against the raw body.

    Returns True when no secret is configured (local/dev mode) so the endpoint
    stays usable without GitHub. When a secret *is* set, the signature must
    match — a constant-time comparison guards against timing attacks.
    """
    if not secret:
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def is_failed_run(event: str, body: dict) -> bool:
    """True when the delivery is a completed workflow run that failed."""
    if event != "workflow_run":
        return False
    run = body.get("workflow_run", {})
    return body.get("action") == "completed" and run.get("conclusion") == "failure"


def extract_run_context(body: dict) -> dict:
    """Pull the fields we need to fetch logs and comment back."""
    run = body.get("workflow_run", {})
    repo = body.get("repository", {})
    prs = run.get("pull_requests", [])
    return {
        "repo_full_name": repo.get("full_name"),
        "run_id": run.get("id"),
        "head_sha": run.get("head_sha"),
        "workflow_name": run.get("name"),
        "pr_number": prs[0].get("number") if prs else None,
        "html_url": run.get("html_url"),
    }
