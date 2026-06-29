"""Background workers so the GUI never blocks om the network or parsing.

``RecordWorker``runs the capture loop on its own thread and is stoopped cooperatively via
the source's ``stop_event``. ``IngestWorker`` then runs parse -> assemble -> persists on its
own thread. Both report progress and completion through Qt signals, which Qt delivers to the GUI
thread; the heave pipeline imports live inside ``IngestWorker.run``so the app starts quickly
and only pulls them in when a capture is acutally proocessed.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from ..ingest.recorder import SessionRecorder
from ..ingest.sources import LiveUDPSource


class RecorderWorker(QThread):
    """Captures live UDP telemetry to a .f1cap file unitl asked to stop."""

    status = Signal(int, int, float)    # packet_count, byte_count, elapsed_seconds
    done = Signal(str, int)             # capture_path, packet_count
    failed = Signal(str)                # error message

    def __init__(self, output_path: str, host: str = "0.0.0.0", port: int = 20777, parent=None) -> None:
        """Initialize the capture worker thread."""
        super().__init__(parent)
        self._output_path = output_path
        self.host = host
        self.port = port
        self.stop_event = threading.Event()

    def run(self) -> None:
        """Capture loop; runs in its own thread."""
        try:
            source = LiveUDPSource(self.host, self.port, stop_event=self.stop_event)
            recorder = SessionRecorder(self._output_path, source)
            recorder.record(on_status=self._emit_status, status_interval=1.0)
            self.done.emit(self._output_path, recorder.packet_count)
        except Exception as exc:            # surface any failure to the UI rather than dying silently
            self.failed.emit(str(exc))

    def _emit_status(self, packets: int, byte_count:int, elapsed: float) -> None:
        """Emit a status update to the GUI thread."""
        self.status.emit(packets, byte_count, elapsed)

    def stop(self) -> None:
        """Ask the capture loop to finish; safe to call from the GUI thread."""
        self.stop_event.set()


class IngestWorker(QThread):
    """Parses a capture, assembles its sessions, and persists each to the store."""

    done = Signal(list)     # list[str] human readbale session descriptions
    failed = Signal(str)    # error message

    def __init__(self, capture_path: str, db_url: str, parent=None) -> None:
        """Initialize the ingest worker thread."""
        super().__init__(parent)
        self._capture_path = capture_path
        self._db_url = db_url

    def run(self) -> None:
        """ Run the parse -> assemble -> persist pipeline in its own thread.
        Heavy imports are done here so the app starts quickly and only pulls them in
        when a capture is actually processed.
        """
        from ..pipeline import ingest_capture
        from ..storage.repository import SessionStore

        try:
            store = SessionStore(self._db_url)
            sessions = ingest_capture(self._capture_path, store)
            self.done.emit([self._describe(s) for s in sessions])
        except Exception as exc:            # surface any failure to the UI rather than dying silently
            self.failed.emit(str(exc))
            

    @staticmethod
    def _describe(session) -> str:
        """Return a human-readable description of a session for the GUI."""
        stype = getattr(session.session_type, "name", session.session_type)
        return f"{stype} (uid {session.session_uid})"