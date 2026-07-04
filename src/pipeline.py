"""Application-level orchestration: turn a capture file into stored sessions.

`ìngest_capture`` is the parse -> assemble -> persist path that the recording UI runs after
a capture and that the integration test runs against a fixture. It's a plain function (no Qt)
so it can be tested directly; the GUI's ``IngestWorker``is a thin wrapper that calls it on a
background thread and reports the result through signals.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timezone

from .domain.models import SessionResult
from .ingest.archive import open_capture
from .ingest.recording import read_header, read_packet
from .protocol.parser import PacketParser
from .protocol.registry import build_registry
from .session.assembler import assemble
from .storage.sessions import SessionStore


def ingest_capture(capture_path: str, store: SessionStore) -> list[SessionResult]:
    """Parse a .f1cap file, assemble its sessions, persist each, and return what was stored.

    A single capture can contain several sessions, (multiple weekends and/or multiple sessions),
    so this returns a list - one ``SessionResult`` per session the assembler emitted. The Store
    is passed in (not constructed here) so callers control its lifetime and, for SQLite, the
    thread it lives on.

    Each session is stamped with ``recorded_at`` = the wall-clock time of its *earliest* packet
    (the capture's per-packet ``recv_time``), so two attempts of the same session driven within
    one recording get distinct, chronological timestamps. We read the capture directly here
    rather than via ``FileReplaySource`` because we need each packet's ``recv_time``, which that
    source drops.
    """
    parser = PacketParser(build_registry())
    earliest: dict[int, float] = {}     # session_uid -> earliest recv_time seen

    def parsed() -> Iterator:
        with open_capture(capture_path) as f:
            read_header(f)
            while (record := read_packet(f)) is not None:
                packet = parser.parse(record.data)
                if packet is None:
                    continue
                uid = packet.header.session_uid
                if uid and record.recv_time < earliest.get(uid, float("inf")):
                    earliest[uid] = record.recv_time    # uid==0 is init noise, ignored downstream
                yield packet

    saved: list[SessionResult] = []
    for session in assemble(parsed()):
        recv_time = earliest.get(session.session_uid)
        if recv_time is not None:
            session = replace(
                session, recorded_at=datetime.fromtimestamp(recv_time, timezone.utc)
            )
        store.save(session)
        saved.append(session)
    return saved