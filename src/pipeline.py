"""Application-level orchestration: turn a capture file into stored sessions.

`ìngest_capture`` is the parse -> assemble -> persist path that the recording UI runs after
a capture and that the integration test runs against a fixture. It's a plain function (no Qt)
so it can be tested directly; the GUI's ``IngestWorker``is a thin wrapper that calls it on a
background thread and reports the result through signals.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timezone

from .domain.captures import CaptureMeta
from .domain.models import SessionResult
from .ingest.archive import (HashingReader, archive_capture, capture_codec,
                                is_compressed_capture, open_capture)
from .ingest.recording import read_header, read_packet
from .protocol.parser import PacketParser
from .protocol.registry import build_registry
from .session.assembler import assemble
from .storage.sessions import SessionStore


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
