"""The lap detail page - one lap's timing, tyre state, damage, setup and telemetry graphs.

Loads a single lap (with its dense trace) via ``LapStore.load`` and its owning session via
``SessionStore.load`` - the session gives the track/label and, through ``setup_for_lap``, the setup
active on that lap (setup is a per-session history, not per-lap). Composes the reusable components:
the lap-info + tyre box, the CarDamage table, the setup table, and the single-lap ``TracePlot``.
Any region whose data wasn't captured (older laps) is simply omitted.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget
)

from ...protocol.reference import track_name
from ..components import (
    TracePlot,
    TyreBox,
    build_damage_table,
    build_kv_table,
    build_setup_table,
    clear_layout,
)
from ..formatting import format_lap_time, slot_label


class DetailPage(QWidget):
    """One lap's full detail; emits ``overview_requested`` to go back (or if the lap vanished)."""

    overview_requested = Signal()

    def __init__(self, session_store, lap_store, parent=None):
        super().__init__(parent)
        self._sessions = session_store
        self._laps = lap_store

        outer = QVBoxLayout(self)
        header = QHBoxLayout()
        back = QPushButton("← Laps")
        back.clicked.connect(self.overview_requested.emit)
        self._title = QLabel()
        self._title.setStyleSheet("font-size: 18pt; font-weight: 600;")
        header.addWidget(back)
        header.addSpacing(12)
        header.addWidget(self._title)
        header.addStretch(1)
        outer.addLayout(header)

        self._body = QVBoxLayout()
        host = QWidget()
        host.setLayout(self._body)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

    def load(self, session_uid: str, lap_number: int) -> None:
        """Populate the page for one lap; falls back to the overview if it's gone."""
        uid = str(session_uid)
        clear_layout(self._body)
        lap = self._laps.load(uid, lap_number)
        if lap is None:
            self.overview_requested.emit()
            return
        session = self._sessions.load(uid)
        track = track_name(session.track_id) if session else "Unknown track"
        label = slot_label(session.session_type) if session else ""
        setup = session.setup_for_lap(lap_number) if session else None
        self._title.setText(
            f"Lap {lap.lap_number} — {track}" + (f" — {label}" if label else "")
        )

        # top: lap info + tyre box (left column), then damage and setup tables beside them
        columns = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(self._panel("Lap", build_kv_table(self._lap_info_rows(lap))))
        if lap.tyre_context is not None:
            left.addWidget(self._panel("Tyres", TyreBox(lap.tyre_context)))
        left.addStretch(1)
        left_host = QWidget()
        left_host.setLayout(left)
        columns.addWidget(left_host)
        if lap.damage is not None:
            columns.addWidget(self._panel("Damage", build_damage_table(lap.damage)))
        if setup is not None:
            columns.addWidget(self._panel("Setup", build_setup_table(setup)))
        columns.addStretch(1)
        cols_host = QWidget()
        cols_host.setLayout(columns)
        self._body.addWidget(cols_host)

        # bottom: single-lap telemetry graphs
        caption = QLabel("Telemetry")
        caption.setStyleSheet("font-weight: 600; margin-top: 8px;")
        self._body.addWidget(caption)
        if lap.trace is not None:
            plot = TracePlot(lap.trace)  # sizes itself to all its rows; the QScrollArea scrolls
            self._body.addWidget(plot)
        else:
            missing = QLabel("No telemetry trace stored for this lap")
            missing.setStyleSheet("color: palette(mid);")
            self._body.addWidget(missing)
        self._body.addStretch(1)

    @staticmethod
    def _panel(caption: str, widget: QWidget) -> QWidget:
        """A captioned, top-aligned column wrapping one widget."""
        panel = QWidget()
        box = QVBoxLayout(panel)
        box.setContentsMargins(0, 0, 0, 0)
        cap = QLabel(caption)
        cap.setStyleSheet("font-weight: 600;")
        box.addWidget(cap)
        box.addWidget(widget)
        box.addStretch(1)
        return panel
    
    @staticmethod
    def _lap_info_rows(lap) -> list[tuple[str, str]]:
        return [
            ("Lap time", format_lap_time(lap.lap_time_ms)),
            ("Sector 1", format_lap_time(lap.sector1_ms)),
            ("Sector 2", format_lap_time(lap.sector2_ms)),
            ("Sector 3", format_lap_time(lap.sector3_ms)),
            ("Valid", "Yes" if lap.is_valid else "No"),
        ]
