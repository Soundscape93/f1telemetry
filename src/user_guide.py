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

``resolve_notices`` - three steps, the same *shape* as the guide and for the same reason. The PDF
is preferred because it is the **readable** one: a user without a markdown viewer opens the
``.md`` in Notepad and reads ``#`` and ``**``. ``app_dir()`` is *beside the exe* when frozen and
the *repo root* in a source run, and the ``.pdf`` is CI-generated and gitignored, so one pair of
probes covers both worlds with no ``is_frozen()`` branch: a release build finds the PDF, a source
run finds only the markdown. Falls back to the copy on GitHub. That fallback is not just
convenience - the LGPL v3 notice for the bundled Qt/PySide6 has to reach whoever got the binary.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import paths
from .update_check import GITHUB_OWNER, GITHUB_REPO

PDF_NAME = "USER_GUIDE.pdf"
MD_NAME = "USER_GUIDE.md"
NOTICES_NAME = "NOTICE.md"
NOTICES_PDF_NAME = "NOTICE.pdf"
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
    
    Three steps, and a presence decides at every one - never :func:`paths.is_frozen()` which is what
    keeps this symmetrical with :func:`resolve_guide`:

    1. ``NOTICE.pdf`` beside the exe - a release build. **Preferred, because it is the readable
       one**; shipping a PDF and then opening the raw markdown anyway would defeat the point.
    2. else ``NOTICE.md`` in the same directory. ``app_dir()`` is the *repo root* in a source run
       and the PDF is a CI artifact that is never committed, so this is the dev path, unchanged.
       It is also the packaged fallback if only part of the archive was extracted.
    3. else the copy on GitHub, so the action can never dead-end.
    """
    app_dir = paths.app_dir() if app_dir is None else app_dir

    pdf = app_dir / NOTICES_PDF_NAME
    if pdf.is_file():
        return GuideTarget(path=pdf)
    notices = app_dir / NOTICES_NAME
    if notices.is_file():
        return GuideTarget(path=notices)
    return GuideTarget(url=notices_url())
