#!/usr/bin/env python3
"""
Step B — Verify Plane REST API direct connection can bypass the MCP proxy and
close a ticket end-to-end. Uses the proven plane_client (browser UA + `state`
field). Creates a test issue, moves it to Done, re-reads to confirm, deletes it.

Exit 0 = full read+write+close loop verified through Cloudflare.
"""
import sys
from plane_client import (create_issue, set_state, get_issue, delete_issue, STATE)


def main():
    print("== Step B: verify Plane REST API direct (bypass MCP proxy) ==\n")

    print("[1] create test issue (create path) ...")
    iss = create_issue("[PIPELINE-TEST] verify REST close — safe to delete")
    iid = iss["id"]
    print(f"    OK create: issue_id={iid}")

    print("\n[2] set_state -> Done (WRITE path through Cloudflare) ...")
    set_state(iid, "done")
    print("    OK write: PATCH accepted")

    print("\n[3] get_issue to confirm state == Done ...")
    got = get_issue(iid)
    if got.get("state") == STATE["done"]:
        print(f"    OK verify: state == Done ({got.get('state')})")
    else:
        print(f"    FAIL: state={got.get('state')} expected Done")
        delete_issue(iid)
        sys.exit(7)

    print("\n[4] delete test issue to leave project clean ...")
    delete_issue(iid)
    print(f"    OK deleted {iid}")

    print("\n== RESULT: Step B PASSED — REST API direct read+write+close works, Cloudflare bypass confirmed. ==")
    sys.exit(0)


if __name__ == "__main__":
    main()
