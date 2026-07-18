"""The application's main window - a sidebar shell with the record control always in reach.

A single QMainWindow hosts everything: a slim header carrying the record/stop button and a 
status line (shown on every page, so a capture can be started or stopped without navigating
back), a left sidebar selecting the active section, and a stacked content area that swaps pages
in place rather than opening new windows. Recording still runs on a background thread and stops
cleanly; when it ends the capture is parsed, assembled, and persisted in a DB (the .f1cap is kept,
for later re-ingest if desired) and the status line shows what was stored.

Of the sibebar section, Seasons is the first view, the rest are placeholders for future work.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .workers import IngestWorker, RecorderWorker
from ..storage.seasons import SeasonStore
from ..storage.sessions import SessionStore
from ..storage.laps import LapStore
from .seasons import SeasonsView
from .laps import LapsView
from .style import MUTED_TEXT_QSS

# Defaults; these become user settings later.
_CAPTURE_DIR = Path("captures")
_DB_URL = "sqlite:///f1league.db"
_TRACE_DIR = "lap_traces"  # where each lap's dense Parquet trace is written
_HOST = "0.0.0.0"
_PORT = 20777

# sidebar sections, on order. Seasons is real; reast are placeholders for future work.
_SECTIONS = ["Dashboard", "Seasons", "Sessions", "Laps", "Analytics", "Help", "Bug report"]


class _PlaceholderPage(QWidget):
    """A placeholder page for a sidebar section that isn't implemented yet."""
    def __init__(self,  title: str, subtitle: str = "Coming soon", parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        heading = QLabel(title)
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading.setStyleSheet("font-size: 20px; font-weight: 600;")
        sub = QLabel(subtitle)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(MUTED_TEXT_QSS)
        layout.addWidget(heading)
        layout.addWidget(sub)
        layout.addStretch(1)


class MainWindow(QMainWindow):
    """The main window of the application, with a sidebar and a stacked content area."""
    def __init__(self) -> None:
        """Initialize the main window and its UI components."""
        super().__init__()
        self.setWindowTitle("F1 Telemetry")
        self.resize(900, 600)

        self._recorder: RecorderWorker | None = None
        self._ingest: IngestWorker | None = None

        # Stores the UI reads on the GUI thread. The IngestWorker keeps its own store on its
        # own thread (SQLite dislikes a connection shared across threads); these point to the
        # same database file.
        self._session_store = SessionStore(_DB_URL)
        self._season_store = SeasonStore(_DB_URL)
        # The UI reads laps/traces on the GUI thread from its own LapStore (same DB file and
        # trace_dir the IngestWorker writes to). Consumed by the Laps View; disposed on close.
        self._lap_store = LapStore(_DB_URL, trace_dir=_TRACE_DIR)

        self.setCentralWidget(self._build_central())

    # --- layout ------------------------------------------------------------

    def _build_central(self) -> QWidget:
        """Build the central widget with a header, sidebar, and stacked content area."""
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())
        root.addWidget(_line(QFrame.Shape.HLine))

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._sidebar = QListWidget()
        self._sidebar.addItems(_SECTIONS)
        self._sidebar.setFixedWidth(170)
        self._sidebar.setFrameShape(QFrame.Shape.NoFrame)
        self._sidebar.setStyleSheet("QListWidget::item { padding: 8px 4px; }")
        body.addWidget(self._sidebar)
        body.addWidget(_line(QFrame.Shape.VLine))

        self._stack = QStackedWidget()
        self._build_pages()
        body.addWidget(self._stack, 1)

        body_host = QWidget()
        body_host.setLayout(body)
        root.addWidget(body_host, 1)

        self._sidebar.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._sidebar.setCurrentRow(0)      # land on dashboard
        return central
    
    def _build_header(self) -> QWidget:
        """Build the header with a record button and a status label.
        The header is always visible, so a capture can be started or stopped from any page.
        """
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(12, 8, 12, 8)

        self._record_button = QPushButton("Record session(s)")
        self._record_button.setMinimumHeight(36)
        self._record_button.clicked.connect(self._on_button_clicked)

        # TEMP: dev-only button to ingest an existing .f1cap; remove before release.
        self._test_ingest_button = QPushButton("Ingest .f1cap (test)")
        self._test_ingest_button.setMinimumHeight(36)
        self._test_ingest_button.clicked.connect(self._on_test_ingest)

        self._status = QLabel("Idle")
        self._status.setWordWrap(True)

        layout.addWidget(self._record_button)
        layout.addWidget(self._test_ingest_button)
        layout.addSpacing(12)
        layout.addWidget(self._status, 1)
        return header
    
    def _build_pages(self) -> None:
        """Build the sidebar and the stacked content area with pages for each section."""
        self._seasons_view = SeasonsView(self._season_store, self._session_store)
        self._stack.addWidget(_PlaceholderPage(
            "Dashboard", "The recent sessions, laps, and analytics will be shown here."))
        self._stack.addWidget(self._seasons_view)
        self._stack.addWidget(_PlaceholderPage(
            "Sessions", "The sessions will be listed here, with details and lap times."))
        self._laps_view = LapsView(self._session_store, self._lap_store)
        self._stack.addWidget(self._laps_view)
        self._stack.addWidget(_PlaceholderPage(
            "Analytics", "The analytics will be shown here, with charts and graphs."))
        self._stack.addWidget(_PlaceholderPage(
            "Help", "The help and documentation will be shown here."))
        self._stack.addWidget(_PlaceholderPage(
            "Bug report", "The bug report form will be shown here."))
        
    # --- button / state machine ------------------------------------------------------------

    def _on_button_clicked(self) -> None:
        """Handle the record button click; start or stop recording depending on the current state."""
        if self._recorder is None:
            self._start_recording()
        else:
            self._stop_recording()

    def _on_test_ingest(self) -> None:
        """TEMP: pick an existing .f1cap and ingest it, to test storing a captured weekend."""
        if self._recorder is not None or self._ingest is not None:
            return
        start_dir = str(_CAPTURE_DIR) if _CAPTURE_DIR.exists() else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a .f1cap / .f1cap.gz to ingest", start_dir,
             "Captures (*.f1cap *.f1cap.gz);;All files (*)"
        )
        if not path:
            return
        self._record_button.setEnabled(False)
        self._test_ingest_button.setEnabled(False)
        self._status.setText(f"Ingesting {Path(path).name} ...")
        self._start_ingest(path)

    def _start_recording(self) -> None:
        """Start recording live telemetry to a .f1cap file in the captures directory."""
        _CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        path = str(_CAPTURE_DIR / f"{datetime.now():%Y%m%d_%H%M%S}.f1cap")

        self._recorder = RecorderWorker(path, host=_HOST, port=_PORT)
        self._recorder.status.connect(self._on_record_status)
        self._recorder.done.connect(self._on_record_done)
        self._recorder.failed.connect(self._on_failed)
        self._recorder.start()

        self._record_button.setText("Stop recording")
        self._status.setText(f"Recording - waiting for telemetry ...")

    def _stop_recording(self) -> None:
        """Stop recording live telemetry; the RecorderWorker will finish and emit a done signal."""
        if self._recorder is not None:
            self._record_button.setEnabled(False)
            self._status.setText("Stopping recording ...")
            self._recorder.stop()

    def _on_record_status(self, packets: int, byte_count: int, elapsed: float) -> None:
        """Update the status label with the current recording progress."""
        kb = byte_count / 1024
        self._status.setText(f"Recording - {packets} packets, {kb:.0f} KB, {elapsed:.0f}s")

    def _on_record_done(self, path: str, packet_count: int) -> None:
        """Handle the RecorderWorker's done signal; start ingesting the capture."""
        worker, self._recorder = self._recorder, None
        if worker is not None:
            worker.wait()  # ensure the thread has finished before deleting it

        if packet_count == 0:
            self._reset_button()
            self._status.setText(
                f"No packets captured - check that the game is running and sending telemetry to {_HOST}:{_PORT} ( set UDP to Broadcast for 0.0.0.0).")
            return
        
        self._status.setText(f"Saved {packet_count} packets. Processing capture ...")
        self._start_ingest(path)

    def _start_ingest(self, capture_path: str) -> None:
        """Start ingesting the capture file in a background thread."""
        self._ingest = IngestWorker(capture_path, _DB_URL, trace_dir=_TRACE_DIR)
        self._ingest.done.connect(self._on_ingest_done)
        self._ingest.failed.connect(self._on_failed)
        self._ingest.start()

    def _on_ingest_done(self, descriptions: list, archive_path: str, archive_error: str) -> None:
        """Handle the IngestWorker's done signal; update the status and refresh the seasons view."""
        worker, self._ingest = self._ingest, None
        if worker is not None:
            worker.wait()  # ensure the thread has finished before deleting it
        
        self._reset_button()
        if descriptions:
            message = f"Stored {len(descriptions)} session(s): " + " ".join(descriptions)
        else:
            message = "Capture saved, but no complete session(s) found."
        if archive_path:
            message += f"Archived capture to {Path(archive_path).name}."
        elif archive_error:
            message += f"Capture kept uncompressed: {archive_error}"
        self._status.setText(message)

        # a freshly-stored session may be on an open surface; refresh whichever is showing.
        current = self._stack.currentWidget()
        if current is self._seasons_view:
            self._seasons_view.refresh()
        elif current is self._laps_view:
            self._laps_view.refresh()

    def _on_failed(self, message: str) -> None:
        """Handle a failure from either the RecorderWorker or IngestWorker; reset the button and show the error."""
        self._recorder = None
        self._ingest = None
        self._reset_button()
        self._status.setText(f"Error: {message}")

    def _reset_button(self) -> None:
        """Reset the record button to its initial state."""
        self._record_button.setText("Record session(s)")
        self._record_button.setEnabled(True)
        self._test_ingest_button.setEnabled(True)  # TEMP: remove with the test button

    # --- shutdown ------------------------------------------------------------

    def closeEvent(self, event) -> None:
        """Handle the window close event; stop any running workers and close the stores."""
        if self._recorder is not None:
            self._recorder.stop()
            self._recorder.wait()
        if self._ingest is not None:
            self._ingest.wait()
        self._session_store.close()
        self._season_store.close()
        self._lap_store.close()
        super().closeEvent(event)


def _line(shape: QFrame.Shape) -> QFrame:
    """Create a horizontal or vertical line for separating sections of the UI."""
    line = QFrame()
    line.setFrameShape(shape)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line
