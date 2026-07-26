"""Central, packaging-aware filesystem paths.

Two distinct location needs - do not conflate them:

* :func:`data_root` per user *writable* data (DB, captures, lap traces, rosters, logs, config).
* :func:`resource_path` bundled *read-only* assets shipped with the app (flag SVGs).

Resolution rules (see docs/PACKAGING.md "the fix: a paths.py helper"):

* ``F1TELEMETRY_DATA_DIR`` env var, if set, wins for the data root in every mode (dev, tests,
    power users).
* **Frozen** (PyInstaller ``sys.frozen``): data goes under the OS per-user local-data dir
    (``%LOCALAPPDATA%\\f1telemetry`` / ``~/Library/Application Support/f1telemetry`` /
    ``~/.local/share/f1telemetry``); assets resolve under ``sys._MEIPASS``.
* **Source / dev** (not frozen): data root is the current working directory - preserving today's
    workspace-root ``f1league.db``/ ``captures``/ ``lap_traces``/ ``rosters`` layout exactly;
    assets resolve from the source tree.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ENV_DATA_DIR = "F1TELEMETRY_DATA_DIR"
_APP_DIR_NAME = "f1telemetry"

# .../f1telemetry/src in a source checkout; the package-relative anchor for bundled assets.
_SRC_DIR = Path(__file__).resolve().parent


def is_frozen() -> bool:
    """True when running from a PyInstaller (or similar) frozen bundle."""
    return bool(getattr(sys, "frozen", False))


# --- data root (per-user writable) ------------------------------------------------

def _frozen_data_root() -> Path:
    """The per-user local-data directory for a packaged build.
    
    Uses ``GenericDataLocation`` and appends the app name ourselfs so the result is independent
    of whether ``QApplication`` has set the application/organization name yet (logging is
    configured before the QApplication exists).
    """
    from PySide6.QtCore import QStandardPaths

    base = QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)
    return Path(base) / _APP_DIR_NAME


def _resolve_data_root() -> Path:
    override = os.environ.get(_ENV_DATA_DIR)
    if override:
        return Path(override).expanduser()
    if is_frozen():
        return _frozen_data_root()
    return Path.cwd()


def data_root() -> Path:
    """The per-user writable data directory, created if missing.
    
    Not cached, so the ``F1TELEMETRY_DATA_DIR`` override (and, in tests the CWD) is honored on
    every call; the underlying ``mkdir(exists_ok=True)`` is a cheap stat when it already exists.
    """
    root = _resolve_data_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _ensure_subdir(name: str) -> Path:
    path = data_root() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    """Absolute path to the SQLite database file inside the data root."""
    return data_root() / "f1league.db"


def db_url() -> str:
    """SQLAlchemy URL for the database (POSIX slashes so Windows drive path parse cleanly)."""
    return f"sqlite:///{db_path().as_posix()}"


def captures_dir() -> Path:
    """Directory that holds records ``.f1cap``archives."""
    return _ensure_subdir("captures")


def trace_dir() -> Path:
    """Directory that holds each lap's dense Parquet trace tree."""
    return _ensure_subdir("lap_traces")


def rosters_dir() -> Path:
    """Directory that holds per-season canonical roster JSON files."""
    return _ensure_subdir("rosters")


def logs_dir() -> Path:
    """Directory for the app's rotating log files."""
    return _ensure_subdir("logs")


def config_path() -> Path:
    """Path to the (future) user config file. The file is not created here."""
    return data_root() / "config.json"


# --- bundled read-only assets (flag SVGs, etc.) ---------------------------------------------

def resource_path(*parts: str) -> Path:
    """Resolve a bundled read-only asset, given its path *relative to the ``src`` package*.
    
    e.g. ``resource_path("ui", "assets", "flags")``. In a frozen build this resolves under
    ``sys._MEIPASS`` (Phase 1's PyInstaller spec must ship these assets preserving the
    ``f1telemetry/src...`` layout via ``datas``); in a source run it resolves from the tree.
    """
    if is_frozen():
        base = Path(sys._MEIPASS) / "f1telemetry" / "src"       # type: ignore[attr-defined]
    else:
        base = _SRC_DIR
    return base.joinpath(*parts)


# --- beside the exe (the third path kind) ----------------------------------------------------

def app_dir() -> Path:
    """The directory the app itself lives in - *beside the exe* in a packaged build.

    A third location kind, distinct from both above (docs/PACKAGING.md, Phase 3): in a one-folder
    PyInstaller build ``sys.executable`` is ``dist/f1telemetry/f1telemetry.exe`` while
    ``_MEIPASS`` is ``dist/f1telemetry/_internal``. Files the *user* is meant to find without
    launching the app (``USER_GUIDE.pdf``, ``roster_template.csv``) ship here - never under
    :func:`resource_path`, which would bury them inside ``_internal``.

    In a source run there is no exe, so the repo root (the parent of ``src``) is the analogue.
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return _SRC_DIR.parent


def source_docs_dir() -> Path:
    """``docs/`` in a source checkout - dev-run fallback for the user guide.
    
    Meaningless in a frozen build (``docs/`` is not shipped); callers test for existence rather
    than for :func:`is_frozen`, so the answer is the same either way.
    """
    return _SRC_DIR.parent / "docs"
