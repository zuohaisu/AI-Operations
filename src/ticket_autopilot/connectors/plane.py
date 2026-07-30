"""Plane adapter for the Ticket Autopilot workflow.

This module deliberately contains only Plane API translation.  Workflow execution,
verification, and retry decisions remain in :mod:`ticket_autopilot.engine`.
"""

from __future__ import annotations

from copy import deepcopy
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_WORKSPACE = "hspace"
DEFAULT_PROJECT_ID = "d40168f5-5d44-4810-a39e-3b6558e9bf6e"
PLANE_API_ROOT = "https://api.plane.so/api/v1"
RATE_LIMIT_PER_MINUTE = 60
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_last_request_at: float | None = None


class PlaneAPIError(RuntimeError):
    """Raised when Plane rejects a request or its API cannot be reached."""


class PlaneNormalizationError(ValueError):
    """A Plane v2 work-item cannot be safely mapped into the intake contract."""


_UNFINISHED_STATE_GROUPS = frozenset({"backlog", "unstarted", "started"})
_TERMINAL_STATE_GROUPS = frozenset({"completed", "cancelled"})
_KNOWN_STATE_GROUPS = _UNFINISHED_STATE_GROUPS | _TERMINAL_STATE_GROUPS


class _MarkdownHTMLParser(HTMLParser):
    """Deterministic HTML-to-Markdown conversion for Plane ticket contracts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.list_depth = 0
        self.in_pre = False

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "p":
            self.parts.append("\n\n")
        elif tag in {"ul", "ol"}:
            self.list_depth += 1
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n" + "  " * max(0, self.list_depth - 1) + "- ")
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "pre":
            self.in_pre = True
            self.parts.append("\n\n```\n")
        elif tag == "code" and not self.in_pre:
            self.parts.append("`")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"ul", "ol"}:
            self.list_depth = max(0, self.list_depth - 1)
            self.parts.append("\n")
        elif tag == "pre":
            self.in_pre = False
            self.parts.append("\n```\n")
        elif tag == "code" and not self.in_pre:
            self.parts.append("`")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def markdown(self) -> str:
        lines = [line.rstrip() for line in "".join(self.parts).replace("\r\n", "\n").splitlines()]
        result = "\n".join(lines).strip()
        return result + ("\n" if result else "")


def html_to_markdown(value: str) -> str:
    """Convert Plane HTML while retaining headings, lists, and fenced code."""
    if not isinstance(value, str) or not value.strip():
        raise PlaneNormalizationError("description_html is required")
    parser = _MarkdownHTMLParser()
    parser.feed(value)
    parser.close()
    result = parser.markdown()
    if not result.strip():
        raise PlaneNormalizationError("description_html converted to an empty description")
    return result


def normalize_work_item(work_item: dict[str, Any]) -> dict[str, Any]:
    """Map an expanded Plane v2 item without trusting legacy null fields."""
    if not isinstance(work_item, dict):
        raise PlaneNormalizationError("Plane work-item payload is not an object")
    if work_item.get("_plane_normalization") == "v2":
        return work_item
    project, state, sequence_id = work_item.get("project"), work_item.get("state"), work_item.get("sequence_id")
    if not isinstance(project, dict) or not isinstance(project.get("identifier"), str) or not project["identifier"].strip():
        raise PlaneNormalizationError("expanded project.identifier is required")
    if isinstance(sequence_id, bool) or not isinstance(sequence_id, int) or sequence_id < 1:
        raise PlaneNormalizationError("positive sequence_id is required")
    if not isinstance(state, dict) or not state.get("id") or not isinstance(state.get("group"), str):
        raise PlaneNormalizationError("expanded state.id and state.group are required")
    state_group = state["group"].casefold()
    if state_group not in _KNOWN_STATE_GROUPS:
        raise PlaneNormalizationError(f"unknown Plane state group: {state['group']}")
    if not work_item.get("id"):
        raise PlaneNormalizationError("Plane work-item has no id")
    if not str(work_item.get("name") or work_item.get("title") or "").strip():
        raise PlaneNormalizationError("Plane work-item has no title")
    computed_key = f"{project['identifier'].strip()}-{sequence_id}"
    legacy_key = work_item.get("identifier")
    if legacy_key is not None and str(legacy_key).strip() and str(legacy_key).casefold() != computed_key.casefold():
        raise PlaneNormalizationError("legacy identifier conflicts with project.identifier + sequence_id")
    normalized = dict(work_item)
    normalized.update({
        "identifier": computed_key,
        "description": html_to_markdown(work_item.get("description_html")),
        "state": {**state, "group": state_group},
        "raw_source": dict(work_item),
        "_plane_normalization": "v2",
        "_description_provenance": "description_html",
    })
    return normalized


def is_unfinished_work_item(work_item: dict[str, Any]) -> bool:
    """Return true only for the Plane state groups allowed into intake."""
    state = work_item.get("state")
    return isinstance(state, dict) and str(state.get("group", "")).casefold() in _UNFINISHED_STATE_GROUPS


def resolve_api_key(api_key: str | None = None) -> str:
    """Resolve a Plane key from an explicit argument or the environment only."""
    if api_key:
        return api_key
    if key := os.environ.get("PLANE_API_KEY"):
        return key
    raise PlaneAPIError("Plane API key is required: set PLANE_API_KEY.")


def _base_url(workspace: str) -> str:
    if not workspace or "/" in workspace:
        raise ValueError("workspace must be a non-empty Plane workspace slug")
    return f"{PLANE_API_ROOT}/workspaces/{workspace}"


def _rate_limit() -> None:
    """Keep this process at or below Plane's documented 60 requests/minute."""
    global _last_request_at
    interval = 60.0 / RATE_LIMIT_PER_MINUTE
    now = time.monotonic()
    if _last_request_at is not None:
        wait = interval - (now - _last_request_at)
        if wait > 0:
            time.sleep(wait)
    _last_request_at = time.monotonic()


