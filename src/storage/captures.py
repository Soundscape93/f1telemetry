"""Persists for the capture aggregate (repository-per-aggregate; see DECISIONS -> Storage).

Owns ``captures`` + ``capture_sessions``: what recordings exist, what they contain, and where
they were last seen - so the app can answer "have I already imported this?" and "which file do
I re-ingest to back-fill the session?" without decompressing a payload.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ..domain.captures import CaptureMeta
from .migrations import ensure_schema
from .schema import Base, CaptureRow, CaptureSessionRow

_DEFAULT_URL = "sqlite:///f1league.db"

class CaptureStore:
    """A SQLite-backed store for capture metadata."""

    def __init__(self, url: str = _DEFAULT_URL, echo: bool = False) -> None:
        self._engine = create_engine(url, echo=echo)
        Base.metadata.create_all(self._engine)      # new tables (incl. captures)
        ensure_schema(self._engine)                  # additive columns on existing tables
        self._Session = sessionmaker(self._engine)
    
    # --- lifecycle -------------------------------------------------------------
    def close(self) -> None:
        """Dispose the engine and close its pooled connections. Safe to call more than once."""
        self._engine.dispose()
    
    def __enter__(self) -> CaptureStore:
        return self
    
    def __exit__(self, *exc) -> None:
        self.close()

    # --- write -----------------------------------------------------------------
    def record(self, meta: CaptureMeta) -> None:
        """Persists a capture, replacing any existing row with the same content hash.
        
        Replace-by-hash mirrors ``SessionStore.save``'s replace-by-uid, so re-ingesting a
        capture (or importing one that's already known under a different filename) is
        idempotent and simply refreshes its path/codec/size.
        """
        with self._Session.begin() as db:
            existing = db.get(CaptureRow, meta.content_hash)
            if existing is not None:
                db.delete(existing)             # cascade clears capture_sessions
                db.flush()
            db.add(self._to_row(meta))
    
    def relocate(self, content_hash: str, path: str, file_size: int, codec: str) -> None:
        """Point a known capture at a new file, e.g. after it's archived. False if unknown."""
        with self._Session.begin() as db:
            row = db.get(CaptureRow, content_hash)
            if row is None:
                return False
            row.path, row.file_size, row.codec = path, file_size, codec
            row.file_name = path.rsplit("/", 1)[-1]
            return True
    
    def delete(self, content_hash: str) -> bool:
        """Forget a capture. False if it wasn't known."""
        with self._Session.begin() as db:
            row = db.get(CaptureRow, content_hash)
            if row is None:
                return False
            db.delete(row)
            return True
    
    # --- read ------------------------------------------------------------------
    def has(self, content_hash: str) -> bool:
        with self._Session.begin() as db:
            return db.get(CaptureRow, content_hash) is not None
    
    def get(self, content_hash: str) -> CaptureMeta | None:
        with self._Session.begin() as db:
            row = db.get(CaptureRow, content_hash)
            return self._to_domain(row) if row is not None else None
    
    def list_captures(self) -> list[CaptureMeta]:
        """Every knwon capture, newest ingest first."""
        with self._Session.begin() as db:
            rows = db.scalars(
                select(CaptureRow).order_by(CaptureRow.ingested_at.desc())).all()
            return [self._to_domain(row) for row in rows]
    
    def for_session(self, session_uid: str) -> list[CaptureMeta]:
        """Captures containing ``session_uid`` - the back-fill re-ingest lookup.
        
        A list, not a single value: the same session can legitimately live in more than one
        file (a member's original plus someone else's imported copy under a diffrent name).
        """
        with self._Session.begin() as db:
            rows = db.scalars(
                select(CaptureRow)
                .join(CaptureSessionRow)
                .where(CaptureSessionRow.session_uid == str(session_uid))
                ).all()
            return [self._to_domain(row) for row in rows]
    
    def known_files(self) -> set[tuple[str, int]]:
        """``(file_name, file_size)`` pairs alredy ingested - the folder-scan pre-filter.
        
        Cheap and deliberately *not* authoritative: the content hash is the real identity, but
        computing it means decompressing the payload. A folder scan skips anything matching a
        known name+size, and anything else gets read - at which point the hash decides whether
        it's genuinely new. A renamed capture therefore coste one wasted read, never a duplicate.
        """
        with self._Session.begin() as db:
            return set(db.execute(select(CaptureRow.file_name, CaptureRow.file_size)).all())
    
    # --- mapping ----------------------------------------------------------------
    @staticmethod
    def _to_row(meta: CaptureMeta) -> CaptureRow:
        return CaptureRow(
            content_hash=meta.content_hash,
            path=meta.path,
            file_name=meta.file_name,
            file_size=meta.file_size,
            payload_size=meta.payload_size,
            codec=meta.codec,
            packet_count=meta.packet_count,
            recorded_by=meta.recorded_by,
            ingested_at=meta.ingested_at or datetime.now(timezone.utc),
            first_packet_at=meta.first_packet_at,
            last_packet_at=meta.last_packet_at,
            sessions=[
                CaptureSessionRow(session_uid=uid) for uid in meta.session_uids
            ],
        )
    
    @staticmethod
    def _to_domain(row: CaptureRow) -> CaptureMeta:
        return CaptureMeta(
            content_hash=row.content_hash,
            path=row.path,
            file_name=row.file_name,
            file_size=row.file_size,
            payload_size=row.payload_size,
            codec=row.codec,
            packet_count=row.packet_count,
            session_uids=tuple(s.session_uid for s in row.sessions),
            recorded_by=row.recorded_by,
            ingested_at=row.ingested_at,
            first_packet_at=row.first_packet_at,
            last_packet_at=row.last_packet_at,
        )