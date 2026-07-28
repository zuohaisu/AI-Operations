"""Minimal GitHub pull-request adapter.

The connector creates reviewable PRs only.  It never pushes branches, merges a
PR, or permits the base branch to be submitted as its own head.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

GITHUB_API_ROOT = "https://api.github.com"
USER_AGENT = "ticket-autopilot-connector/0.1"


class GitHubAPIError(RuntimeError):
    """Raised when GitHub cannot create the requested pull request."""


def resolve_token(token: str | None = None) -> str:
    """Resolve a GitHub token without persisting or printing it."""
    if token:
        return token
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise GitHubAPIError("GitHub token is required: set GITHUB_TOKEN or GH_TOKEN.")
    return token


def _validate_pr_target(repo: str, base: str, head: str) -> None:
    if not repo or repo.count("/") != 1:
        raise ValueError("repo must be in 'owner/repository' form")
    if not base or not head:
        raise ValueError("base and head branches are required")
    # A separate, non-protected branch is the feature branch for this adapter.
    # GitHub permits fork syntax (``owner:branch``), so compare its actual ref
    # rather than allowing an accidental ``owner:main`` bypass.  We deliberately
    # do not impose a naming convention (teams use feature/, fix/, etc.).
    base_ref = base.rsplit(":", 1)[-1].removeprefix("refs/heads/")
    head_ref = head.rsplit(":", 1)[-1].removeprefix("refs/heads/")
    if head_ref.casefold() in {base_ref.casefold(), "main", "master"}:
        raise ValueError(
            "head must be a separate feature branch; refusing base/protected branch "
            f"'{head}'."
        )


def create_pr(
    *,
    repo: str,
    base: str,
    head: str,
    title: str,
    body: str,
    draft: bool = True,
    token: str | None = None,
) -> dict[str, Any]:
    """Create a draft (by default) PR for human review; never merge it."""
    _validate_pr_target(repo, base, head)
    if not title:
        raise ValueError("title is required")

    api_token = resolve_token(token)
    payload = {"title": title, "body": body, "base": base, "head": head, "draft": draft}
    request = urllib.request.Request(
        f"{GITHUB_API_ROOT}/repos/{repo}/pulls",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            result = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        raise GitHubAPIError(f"create_pr {repo} failed: HTTP {exc.code} {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GitHubAPIError(f"create_pr {repo} failed: {exc}") from exc

    if not isinstance(result, dict) or not result.get("number") or not result.get("html_url"):
        raise GitHubAPIError(f"create_pr {repo} returned an invalid response: {result}")
    # Keep GitHub's response intact while supplying the requested ergonomic URL key.
    return {"number": result["number"], "url": result["html_url"],
            "html_url": result["html_url"], "draft": result.get("draft", draft),
            "pull_request": result}
