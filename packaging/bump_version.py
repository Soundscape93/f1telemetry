"""Apply a SemVer bump to the version files and close the changelog's Unreleased section.

Label-driven releases (docs/PACKAGING.md, Phase 3): merging a PR labelled ``major`` / ``minor`` /
``patch`` makes CI run this on ``main``, commit the result, and tag that commit. The version
therefore lives in the repository *before* the tag exists - nothing is stamped at build time, so
the published artifact is exactly the tagged commit (``release.yml`` re-verifies with
``check_version.py``).

    python packaging/bump_version.py --check           # PR gate: is the Unreleased section usable?
    python packaging/bump_version.py minor --dry-run   # what would the next version be?
    python packaging/bump_version.py minor             # write version.py, pyproject.toml, CHANGELOG
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VERSION_PY = REPO_ROOT / "src" / "version.py"
PYPROJECT = REPO_ROOT / "pyproject.toml"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

# Sibling script, imported by path so this works both as `python packaging/bump_version.py`
# (where the dir is already sys.path[0]) and when a test loads it directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_version import project_version, source_version   # noqa: E402

LEVELS = ("major", "minor", "patch")
UNRELEASED_HEADING = "## Unreleased"
PLACEHOLDER = (
    "<!-- One bullet per user-visible change, plus the mandatory line\n"
    "     **Re-ingest needed: yes/no** - yes whenever PIPELINE_VERSION moved.\n"
    "     Merging a PR labelled major/minor/patch turns this section into a release. -->"
)
_REINGEST_HINT = "re-ingest"


def next_version(current: str, level: str) -> str:
    major, minor, patch = (int(part) for part in current.split("."))
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    if level == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"unknown bump level: {level!r}")


# --- the changelog's Unreleased section -------------------------------------------------

def _strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def unreleased_body(text: str) -> str:
    """Everything under the Unreleased heading, up to the next ``## `` heading."""
    match = re.search(rf"^{re.escape(UNRELEASED_HEADING)}\s*$(.*?)(?=^##\s|\Z)",
                      text, re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else ""


def check(text: str) -> list[str]:
    """Problems with the Unreleased section; empty when it is release-ready.

    Enforced on the pull request (ci.yml) rather than only at release time, so the author finds
    out while they are still writing the change, not after the merge.
    """
    if UNRELEASED_HEADING not in text:
        return [f"CHANGELOG.md has no '{UNRELEASED_HEADING}' section."]
    body = unreleased_body(text)
    if not _strip_comments(body).strip():
        return ["The Unreleased section is empty - describe this change for users & testers."]
    if _REINGEST_HINT not in body.lower():
        return ["The Unreleased section must state '**Re-ingest needed: yes/no**' "
                 "(yes whenever PIPELINE_VERSION moved)."]
    return []


def release_unreleased(text: str, version: str, today: dt.date) -> str:
    """Rename Unreleased to the new version and open a fresh empty Unreleased above it."""
    body = _strip_comments(unreleased_body(text)).strip()
    replacement = (f"{UNRELEASED_HEADING}\n\n{PLACEHOLDER}\n\n"
                   f"## v{version} — {today.isoformat()}\n\n{body}\n\n")
    return re.sub(rf"^{re.escape(UNRELEASED_HEADING)}\s*$.*?(?=^##\s|\Z)",
                  lambda _match: replacement, text, count=1,
                  flags=re.MULTILINE | re.DOTALL)


# --- writing ----------------------------------------------------------------------------------------

def _replace_once(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(pattern, lambda _match: replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"could not find the version line in {path}")
    path.write_text(new_text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("level", nargs="?", choices=LEVELS, 
                        help="bump level, taken from the PR label")
    parser.add_argument("--check", action="store_true",
                        help="only validate the Unreleased section (the pull-request gate)")
    parser.add_argument("--is-prepared", action="store_true",
                        help="exit 0 when CHANGELOG.md already carries a section for the version "
                             "in src/version.py - i.e. the bump has already run on this branch")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the next version, write nothing")
    args = parser.parse_args()

    changelog = CHANGELOG.read_text(encoding="utf-8")
    # Asked before --check, and keyed on the changelog/version pair rather than the tip commit
    # subject: a merge landing after the bump would hide a subject test, but cannot hide this.
    # Same reasoning as tag.yml, which keys on the version file for exactly this robustness.
    if args.is_prepared:
        version = source_version()
        has_section = re.search(rf"^##\s+v{re.escape(version)}\b", changelog, re.MULTILINE) is not None
        notes_pending = bool(_strip_comments(unreleased_body(changelog)).strip())
        # Prepared means the bump already moved *this cycle's* notes out of Unreleased, so both
        # halves are needed. The version's own section survices every later release, so on its own
        # it would skip every future bump; an empty Unreleased section alone can't tell "just bumped" from
        # "nothing written yet".
        prepared = has_section and not notes_pending
        print(f"v{version}: section {'present' if has_section else 'absent'}, "
              f"Unreleased {'has notes' if notes_pending else 'empty'} -> "
              f"{'already prepared' if prepared else 'not prepared'}")
        return 0 if prepared else 1
    
    problems = check(changelog)
    if args.check:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1 if problems else 0

    if args.level is None:
        parser.error("a bump level is required unless --check is given")
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1

    current = source_version()
    if current != project_version():
            print("src/version.py and pyproject.toml disagree - fix that first "
            "(python packaging/check_version.py).", file=sys.stderr)
            return 1

    new = next_version(current, args.level)
    if args.dry_run:
        print(new)
        return 0

    _replace_once(VERSION_PY, r'^__version__ = "[^"]+"', f'__version__ = "{new}"')
    _replace_once(PYPROJECT, r'^version = "[^"]+"', f'version = "{new}"')
    CHANGELOG.write_text(release_unreleased(changelog, new, dt.date.today()), encoding="utf-8")
    print(new)          # the workflow captures stdout as the new version
    return 0


if __name__ == "__main__":
    sys.exit(main())