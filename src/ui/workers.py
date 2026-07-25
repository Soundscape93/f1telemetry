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

    done = Signal(list, str, str)  # list[str] human readable session descriptions, archive path, archive error
    failed = Signal(str)    # error message

    def __init__(self, capture_path: str, db_url: str, trace_dir: str = "lap_traces",
                 parent=None) -> None:
        """Initialize the ingest worker thread.
        
        ``trace_dir``is where each lap's dense Parquet trace is written (as a
        ``<session_uid>/lap_<n>.parquet`` tree beneath it); it defaults to ``lap_traces`` at
        CWD, a sibling of ``captures/`` and ``rosters/``.
        """
        super().__init__(parent)
        self._capture_path = capture_path
        self._db_url = db_url
        self._trace_dir = trace_dir
    
    def run(self) -> None:
        """Archive, ingest, and persist the capture on this thread (see pipeline.archive_and_ingest).

        Each store owns its connection on THIS thread - SQLite dislikes a connection shared across
        threads, and the LapStore writes each lap's Parquet trace under trace_dir. Heavy imports
        live here so the app starts quickly and only pulls them in when a capture is processed.
        """
        from ..pipeline import archive_and_ingest
        from ..storage.captures import CaptureStore
        from ..storage.laps import LapStore
        from ..storage.sessions import SessionStore

        # Each store owns its own engine on THIS thread; a single finally disposes all three,
        # wether ingest succeeded, failed, or a later store failed to construct (None = never built).
        store = lap_store = capture_store = None
        try:
            store = SessionStore(self._db_url)
            lap_store = LapStore(self._db_url, trace_dir=self._trace_dir)
            capture_store = CaptureStore(self._db_url)
            sessions, archive_path, archive_error = archive_and_ingest(
                self._capture_path, store,
                lap_store=lap_store, capture_store=capture_store
            )
            self.done.emit([self._describe(s) for s in sessions], archive_path, archive_error)
        except Exception as exc:            # surface any failure to the UI rather than dying silently
            self.failed.emit(str(exc))
        finally:
            for s in (capture_store, lap_store, store):
                if s is not None:
                    s.close()

    @staticmethod
    def _describe(session) -> str:
        """Return a human-readable description of a session for the GUI."""
        stype = getattr(session.session_type, "name", session.session_type)
        return f"{stype} (uid {session.session_uid})"


class UpdateCheckWorker(QThread):
    """Runs the GitHub Releases check off the GUI thread; emits one results object.
    
    The network + pasring live in ``update_check.check_for_update`` (imported lazily so the app
    start-up path never imports urllib). That function never raises; the try/except here is a
    final guard so a worker failure still surfaces a calm result rather than a silent thread.
    """
    
    result_ready = Signal(object)  # update_check.CheckResult

    def __init__(self, current_version: str, parent=None) -> None:
        super().__init__(parent)
        self._current_version = current_version
    
    def run(self) -> None:
        from ..update_check import check_for_update, UpdateCheckResult, CheckStatus
        try:
            result = check_for_update(self._current_version)
        except Exception:
            result = UpdateCheckResult(
                CheckStatus.ERROR, message="Could not check for updates right now. Please try again later.")
        self.result_ready.emit(result)