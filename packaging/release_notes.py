"""Extract one version's section from CHANGELOG.md to use as the GitHub Release body.

Also enforces the rule from docs/PACKAGING.md: release notes for testers/users must state whether a
re-ingest is needed. Failing here (in the preflight job, before anything is built or published)
is the cheapest place to catch notes that were never written.

    python packaging/release_notes.py v0.2.0             # print the section
    python packaging/release_notes.py v0.2.0 -o notes.md # ... and write it out
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = _REPO_ROOT / "CHANGELOG.md"
_REINGEST_HINT = "re-ingest"


def section_for(tag: str, text: str) -> str | None:
    """The body under the ``## v<tag> ...`` heading, up to the next ``## `` heading."""
    version = re.escape(tag.strip().lstrip("vV"))
    pattern = rf"^##\s+v?{version}\b.*?$(.*?)(?=^##\s|\Z)"
    match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="release tag, e.g. v0.2.0")
    parser.add_argument("-o", "--output", type=Path, help="write the section to this file")
    args = parser.parse_args()

    body = section_for(args.tag, CHANGELOG.read_text(encoding="utf-8"))
    if not body:
        print(f"No '## {args.tag}' section in CHANGELOG.md - write the release notes first.",
                file=sys.stderr)
        return 1
    if _REINGEST_HINT not in body.lower():
        print(f"The '{args.tag}' notes must say whether a re-ingest is needed "
              f"or not.", file=sys.stderr)
        return 1

    if args.output:
        args.output.write_text(body + "\n", encoding="utf-8")
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())