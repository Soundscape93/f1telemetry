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
        """Capture loop; runs in its own thread.
        The stay-awake request belongs here rather than in the recorder: SetThreadExecutionState
        is per-thread, so it has to be asserted on the thread that actually blocks in recvfrom.
        """
        try:
            from ..keep_awake import keep_awake
            source = LiveUDPSource(self.host, self.port, stop_event=self.stop_event)
            recorder = SessionRecorder(self._output_path, source)
            with keep_awake():
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


class ReingestWorker(QThread):
    """Rebuilds every stored session from its archived capture, off the GUI thread.

    The Phase-2 counterpart of ``IngestWorker`` and built the same way: its stores are created
    on THIS thread (SQLite dislikes a connection shared across threads) and disposed in a single
    ``finally``, and the heavy pipeline imports live inside ``run`` so they stay out of start-up.

    A pass takes minutes on a real weekend, so it is cooperatively cancellable through
    ``stop_event`` - polled between captures by ``reingest_all``, never mid-capture.
    """

    progress = Signal(int, int, str)  # capture index (1-based), total, capture file name
    done = Signal(object)             # pipeline.ReingestSummary
    failed = Signal(str)                # error message

    def __init__(self, db_url: str, *, trace_dir: str = "lap_traces",
                 captures_dir: str = "", parent=None) -> None:
        super().__init__(parent)
        self._db_url = db_url
        self._trace_dir = trace_dir
        self._captures_dir = captures_dir
        self.stop_event = threading.Event()

    def cancel(self) -> None:
        """Ask the pass to stop after the capture it's on; safe from the GUI thread."""
        self.stop_event.set()

    def run(self) -> None:
        from ..pipeline import reingest_all
        from ..storage.captures import CaptureStore
        from ..storage.laps import LapStore
        from ..storage.meta import MetaStore
        from ..storage.sessions import SessionStore
        from ..version import PIPELINE_VERSION

        store = lap_store = capture_store = meta_store = None
        try:
            store = SessionStore(self._db_url)
            lap_store = LapStore(self._db_url, trace_dir=self._trace_dir)
            capture_store = CaptureStore(self._db_url)
            meta_store = MetaStore(self._db_url)
            summary = reingest_all(
                capture_store, store,
                lap_store=lap_store,
                captures_dir=self._captures_dir,
                on_progress=self.progress.emit,
                cancelled=self.stop_event.is_set,
            )
            # Only a clean, complete pass moves the stamp: a cancelled or failed one leaves the
            # database on the old version, so the offer comes back next launch. Missing archives
            # don't count as failure - see ReingestSummary.is_complete.
            if summary.is_complete:
                meta_store.set_pipeline_version(PIPELINE_VERSION)
            self.done.emit(summary)
        except Exception as exc:            # surface any failure to the UI rather than dying silently
            self.failed.emit(str(exc))
        finally:
            for s in (meta_store, capture_store, lap_store, store):
                if s is not None:
                    s.close()
