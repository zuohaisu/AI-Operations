#!/usr/bin/env python3
"""Execute step (MOCK). Reads the plan and writes a canned result.
In a real deployment this step would run `claude -p --append-system-prompt ...`
(or codex) to actually implement the plan against the codebase."""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ART = os.path.join(HERE, "artifacts")
os.makedirs(ART, exist_ok=True)


def main():
    plan = open(os.path.join(ART, "plan.md")).read()
    result = (
        "MOCK EXECUTE RESULT\n"
        "Implemented per plan. Tests pass. No diff produced in mock mode.\n"
    )
    with open(os.path.join(ART, "result.md"), "w") as f:
        f.write(result)
    print(result)


if __name__ == "__main__":
    main()
