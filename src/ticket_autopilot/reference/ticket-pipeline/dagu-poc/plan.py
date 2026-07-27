#!/usr/bin/env python3
"""Plan step (MOCK). Reads the ticket, writes a plan to artifacts/plan.md.
In a real deployment this would call an LLM (our llm_call / OpenAI-compatible
endpoint) to produce a spec from the ticket description."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import plane_client as pc

HERE = os.path.dirname(os.path.abspath(__file__))
ART = os.path.join(HERE, "artifacts")
os.makedirs(ART, exist_ok=True)


def main():
    tid = open(os.path.join(HERE, ".tid")).read().strip()
    issue = pc.get_issue(tid)
    title = issue.get("name", "(untitled)")
    spec = (
        f"# Plan for {tid}\n\n"
        f"**Title:** {title}\n\n"
        f"**Mock plan:** analyse the request, implement the change, "
        f"run the relevant tests, and report the result.\n"
    )
    with open(os.path.join(ART, "plan.md"), "w") as f:
        f.write(spec)
    print(spec)


if __name__ == "__main__":
    main()
