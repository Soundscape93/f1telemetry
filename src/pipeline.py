"""Application-level orchestration: turn a capture file into stored sessions.

`ìngest_capture`` is the parse -> assemble -> persist path that the recording UI runs after
a capture and that the integration test runs against a fixture. It's a plain function (no Qt)
so it can be tested directly; the GUI's ``IngestWorker``is a thin wrapper that calls it on a
background thread and reports the result through signals.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum, auto

from .domain.captures import CaptureMeta
from .domain.models import SessionResult
from .ingest.archive import (HashingReader, archive_capture, capture_codec,
                                is_compressed_capture, open_capture)
from .ingest.recording import read_header, read_packet
from .protocol.parser import PacketParser
from .protocol.registry import build_registry
from .session.assembler import assemble
from .storage.captures import CaptureStore
from .storage.meta import LEGACY_PIPELINE_VERSION, MetaStore
from .storage.sessions import SessionStore
from .version import PIPELINE_VERSION

log = logging.getLogger(__name__)


class _CaptureScan:
    """Capture-level facts accumulated while the packets stream past.
    
    Exists so the metadata row costs nothing extra: the hash, sizes, packet count and time span
    all fall out of the read ingest already performs, rather than a second decompression of a
    multi-hundred-MB archive.
    """

    def __init__(self) -> None:
        self._reader: HashingReader | None = None
        self.packet_count = 0
        self.first_recv_time: float | None = None
        self.last_recv_time: float | None = None
        self.session_uids: list[str] = []
    
    def wrap(self, fh) -> HashingReader:
        self._reader = HashingReader(fh)
        return self._reader
    
    def note_packet(self, recv_time: float) -> None:
        self.packet_count += 1
        if self.first_recv_time is None or recv_time < self.first_recv_time:
            self.first_recv_time = recv_time
        if self.last_recv_time is None or recv_time > self.last_recv_time:
            self.last_recv_time = recv_time
    
    def to_meta(self, capture_path: str, recorded_by: str | None) -> CaptureMeta:
        """The metadata row for the scanned capture. Only valid once the stream hit EOF."""
        return CaptureMeta(
            content_hash=self._reader.content_hash if self._reader else "",
            path=os.path.abspath(capture_path),
            file_name=os.path.basename(capture_path),
            file_size=os.path.getsize(capture_path),
            payload_size=self._reader.payload_size if self._reader else 0,
            codec=capture_codec(capture_path),
            packet_count=self.packet_count,
            session_uids=tuple(self.session_uids),
            recorded_by=recorded_by,
            ingested_at=datetime.now(timezone.utc),
            first_packet_at=_as_utc(self.first_recv_time),
            last_packet_at=_as_utc(self.last_recv_time),
        )
    

def _as_utc(recv_time: float | None) -> datetime | None:
    return None if recv_time is None else datetime.fromtimestamp(recv_time, timezone.utc)


def ingest_capture(capture_path: str, store: SessionStore, lap_store=None,
                   capture_store = None, recorded_by: str | None = None) -> list[SessionResult]:
    """Parse a .f1cap file, assemble its session, persists each, and return what was stored.
    
    A single capture can contain several sessions (multiple weekends and/or multiple sessions),
    so this returns a list - on ``SessionResult`` per session the assembler emitted. The Store
    is passed in (not constructed here) so callers control its lifetime and, for SQLite, the
    thread it lives on.

    Each session is stamped with ``recorded_at`` = the wall-clock time of its *earliest* packet
    (the capture's per-packet ``recv_time``), so two attempts of the same session driven within
    one recording get distinct, chronological timestamps. We read the capture directly here
    rather than via ``FileReplaySource`` because we need each packet's ``recv_time``, which that
    source drops.

    Sessions the user has deleted from the store are tombstoned (see ``SessionStore.delete``);
    those uids are skipped here so re-ingesting a capture doesn't resurrect a deliberately
    removed attempt. The returned list therefore covers only the sessions actually stored.

    ``capture_store`` is optional (like ``lap_store``): when given, the capture's metadata is
    recorded so it's queryable without decompressing it again. That row describes the *file* -
    it lists every session the capture contains, including tombstoned ones this call skipped -
    and is keyed by a content hash computed from the bytes as they stream past.
    """
    parser = PacketParser(build_registry())
    earliest: dict[int, float] = {}   # session_uid -> earliest packet recv_time
    scan = _CaptureScan()

    def parsed() -> Iterator:
        with open_capture(capture_path) as fh:
            reader = scan.wrap(fh)
            read_header(reader)
            while (record := read_packet(reader)) is not None:
                scan.note_packet(record.recv_time)
                packet = parser.parse(record.data)
                if packet is None:
                    continue
                uid = packet.header.session_uid
                if uid and record.recv_time < earliest.get(uid, float("inf")):
                    earliest[uid] = record.recv_time        # uid==0 is init noise, ignored downstream
                yield packet
    
    tombstoned = store.deleted_uids()           # sessions the user deleted on purpose - don't resurrect
    saved: list[SessionResult] = []
    for session in assemble(parsed()):
        scan.session_uids.append(str(session.session_uid))      # what the FILE holds, tombstones included
        if session.session_uid in tombstoned:
            continue
        recv_time = earliest.get(session.session_uid)
        if recv_time is not None:
            session = replace(
                session, recorded_at=datetime.fromtimestamp(recv_time, timezone.utc))
        store.save(session)
        if lap_store is not None:
            lap_store.save_laps(session.session_uid, session.laps)
        saved.append(session)

    if capture_store is not None:
        capture_store.record(scan.to_meta(capture_path, recorded_by))
    return saved


def archive_and_ingest(capture_path: str, store: SessionStore, lap_store=None,
                     capture_store = None, recorded_by: str | None = None) -> list[SessionResult]:
    """Archive a raw capture, ingest it, and delete the raw only once ingest succeeds.
     
    The Qt-free orchestration behind ``IngestWorker`` (which is a thin wrapper over this, as it
    is over ``ingest_capture``). The ordering is the safety property (DECISIONS -> Storage):

        1. Compress the raw capture *first*, keeping the original (``remove_original=False``).
        2. Ingest the **archive** - the decompressor verifies its own frame checksum end-to-end as
            the bytes stream past, so a corrupt archive fails the ingest.
        3. Delete the raw only after that succeeds - never before its bytes are proven readable in
            the archive.
    
    So a capture that fails to parse is left as *both* a raw file (for debugging) and a small
    archive (uploadable to the league folder), and the sole readable copy is never destroyed on
    trust. New archives are zstd; ``.gz`` stays readable forever.

    An already-archived input (a re-ingest of a ``.gz`` / ``.zst``) is ingested in place: nothing
    is re-compressed, and nothing is deleted. Archiving is non-fatal - if it fails, the raw is
    ingested directly and kept.

    Returns ``(sessions, archive_path, archive_error)``: ``archive_path`` is the new archive that
    was written ("" when none was - a re-ingest, or an archive failure), and ``archive_error`` a
    message when archiving failed.
    """
    archive_path = ""
    archive_error = ""
    raw_to_delete: str | None = None

    if is_compressed_capture(capture_path):
        ingest_path = capture_path          # re-ingest: already archived, leave it be
    else:
        try:
            # archive first, keeping the raw; the raw is removed only after ingest succeeds
            archive_path = str(archive_capture(capture_path, remove_original=False))
            ingest_path = archive_path
            raw_to_delete = capture_path
        except Exception as exc:
            archive_error = str(exc)           # non-fatal: fall back to ingesting the raw
            ingest_path = capture_path
    
    sessions = ingest_capture(
        ingest_path, store, lap_store=lap_store, capture_store=capture_store,
        recorded_by=recorded_by
    )

    # Ingest read the archive the EOF without error, so the raw's bytes are safe in it.
    if raw_to_delete is not None and os.path.exists(raw_to_delete):
        os.remove(raw_to_delete)
    
    return sessions, archive_path, archive_error


# --- pipeline version gate & guieded re-ingest -------------------------------------------------------------
#
# Three change types decide "must the user re-ingest?" (docs/PACKAGING.md):
#   1. additive schema changes                  -> silent, ``ensure_schema`` on every store reconstruction
#   2. additive + needs values from packets     -> the column exists, but rows are stale;
#                                               THIS is what PIPELINE_VERSION gates
#  3. non-additive                              -> Albemic, deffered unit the first one exists
# Only (2) is handled here. The version is bumped in ``version.py`` when ingest starts producing
# diffrent or new derived data - never for a UI-only release.


class PipelineState(Enum):
    """How a database's derived data relates to this build's ingest pipeline."""

    CURRENT = auto()      # stamped with this build's version - nothing to do
    UPGRADE_AVAILABLE = auto()  # older: this build derives data the stored rows don't have
    AHEAD = auto()        # newer: written by a later build. Re-ingest would DOWNGRADE


@dataclass(frozen=True)
class PipelineCheck:
    """The start-up check comparison result: what the database holds vs what this build produces."""

    state: PipelineState
    stored: int
    current: int


def check_pipeline_version(meta_store: MetaStore, session_store: SessionStore,
                           current: int = PIPELINE_VERSION) -> PipelineCheck:
    """Compare the database's pipeline stamp with this build's, adopting an unstamped one.
    
    Runs *after* ``create_all`` + ``ensure_schema`` (every store does both in its constructor),
    so the silent additive migration always precedes this: the column exists by the time we ask
    whether its values are stale.

    An **unstamped** database is one of two things, and the difference matters:

    * **no sessions** - brand new, nothing has been derived yet, so it is stamped with
      ``current`` immediately. A first launch must never prompt.
    * **has sessions** - it predates the stamp itself, so its rows were derived by an unknown
      older pipeline: treated as :data:`LEGACY_PIPELINE_VERSION` and offered the re-ingest. It
      is deliberately *not* stamped here - only a completed rebuild (or an explicit
      "don't ask again") writes the new value.

    Writing is confined to that one adopt-a-fresh-database case; every other path is read-only.
    """
    stored = meta_store.pipeline_version()
    if stored is None:
        if session_store.stored_uids():      # has sessions, predates the stamp
            stored = LEGACY_PIPELINE_VERSION
        else:                                 # no sessions, adopt the current build's version
            stored = current
            meta_store.set_pipeline_version(current)

    if stored < current:
        state = PipelineState.UPGRADE_AVAILABLE
    elif stored > current:
        state = PipelineState.AHEAD
    else:
        state = PipelineState.CURRENT
    return PipelineCheck(state=state, stored=stored, current=current)


def resolve_capture_path(meta: CaptureMeta, captures_dir: str | os.PathLike | None = None) -> str:
    """Where a known capture's bytes are *now*, or None if the archive can't be found.

    ``CaptureRow.path`` is advisory by design (DECISIONS -> Storage): captures move between
    machines and data roots, and the content hash - not the location - is the identity. So the
    recorded path is tried first, then the app's captures directory under the recorded file
    name. That second lookup covers the case that actually happens: a data root that moved
    (a dev checkout's ``captures/`` vs a frozen build's ``%LOCALAPPDATA%``), or a capture
    ingested from Downloads and later copied into place."""
    if meta.path and os.path.isfile(meta.path):
        return meta.path
    if captures_dir:
        candidate = os.path.join(str(captures_dir), meta.file_name)
        if os.path.isfile(candidate):
            return candidate
    return None


@dataclass(frozen=True)
class ReingestSummary:
    """What one guided re-ingest pass managed to rebuild."""

    captures_total: int
    captures_ingested: int
    sessions_total: int                 # stored sessions when the pass started
    sessions_rebuilt: int               # of those, how many were re-derived from a capture
    missing: tuple[str, ...] = ()       # captures whose archive is gone - unrebuildable
    errors: tuple[str, ...] = ()        # "<file name: error>", one per capture that failed
    cancelled: bool = False

    @property
    def is_complete(self) -> bool:
        """Whether the pass finished cleanly enough to stamp the new PIPELINE_VERSION.

        Missing archives deliberately do NOT block it: nothing the app can ever do will rebuild
        those rows, so refusing to stamp would re-offer the same impossible upgrade on every
        launch. A cancel or a real ingest error does block it - both are worth retrying.
        """
        return not self.cancelled and not self.errors


def reingest_all(capture_store: CaptureStore, session_store: SessionStore, *,
                 lap_store=None,
                 captures_dir: str | os.PathLike | None = None,
                 on_progress: Callable[[int, int, str], None] | None = None,
                 cancelled: Callable[[], bool] | None = None,
                 ingest: Callable[..., list[SessionResult]] = ingest_capture) -> ReingestSummary:
    """Re-derive every stored session from the capture archives ``captures`` enumerates.

    The Qt-free half of the guided re-ingest (docs/PACKAGING.md -> Phase 2); the UI's
    ``ReingestWorker`` is a thin wrapper that runs this on a background thread and forwards
    ``on_progress`` as Qt signals - the same split as ``archive_and_ingest`` / ``IngestWorker``.

    **Idempotent and resumable by construction**, so a cancelled or half-finished pass costs
    nothing and can simply be run again: ``ingest_capture`` replaces by ``session_uid`` and
    ``CaptureStore.record`` by content hash, while season assignments, rosters and tombstones
    are keyed on the uid and deliberately not FK'd to ``sessions`` (core invariant #4) - so
    rebuilding derived rows never touches standings, round placements or curation. Sessions the
    user deleted stay deleted: ingest skips tombstoned uids.

    Archives are ingested **in place** (``ingest_capture``, not ``archive_and_ingest``): nothing
    is re-compressed, and a re-ingest never deletes a file. ``recorded_by`` is fed back from the
    existing metadata row - it isn't in the capture file, so this is the only thing that keeps a
    re-ingest from erasing it.

    ``cancelled`` is a zero-arg predicate polled *between* captures: a capture is never
    interrupted half-way, so the store is never left holding a partial session. ``ingest`` is
    injectable purely so the tests can drive the accounting without a real capture.
    """
    captures = capture_store.list_captures()
    total = len(captures)
    stored_before = session_store.stored_uids()
    rebuilt: set[int] = set()
    missing: list[str] = []
    errors: list[str] = []
    ingested = 0
    was_cancelled = False

    log.info("Re-ingest starting: %d captures, %d stored sessions", total, len(stored_before))
    for index, meta in enumerate(captures, start=1):
        if cancelled is not None and cancelled():
            was_cancelled = True
            log.info("Re-ingest cancelled at %d of %d captures", index - 1, total)
            break
        if on_progress is not None:
            on_progress(index, total, meta.file_name)

        path = resolve_capture_path(meta, captures_dir)
        if path is None:
            log.info("Re-ingest: no archive found for %s (last known path: %s)",
                     meta.file_name, meta.path)
            missing.append(meta.file_name)
            continue
        try:
            sessions = ingest(path, session_store, lap_store=lap_store,
                              capture_store=capture_store, recorded_by=meta.recorded_by)
        except Exception as exc:                    # one bad archive must not abort the whole pass
            log.exception("Re-ingest failed for %s", path)
            errors.append(f"{meta.file_name}: {exc}")
            continue
        rebuilt.update((int(s.session_uid) for s in sessions))
        ingested += 1

    summary = ReingestSummary(
        captures_total=total,
        captures_ingested=ingested,
        sessions_total=len(stored_before),
        sessions_rebuilt=len(rebuilt & stored_before),
        missing=tuple(missing),
        errors=tuple(errors),
        cancelled=was_cancelled,
    )
    log.info("Re-ingest finished: %s", summary)
    return summary
