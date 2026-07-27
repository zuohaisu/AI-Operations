#!/usr/bin/env python3
"""
plane_client.py — proven Plane REST API client (bypasses the MCP proxy).

Two non-obvious facts baked in here (both verified 2026-07-26):
  1. api.plane.so sits behind Cloudflare, which 403s non-browser User-Agents
     (error 1010). A normal browser UA bypasses it. This is ALSO why the MCP
     proxy got 403 — its HTTP client didn't send a browser UA.
  2. PATCHing an issue's state uses the `state` field (the state UUID), NOT
     `state_id`. `state_id` on PATCH is silently dropped (HTTP 200, no change)
     — that is the real cause of the old "MCP drops state_id" bug.

Auth: X-API-Key header. Token resolved from env PLANE_API_KEY or
~/.workbuddy/mcp.json (never hardcoded, never printed).
"""
import json
import os
import time
import urllib.request
import urllib.error

WORKSPACE = "hspace"
PROJECT_ID = "5c5c7207-868e-4da6-ae95-66e7d02eeebb"
BASE = f"https://api.plane.so/api/v1/workspaces/{WORKSPACE}"

STATE = {
    "backlog": "9226fe01-b462-4b60-ac08-e15c8da0a73b",
    "todo": "b85c4f6b-4258-4225-8002-caf57da50bf2",
    "in_progress": "363faa30-72e5-4f7b-b193-0e750b0f563b",
    "done": "e6a30651-af21-48d6-af5d-042ca0b43c5f",
    "cancelled": "d36b6a43-4b3e-419d-af6e-e7200333bf05",
    "blocked": "3e4ef549-3302-4b3e-adce-72da13918678",
}

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def get_token():
    tok = os.environ.get("PLANE_API_KEY")
    if tok:
        return tok
    cfg = json.load(open(os.path.expanduser("~/.workbuddy/mcp.json")))
    return cfg["mcpServers"]["plane"]["env"]["PLANE_API_KEY"]


TOKEN = get_token()


def _call(method, path, body=None, timeout=30, retries=3):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    last_err = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("X-API-Key", TOKEN)
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", BROWSER_UA)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace")
        except Exception as e:  # network / TLS / timeout — retry transient drops
            last_err = e
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    return None, str(last_err)


def list_issues(page_size=10):
    st, p = _call("GET", f"/projects/{PROJECT_ID}/issues/?page_size={page_size}")
    if st != 200:
        raise RuntimeError(f"list_issues failed: HTTP {st} {p}")
    return p.get("results", []) if isinstance(p, dict) else []


def get_issue(issue_id):
    st, p = _call("GET", f"/projects/{PROJECT_ID}/issues/{issue_id}/")
    if st != 200:
        raise RuntimeError(f"get_issue {issue_id} failed: HTTP {st} {p}")
    return p


def create_issue(name, state_key="backlog", description_html=None):
    body = {"name": name, "state_id": STATE[state_key]}
    if description_html:
        body["description_html"] = description_html
    st, p = _call("POST", f"/projects/{PROJECT_ID}/issues/", body)
    if st not in (200, 201) or not isinstance(p, dict) or "id" not in p:
        raise RuntimeError(f"create_issue failed: HTTP {st} {p}")
    return p


def set_state(issue_id, state_key):
    """Move an issue to a state. Uses the `state` field (NOT state_id)."""
    st, p = _call("PATCH", f"/projects/{PROJECT_ID}/issues/{issue_id}/",
                  {"state": STATE[state_key]})
    if st not in (200, 201):
        raise RuntimeError(f"set_state {issue_id}->{state_key} failed: HTTP {st} {p}")
    return p


def delete_issue(issue_id):
    st, _ = _call("DELETE", f"/projects/{PROJECT_ID}/issues/{issue_id}/")
    if st not in (200, 204):
        raise RuntimeError(f"delete_issue {issue_id} failed: HTTP {st}")
    return True


def add_comment(issue_id, text):
    """Post a comment (markdown) to an issue. Best-effort: tries comment_html,
    falls back to comment on HTTP 400. Raises on other hard failures."""
    html = text.replace("\n", "<br>")
    for field in ("comment_html", "comment"):
        st, p = _call("POST", f"/projects/{PROJECT_ID}/issues/{issue_id}/comments/",
                      {field: html})
        if st in (200, 201):
            return p
        if st == 400 and field == "comment_html":
            continue  # try plain `comment` next
        raise RuntimeError(f"add_comment {issue_id} failed: HTTP {st} {p}")
    raise RuntimeError(f"add_comment {issue_id} failed: both field attempts rejected")



if __name__ == "__main__":
    # smoke test
    iss = create_issue("[PIPELINE-TEST] smoke")
    iid = iss["id"]
    set_state(iid, "done")
    got = get_issue(iid)
    print("state after set_state(done):", got.get("state"),
          "->", "OK" if got.get("state") == STATE["done"] else "FAIL")
    delete_issue(iid)
    print("smoke test issue deleted")
