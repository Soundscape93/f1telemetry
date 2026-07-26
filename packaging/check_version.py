"""Fail the release build when the git tag, src/version.py and pyproject.toml disagree.

The repository is the source of truth for the version and CI *verifies* rather than rewrites it:
a build-time stamp would make the published artifact differ from the tagged commit, and an
editable install in a checkout would report a different version than the build.

Run it yourself before tagging:

    python packaging/check_version.py             # the two files agree
    python packaging/check_version.py v0.2.0      # ... and match the tag you are about to push
"""
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def source_version() -> str:
    text = (REPO_ROOT / "src" / "version.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit("could not find __version__ in src/version.py")
    return match.group(1)


def project_version() -> str:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def main(argv: list[str]) -> int:
    source, project = source_version(), project_version()
    tag = argv[1].strip().lstrip("vV") if len(argv) > 1 and argv[1].strip() else None

    problems = []
    if source != project:
        problems.append(f"src/version.py says {source!r}, pyproject.toml says {project!r}")
    if tag is not None and tag != source:
        problems.append(f"the git tag says {tag!r}, src/version.py says {source!r}")

    if problems:
        print("Version mismatch:\n  " + "\n  ".join(problems), file=sys.stderr)
        print("Bump src/version.py and pyproject.toml together, commit, then re-tag.",
              file=sys.stderr)
        return 1
    print(f"version {source} OK" + (" (matches the tag)" if tag else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
