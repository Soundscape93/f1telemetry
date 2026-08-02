"""Consistent copies of the live database, via SQLite's ``VACUUM INTO``.

The point of this module is that it is safe on a database that is *in use*. Copying the file with
the filesystem is not: with WAL on, committed pages live in a ``-wal`` sibling that a naive copy
either misses or catches mid-write, so the copy can be stale or torn. ``VACUUM INTO`` writes a new,
fully checkpointed, defragmented database out of a single read transaction - which is exactly what
"send me your database" wants for a bug report (PACKAGING -> "Data layout & the database").

This is **not** the "open the database" action the project has ruled out. It hands the user a copy
at a path they chose; the live file stays unexposed and unserviceable.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .engine import create_db_engine


def default_backup_name(now: datetime | None = None) -> str:
    """Suggested filename for a backup - sortable, and obvious about what the file is."""
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"f1telemetry_backup_{stamp}.db"


def backup_database(url: str, destination: str | Path, *, overwrite: bool = False) -> Path:
    """Write a consistent copy of the database at ``url`` to ``destination``; return its path.

    ``VACUUM INTO`` refuses to write over an existing file ("output file already exists"), so
    ``overwrite`` unlinks first - the caller is expected to have asked the user already, which a
    save dialog does. Raises ``FileExistsError`` when the destination exists and ``overwrite`` is
    False, ``OSError`` if it can't be removed, and ``sqlalchemy.exc.DatabaseError`` if the copy
    itself fails.
    """
    path = Path(destination)
    if path.exists():
        if not overwrite:
            raise FileExistsError(f"{path} already exists")
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Opened the app's normal way so the backup inherits busy_timeout - it may well run while an
    # ingest is writing, which is the case this while feature exists to survive.
    engine = create_db_engine(url)
    try:
        # AUTOCOMMIT because VACUUM cannot run inside a transaction. The path is bound as a 
        # parameter rather than interpolated, so a Windows path's backslashes and any quote in a
        # user-chosen filename can't break the statement.
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.exec_driver_sql("VACUUM INTO ?", (str(path),))
    finally:
        engine.dispose()
    return path