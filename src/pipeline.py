"""Application-level orchestration: turn a capture file into stored sessions.

`ìngest_capture`` is the parse -> assemble -> persist path that the recording UI runs after
a capture and that the integration test runs against a fixture. It's a plain function (no Qt)
so it can be tested directly; the GUI's ``IngestWorker``is a thin wrapper that calls it on a
background thread and reports the result through signals.
"""

from __future__ import annotations

from collections.abc import Iterator

from .domain.models import SessionResult
from .ingest.sources import FileReplaySource
from .protocol.parser import PacketParser
from .protocol.registry import build_registry
from .session.assembler import assemble
from .storage.repository import SessionStore


def ingest_capture(capture_path: str, store: SessionStore) -> list[SessionResult]:
    """Parse a .f1cap file, assemble its sessions, persist each, and return what was stored.
    
    A single capture can contain several sessions, (multiple weekends and/or multiple sessions),
    so this returns a list - one ``SessionResult`` per session the assembler emitted. The Store
    is passed in (not constructed here) so callers control its lifetime and, for SQLite, the
    thread it lives on.
    """
    parser = PacketParser(build_registry())

    def parsed() -> Iterator:
        for raw in FileReplaySource(capture_path, realtime=False):
            packet = parser.parse(raw)
            if packet is not None:
                yield packet

    saved: list[SessionResult] = []
    for session in assemble(parsed()):
        store.save(session)
        saved.append(session)
    return saved