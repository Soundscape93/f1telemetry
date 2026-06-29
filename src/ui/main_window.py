"""The application's entry-point window.

Intenionally minimal for now: one record/stop button and a status line. Recording runs on a
background thread so the UI remains responsive, The background thread stops cleanly from the button;
when it ends, the capture is automatically parsed, assembled, and persisted (the .f1cap is kept).
The season/results view will be added as further windows later.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .workers import IngestWorker, RecorderWorker

# Defaults; these become user settings later.
_CAPTURE_DIR = Path("captures")
_DB_URL = "sqlite:///f1league.db"
_HOST = "0.0.0.0"
_PORT = 20777


class MainWindow(QMainWindow):
    """The main window of the f1telemetry desktop UI."""
    def __init__(self) -> None:
        """Initialize the main window."""
        super().__init__()
        self.setWindowTitle("F1 Telemetry Viewer")
        self.resize(440, 220)

        self._recorder: RecorderWorker | None = None
        self._ingest: IngestWorker | None = None

        self._button = QPushButton("Record session(s)")
        self._button.setMinimumHeight(48)
        self._button.clicked.connect(self._on_button_clicked)

        self._status = QLabel("Idle")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addStretch(1)
        layout.addWidget(self._button)
        layout.addWidget(self._status)
        layout.addStretch(1)

        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

    
    # --- button / state machine ---
    def _on_button_clicked(self) -> None:
        if self._recorder is None:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self) -> None:
        _CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        path = str(_CAPTURE_DIR / f"{datetime.now():%Y%m%d_%H%M%S}.f1cap")

        self._recorder = RecorderWorker(path, host=_HOST, port=_PORT)
        self._recorder.status.connect(self._on_record_status)
        self._recorder.done.connect(self._on_record_done)
        self._recorder.failed.connect(self._on_failed)
        self._recorder.start()

        self._button.setText("Stop recording")
        self._status.setText(f"Recording - waiting for telemetry...")
        
    def _stop_recording(self) -> None:
        if self._recorder is not None:
            self._button.setEnabled(False)
            self._status.setText(f"Stopping...")
            self._recorder.stop()

    
    # --- recorder signals ---
    def _on_record_status(self, packets: int, byte_count: int, elapsed: float) -> None:
        kb = byte_count / 1024
        self._status.setText(f"Recording - {packets} packets, {kb:,.0f} KB, {elapsed:.0f}s")

    def _on_record_done(self, path: str, packet_count: int) -> None:
        worker, self._recorder = self._recorder, None
        if worker is not None:
            worker.wait()           # join the finished thread before releasing it

        if packet_count == 0:
            self._reset_button()
            self._status.setText(
                f"No packets captured: is the game sending telemetry to {_HOST}:{_PORT} ?"
            )
            return
        
        self._status.setText(f"Saved {packet_count} packets. Processing capture...")
        self._start_ingest(path)


        # --- ingest signals ---
    def _start_ingest(self, path: str) -> None:
        self._ingest = IngestWorker(path, _DB_URL)
        self._ingest.done.connect(self._on_ingest_done)
        self._ingest.failed.connect(self._on_failed)
        self._ingest.start()

    def _on_ingest_done(self, descriptions: list) -> None:
        worker, self._ingest = self._ingest, None
        if worker is not None:
            worker.wait()           # join the finished thread before releasing it

        self._reset_button()
        if descriptions:
            self._status.setText(
                f"Stored {len(descriptions)} session(s): " + ", ".join(descriptions)
            )
        else:
            self._status.setText("Capture saved, but no complete sesssions were found in it.")


        # --- shared ---
    def _on_failed(self, message: str) -> None:
        self._recorder = None
        self._ingest = None
        self._reset_button()
        self._status.setText(f"Error: {message}")

    def _reset_button(self) -> None:
        self._button.setText("Record session(s)")
        self._button.setEnabled(True)