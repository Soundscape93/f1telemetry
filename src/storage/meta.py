"""MetaStore - small key/value app state that belongs to no aggregate.

Repository-per-aggregate sibling of the other stores, for the one thing that isn't part of any
aggregate: the ``PIPELINE_VERSION`` the database's *derived* data was produced by.

The stamp is deliberately independent of the app's SemVer (see ``src/version.py``): a release
that only changes the UI must not force a re-ingest, and a pipeline change without a release
still needs the bump. It answers exactly one question on start-up - "does this build read more
out of a capture than the stored rows hold?" - which gates the guided re-ingest in
``pipeline.reingest_all`` (docs/PACKAGING.md → Phase 2).
"""
from __future__ import annotations

import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .migrations import ensure_schema
from .schema import Base, MetaRow

log = logging.getLogger(__name__)

_DEFAULT_URL = "sqlite:///f1league.db"

_PIPELINE_KEY = "pipeline_version"

# What a database that holds sessions but carries no stamp counts as. Its rows were derived
# before the stamp existed (i.e. before Phase 2), so it is older than any shipped pipeline and
# is offered the re-ingest rather than silently adopted. Must stay below PIPELINE_VERSION.
LEGACY_PIPELINE_VERSION = 0


class MetaStore:
    """A SQLite-backed key/value store for the app level state."""

    def __init__(self, url: str = _DEFAULT_URL, echo: bool = False) -> None:
        self._engine = create_engine(url, echo=echo)
        Base.metadata.create_all(self._engine)      # new tables (incl. meta)
        ensure_schema(self._engine)                 # additive columns on existing tables
        self._Session = sessionmaker(self._engine)

    # --- lifecycle --------------------------------------------------------------
    def close(self) -> None:
        """Dispose the engine and close its pooled connections. Safe to call more than once."""
        self._engine.dispose()

    def __enter__(self) -> "MetaStore":
        return self
    
    def __exit__(self, *exc) -> None:
        self.close()

    # --- generic key/value ---------------------------------------------------------
    def get(self, key: str) -> str | None:
        """The stored value for ``key``, or None if it was never written."""
        with self._Session.begin() as db:
            row = db.get(MetaRow, key)
            return row.value if row is not None else None

    def set(self, key: str, value: str) -> None:
        """Write a key, replacing any existing value (merge -> idempotent re-writes)."""
        with self._Session.begin() as db:
            db.merge(MetaRow(key=key, value=value))

    # --- pipeline stamp ---------------------------------------------------------
    def pipeline_version(self) -> int  | None:
        """The PIPELINE_VERSION this database's derived data was produced by.
        
        ``None`` means "never stamped" - either a brand-new database or one written before the
        stamp existed; ``pipeline.check_pipeline_version`` decides which. A non-integer value
        (hand-edited or corrupted) reads as unstamped rather than crashing the start-up path.
        """
        raw = self.get(_PIPELINE_KEY)
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            log.warning("Ignoring unpareable %s in meta: %r", _PIPELINE_KEY, raw)
            return None

    def set_pipeline_version(self, version: int) -> None:
        """Stamp the database as carrying data derived by pipeline ``version``."""
        self.set(_PIPELINE_KEY, str(int(version)))
