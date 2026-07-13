"""Thin GitHub REST client: download run logs and post diagnosis comments.

Only used in live webhook mode when ``DOCTOR_GITHUB_TOKEN`` is configured.
"""

from __future__ import annotations

import io
import zipfile

import httpx

_API = "https://api.github.com"


class GitHubClient:
    def __init__(self, token: str) -> None:
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def get_run_logs(self, repo_full_name: str, run_id: int) -> str:
        """Download and unzip the logs for a workflow run into one text blob."""
        url = f"{_API}/repos/{repo_full_name}/actions/runs/{run_id}/logs"
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.get(url, headers=self._headers)
            resp.raise_for_status()
            content = resp.content
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                parts = [zf.read(n).decode("utf-8", "replace") for n in zf.namelist()]
            return "\n".join(parts)
        except zipfile.BadZipFile:
            return content.decode("utf-8", "replace")

    async def comment_on_pr(self, repo_full_name: str, pr_number: int, body: str) -> None:
        url = f"{_API}/repos/{repo_full_name}/issues/{pr_number}/comments"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=self._headers, json={"body": body})
            resp.raise_for_status()

    async def comment_on_commit(self, repo_full_name: str, sha: str, body: str) -> None:
        url = f"{_API}/repos/{repo_full_name}/commits/{sha}/comments"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=self._headers, json={"body": body})
            resp.raise_for_status()
