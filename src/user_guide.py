"""Locate the user guide for the Help page's "Open user guide" action.

Qt-free and side-effect-free so the fallback chain is unit-testable: this only decides *what* to
open; the Help page hands the result to ``QDesktopServices``. Three steps, so the action can never
dead-end (docs/PACKAGING.md "Phase 3 - agreed scope", item 1):

1. ``USER_GUIDE.pdf`` beside the exe - the packaged build. CI generates it and the release zip
   ships it at the top level, next to the exe, where a tester finds it without opening the app.
2. else ``docs/USER_GUIDE.md`` in the source tree - dev runs; the OS opens it with whatever is
   registered for ``.md``.
3. else the guide rendered on GitHub - costs nothing (the owner/repo constants already exist for
   the update check) and still works for someone who unzipped only the exe.

``resolve_notices`` - two steps, because ``NOTICE.md`` needs no source-tree special case:
``app_dir()`` is *beside the exe* when frozen and the *repo root* in a source run, and the file
lives at the repo root, so one probe covers both. Falls back to the copy on GitHub. That fallback
is not just convenience - the LGPL v3 notice for the bundled Qt/PySide6 has to reach whoever got
the binary.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import paths
from .update_check import GITHUB_OWNER, GITHUB_REPO

PDF_NAME = "USER_GUIDE.pdf"
MD_NAME = "USER_GUIDE.md"
NOTICES_NAME = "NOTICE.md"
_BRANCH = "main"  # the default branch the guide is read from


@dataclass(frozen=True)
class GuideTarget:
    """What to open. Exactly one of the two is set - the caller needs the distinction, since a 
    local path must be wrapped in ``QUrl.fromLocalFile()`` and a URL must not be."""
    path: Path | None = None
    url: str | None = None

    @property
    def is_local(self) -> bool:
        return self.path is not None


def github_url() -> str:
    """The guide rendered on GitHub - the last-resort fallback."""
    return f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/blob/{_BRANCH}/docs/{MD_NAME}"


def resolve_guide(*, app_dir: Path | None = None, docs_dir: Path | None = None) -> GuideTarget:
    """The first of the three steps above that exists. Never raises; always returns a target.

    Both directories are injectable so the chain is testable without a frozen build.
    """
    app_dir = paths.app_dir() if app_dir is None else app_dir
    docs_dir = paths.source_docs_dir() if docs_dir is None else docs_dir

    pdf = app_dir / PDF_NAME
    if pdf.is_file():
        return GuideTarget(path=pdf)
    markdown = docs_dir / MD_NAME
    if markdown.is_file():
        return GuideTarget(path=markdown)
    return GuideTarget(url=github_url())


def notices_url() -> str:
    """The notice rendered on GitHub - the fallback when the file wasn't unzipped."""
    return f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/blob/{_BRANCH}/{NOTICES_NAME}"


def resolve_notices(*, app_dir: Path | None = None) -> GuideTarget:
    """Licence + third-party notices. Never raises; always returns a target.
    
    Only two steps, unlike the guide: ``app_dir`` is *beside the exe* when frozen and the 
    *repo root* in a source run, and NOTICE.md lives at the repo root - so one probe covers
    both. The LGPL notice for the bundled Qt must reach the user, hence the URL fallback for
    someone who unzipped only the exe.
    """
    app_dir = paths.app_dir() if app_dir is None else app_dir

    notices = app_dir / NOTICES_NAME
    if notices.is_file():
        return GuideTarget(path=notices)
    return GuideTarget(url=notices_url())