def _error_body(error: urllib.error.HTTPError) -> str:
    try:
        return error.read().decode("utf-8", errors="replace")
    except Exception:
        return str(error)


def _request(
    method: str,
    path: str,
    *,
    workspace: str,
    api_key: str,
    body: dict[str, Any] | None = None,
    timeout: int = 30,
    retries: int = 3,
) -> tuple[int, Any]:
    """Make a JSON Plane request, retrying transient transport and 429 failures."""
    url = _base_url(workspace) + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json",
        "User-Agent": BROWSER_UA,
    }
    last_error: Exception | None = None

    for attempt in range(retries):
        _rate_limit()
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                return response.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as exc:
            raw = _error_body(exc)
            # Plane returns 429 when its 60/min quota is exhausted.  Respect an
            # advertised retry delay and otherwise use bounded backoff.
            if exc.code == 429 and attempt < retries - 1:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    delay = float(retry_after) if retry_after else float(attempt + 1)
                except ValueError:
                    delay = float(attempt + 1)
                time.sleep(delay)
                continue
            return exc.code, raw
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(float(attempt + 1))
                continue

    raise PlaneAPIError(f"Plane {method} {path} failed after {retries} attempts: {last_error}")


def fetch_issue_by_identifier(
    identifier: str,
    *,
    workspace: str = DEFAULT_WORKSPACE,
    project_id: str = DEFAULT_PROJECT_ID,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Read exactly one Plane issue by its human ticket identifier.

    The product CLI accepts keys such as ``AIO-14`` rather than opaque UUIDs.
    Ambiguous or absent search results are errors, never a guessed selection.
    """
    if not identifier:
        raise ValueError("identifier is required")
    key = resolve_api_key(api_key)
    matches = [item for item in list_work_items(
        workspace=workspace, project_id=project_id, api_key=key
    ) if item["identifier"].casefold() == identifier.casefold()]
    if len(matches) != 1:
        raise PlaneAPIError(f"expected exactly one Plane work-item for {identifier}, found {len(matches)}")
    return fetch_issue(str(matches[0]["id"]), workspace=workspace, project_id=project_id, api_key=key)


def fetch_issue(
    issue_id: str,
    *,
    workspace: str = DEFAULT_WORKSPACE,
    project_id: str = DEFAULT_PROJECT_ID,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Fetch one expanded Plane v2 work-item through the primary read path."""
    if not issue_id:
        raise ValueError("issue_id is required")
    key = resolve_api_key(api_key)
    status, payload = _request(
        "GET",
        f"/projects/{project_id}/work-items/{issue_id}/?expand=state,project",
        workspace=workspace,
        api_key=key,
    )
    if status != 200 or not isinstance(payload, dict):
        raise PlaneAPIError(f"fetch_issue {issue_id} failed: HTTP {status} {payload}")
    try:
        return normalize_work_item(payload)
    except PlaneNormalizationError as exc:
        raise PlaneAPIError(f"fetch_issue {issue_id} returned an unsafe v2 payload: {exc}") from exc


def list_work_items(
    *,
    workspace: str = DEFAULT_WORKSPACE,
    project_id: str = DEFAULT_PROJECT_ID,
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """List expanded v2 work-items; callers own the state-group policy."""
    key = resolve_api_key(api_key)
    status, payload = _request(
        "GET", f"/projects/{project_id}/work-items/?expand=state,project",
        workspace=workspace, api_key=key,
    )
    items = payload.get("results", []) if isinstance(payload, dict) else payload
    if status != 200 or not isinstance(items, list):
        raise PlaneAPIError(f"list work-items failed: HTTP {status} {payload}")
    normalized: list[dict[str, Any]] = []
    for item in items:
        try:
            normalized.append(normalize_work_item(item))
        except PlaneNormalizationError:
            # Unsafe list items cannot be shown as dispatchable.
            continue
    return normalized


def _ticket_context(issue: dict[str, Any]) -> dict[str, Any]:
    """Normalize the useful Plane fields while retaining the source description."""
    return {
        "id": issue.get("id") or issue.get("sequence_id"),
        "sequence_id": issue.get("sequence_id"),
        "title": issue.get("name") or issue.get("title") or "Untitled Plane ticket",
        "description": issue.get("description") or issue.get("description_html") or "",
        "state": issue.get("state"),
    }


def _pipeline_template() -> dict[str, Any]:
    """Load the current canonical four-stage Engine workflow."""
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - installed by the Engine CLI
        raise RuntimeError("build_workflow_yaml requires PyYAML") from exc

    path = Path(__file__).resolve().parents[1] / "workflows" / "ticket-pipeline.yaml"
    with path.open(encoding="utf-8") as workflow_file:
        return yaml.safe_load(workflow_file)


def build_workflow_yaml(issue: dict[str, Any]) -> dict[str, Any]:
    """Turn a Plane issue into a valid, ticket-specific Engine workflow dict."""
    ticket = _ticket_context(issue)
    ticket_id = ticket["id"]
    if ticket_id is None:
        raise ValueError("Plane issue must contain id or sequence_id")

    workflow = deepcopy(_pipeline_template())
    workflow["version"] = "1.0"
    workflow["name"] = f"ticket-{ticket_id}"
    workflow.setdefault("vars", {})["max_retries"] = 5
    workflow["vars"]["ticket"] = ticket
    workflow.setdefault("params", {}).setdefault("ticket_id", {
        "type": "string", "description": "Plane ticket UUID to process"
    })
    workflow["params"]["ticket_id"]["default"] = str(ticket_id)

    planner = workflow["agents"]["planner"]
    planner["system"] = (
        planner.get("system", "").rstrip()
        + "\n\nPlane ticket context (treat its scope and acceptance criteria as "
        + "the execution contract):\n"
        + json.dumps(ticket, ensure_ascii=False, indent=2)
    )
    plan_node = next(node for node in workflow["nodes"] if node["id"] == "plan")
    plan_node.setdefault("inputs", {})["ticket"] = "${vars.ticket}"
    plan_node["inputs"]["ticket_id"] = "${params.ticket_id}"
    return workflow


def _find_state(
    state_name: str, *, workspace: str, project_id: str, api_key: str
) -> str:
    """Resolve an explicit human-visible Plane state name in this project."""
    if not state_name or not state_name.strip():
        raise ValueError("state_name is required")
    status, payload = _request(
        "GET",
        f"/projects/{project_id}/states/",
        workspace=workspace,
        api_key=api_key,
    )
    if status != 200:
        raise PlaneAPIError(f"list states for project {project_id} failed: HTTP {status} {payload}")
    states = payload.get("results", []) if isinstance(payload, dict) else payload
    if not isinstance(states, list):
        raise PlaneAPIError(f"list states for project {project_id} returned invalid data: {payload}")

    wanted = state_name.strip().casefold()
    for state in states:
        if str(state.get("name", "")).casefold() == wanted and state.get("id"):
            return state["id"]
    # Plane installations sometimes label Done with a localized name but retain
    # the completed group.  Never use a group fallback for In Review/Blocked:
    # those names carry workflow semantics and must be configured explicitly.
    if wanted == "done":
        for state in states:
            if str(state.get("group", "")).casefold() == "completed" and state.get("id"):
                return state["id"]
    raise PlaneAPIError(f"project {project_id} has no state named {state_name!r}")


def _add_comment(
    issue_id: str,
    summary: str,
    *,
    workspace: str,
    project_id: str,
    api_key: str,
) -> dict[str, Any]:
    comment_html = html.escape(summary).replace("\n", "<br>")
    for field in ("comment_html", "comment"):
        status, payload = _request(
            "POST",
            f"/projects/{project_id}/issues/{issue_id}/comments/",
            workspace=workspace,
            api_key=api_key,
            body={field: comment_html},
        )
        if status in (200, 201) and isinstance(payload, dict):
            return payload
        if status != 400 or field == "comment":
            raise PlaneAPIError(f"add_comment {issue_id} failed: HTTP {status} {payload}")
    raise AssertionError("unreachable")  # pragma: no cover


def set_ticket_state(
    issue_id: str,
    state_name: str,
    summary: str,
    *,
    workspace: str = DEFAULT_WORKSPACE,
    project_id: str = DEFAULT_PROJECT_ID,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Post retained evidence then move an issue to an explicit Plane state.

    The caller chooses ``In Review`` or ``Blocked`` for the AIO-13 loop.  This
    adapter never infers Done and never represents an HTTP failure as success.
    """
    if not issue_id:
        raise ValueError("issue_id is required")
    if not summary:
        raise ValueError("summary is required")
    key = resolve_api_key(api_key)
    comment = _add_comment(
        issue_id, summary, workspace=workspace, project_id=project_id, api_key=key
    )
    state_id = _find_state(state_name, workspace=workspace, project_id=project_id, api_key=key)
    status, issue = _request(
        "PATCH",
        f"/projects/{project_id}/issues/{issue_id}/",
        workspace=workspace,
        api_key=key,
        body={"state": state_id},  # Plane PATCH intentionally uses state, not state_id.
    )
    if status not in (200, 201) or not isinstance(issue, dict):
        raise PlaneAPIError(f"set_ticket_state {issue_id} failed: HTTP {status} {issue}")
    return {"updated": True, "ticket_id": issue_id, "state_name": state_name,
            "state": state_id, "comment": comment, "issue": issue}


def close_ticket(
    issue_id: str,
    summary: str,
    *,
    workspace: str = DEFAULT_WORKSPACE,
    project_id: str = DEFAULT_PROJECT_ID,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Legacy AIO-8 compatibility wrapper; AIO-13 never calls this path."""
    result = set_ticket_state(
        issue_id, "Done", summary, workspace=workspace, project_id=project_id, api_key=api_key,
    )
    return {"closed": True, **result}


# A verb-first alias is convenient for callers that refer to Plane's API action.
update_ticket_state = set_ticket_state
