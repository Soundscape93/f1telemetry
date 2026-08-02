"""One place that opens the SQLite database, so every store leaves it in the same state.

The five stores are repositories over the *same* file (repository-per-aggregate, see DECISIONS ->
Storage) and each builds its own ``Engine`` - deliberately, because SQLite dislikes a connection
shared across threads and the ingest / re-ingest workers run on theirs. Connection setup therefore
has to be a shared *function*, not a shared object: whichever store happens to open the database
first must configure it exactly as any other would have.

What that setup does today is the Cycle-1 C2 work - turn WAL on:

- ``journal_mode=WAL`` lets a reader (the GUI thread) and a writer (an ingest worker) work at the
  same time instead of locking each other out. That is what a minutes-long re-ingest needs, it is
  the double-launch case from the Phase-1 checklist, and it is what makes ``backup.py`` safe on a
  live database. WAL is a **persistent** property written into the file header, so re-applying it
  on every connection is redundant - but it is cheap, and it is the only way to be sure a database
  created by *whichever* of the five stores ran first ends up with it.
- ``synchronous=NORMAL`` is WAL's usual companion: still durable against an application crash,
  and only at risk of losing the last few commits to an OS crash or power loss. That trade is
  already this project's stated position - the database is deliberately disposable and rebuildable
  from the captures (PACKAGING -> "Data layout & the database"), so paying a full fsync per commit
  through a re-ingest buys durability for data we can recreate anyway.
- ``busy_timeout`` makes a store that *does* meet a locked database wait instead of failing at
  once. WAL removes most of that contention; this covers what is left.

Deliberately NOT set: ``foreign_keys``. SQLite leaves FK enforcement off by default, and the
schema's cascades are ORM-level. Turning it on is a real behaviour change (and would interact with
invariant #4, the intentionally FK-free ``session_assignments``), so it belongs with the Alembic
decision in DECISIONS -> Migrations, not with WAL.
"""
from __future__ import annotations

from sqlalchemy import Engine, create_engine, event

# Long enough to outlast a re-ingest's individual wrtie transactions, short enough that genuinely
# wedged database still surfaces an error rather than a hang.
_BUSY_TIMEOUT_MS = 10_000


def create_db_engine(url: str, *, echo: bool = False) -> Engine:
    """The app's ``Engine`` for ``url``: a plain SQLAlchemy engine plus the SQLite pragmas above.

    A non-SQLite URL passes straight through untouched, so the storage layer stays engine-agnostic
    and the "could move to Postgres" door DECISIONS keeps open stays open.
    """
    engine = create_engine(url, echo=echo)

    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _apply_sqlite_pragmas)
    return engine


def _apply_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    """Apply the per-connection PRAGMAs through the raw DBAPI cursor.

    PRAGMA has to run outside SQLAlchemy's transaction handling, hence the driver cursor rather
    than a ``Connection``. An in-memory database answers ``memory`` to the WAL request instead of
    raising, so the tests' file-backed and any throwaway in-memory database both work.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    finally:
        cursor.close()
