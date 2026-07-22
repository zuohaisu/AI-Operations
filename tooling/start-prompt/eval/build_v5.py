#!/usr/bin/env python3
"""Build the copy-ready, single-file V5 start prompt from modular sources."""

from __future__ import annotations

import argparse
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parent
CORE_DIR = ROOT.parent / "core"
MODULE_DIR = ROOT.parent / "modules"
OUTPUT = ROOT / "prompts" / "v5.md"

MODULE_NAMES = {
    "decision.md": "Decision Module",
    "engineering.md": "Engineering Module",
    "product.md": "Product Module",
    "research.md": "Research Module",
    "system.md": "System / Second-Me Module",
    "writing.md": "Writing Module",
}


def _read_markdown(directory: pathlib.Path) -> list[str]:
    files = sorted(directory.glob("*.md"))
    if not files:
        raise FileNotFoundError(f"No Markdown sources found in {directory}")
    return [path.read_text().strip() for path in files]


def _single_file_routing(text: str) -> str:
    text = text.replace(
        "Load exactly ONE module.",
        "Apply exactly ONE task module from the Task Modules section of this prompt.",
    )
    for filename, section_name in MODULE_NAMES.items():
        text = text.replace(f"`{filename}`", f"the **{section_name}** section")
        text = text.replace(filename, section_name)
    text = text.replace("core/04", "the Epistemics section")
    text = text.replace("core/03", "the Failure Protocol section")
    return text


def compose() -> str:
    core_parts = [_single_file_routing(part) for part in _read_markdown(CORE_DIR)]
    module_parts = [_single_file_routing(part) for part in _read_markdown(MODULE_DIR)]
    header = """# Haisu — Universal AI Agent Operating Prompt V5

This is the self-contained distribution build. Apply every Core section to every
request. Then use Module Routing to apply exactly one Task Module. All modules are
included below so this file can be pasted directly into an AI agent's Start Prompt
or System Prompt field; no external prompt files are required.
"""
    sections = [header.strip(), *core_parts, "# Task Modules", *module_parts]
    return "\n\n---\n\n".join(sections).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if prompts/v5.md is missing or differs from the modular sources.",
    )
    args = parser.parse_args()
    expected = compose()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text() != expected:
            print(f"OUT-OF-DATE: {OUTPUT}", file=sys.stderr)
            return 1
        print(f"OK: {OUTPUT}")
        return 0
    OUTPUT.write_text(expected)
    print(f"built {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
