"""The lap detail page - one lap's timing, tyre state, damage, setup and telemetry graphs.

Loads a single lap (with its dense trace) via ``LapStore.load`` and its owning session via
``SessionStore.load`` - the session gives the track/label and, through ``setup_for_lap``, the setup
active on that lap (setup is a per-session history, not per-lap). Composes the reusable components:
the lap-info + tyre box, the CarDamage table, the setup table, and the single-lap ``TracePlot``.
Any region whose data wasn't captured (older laps) is simply omitted.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QVBoxLayout,
    QWidget
)

from ...protocol.reference import track_name
from ..components import (
    TracePlot,
    TyreBox,
    build_damage_table,
    build_setup_table,
    cell,
    clear_layout,
    fit_table_height,
    tidy_table
)
from ..components.tyres import tyre_pixmap
from ..formatting import format_lap_time, slot_label
from ..settings import set_trace_colorblind, trace_colorblind


class DetailPage(QWidget):
    """One lap's full detail; emits ``overview_requested`` to go back (or if the lap vanished)."""

    overview_requested = Signal()

    def __init__(self, session_store, lap_store, parent=None):
        super().__init__(parent)
        self._sessions = session_store
        self._laps = lap_store
        self._colorblind = trace_colorblind()  # throttle/brake palette reference, persisted
        self._plot: TracePlot | None = None

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

        # top: one compact lap-summary row (tyre+lap · sectors · lap time · valid), full width
        self._body.addWidget(self._lap_summary_row(lap))

        # beneath: tyre box, damage and setuo tables side by side
        columns = QHBoxLayout()
        if lap.tyre_context is not None:
            columns.addWidget(self._panel("Tyres", TyreBox(lap.tyre_context)))
        if lap.damage is not None:
            columns.addWidget(self._panel("Damage", build_damage_table(lap.damage)))
        if setup is not None:
            columns.addWidget(self._panel("Setup", build_setup_table(setup)))
        columns.addStretch(1)
        cols_host = QWidget()
        cols_host.setLayout(columns)
        self._body.addWidget(cols_host)

        # bottom: single-lap telemetry graphs, with a colour-blind palette toggle in the header
        caption_host = QWidget()
        caption_row = QHBoxLayout(caption_host)
        caption_row.setContentsMargins(0, 0, 0, 0)
        caption = QLabel("Telemetry")
        caption.setStyleSheet("font-weight: 600; margin-top: 8px;")
        caption_row.addWidget(caption)
        caption_row.addStretch(1)
        self._plot = None
        if lap.trace is not None:
            toggle = QCheckBox("Colour-blind palette")
            toggle.setChecked(self._colorblind)
            toggle.toggled.connect(self._on_colorblind_toggled)
            caption_row.addWidget(toggle)
        self._body.addWidget(caption_host)
        if lap.trace is not None:
            plot = TracePlot(lap.trace, colorblind=self._colorblind)    # sizes itself; QScrollArea scrolls
            self._plot = plot
            self._body.addWidget(plot)
        else:
            missing = QLabel("No telemetry trace stored for this lap")
            missing.setStyleSheet("color: palette(mid);")
            self._body.addWidget(missing)
        self._body.addStretch(1)

    def _on_colorblind_toggled(self, enabled: bool) -> None:
        """Persists the palette choice and recolour the live plot in place."""
        self._colorblind = enabled
        set_trace_colorblind(enabled)
        if self._plot is not None:
            self._plot.set_colorblind(enabled)

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
    def _lap_summary_row(lap) -> QWidget:
        """One compact row: tyre icon + lap time, the three sector times, the lap
        and whether the lap was valid.
        """
        headers = ["TYRE / LAP", "SECTOR 1", "SECTOR 2", "SECTOR 3", "LAP TIME", "VALID"]
        table = QTableWidget(1, len(headers))
        table.setHorizontalHeaderLabels(headers)
        tidy_table(table)

        tyre_cell = cell(f"Lap {lap.lap_number}")
        if lap.tyre_context is not None:
            pixmap = tyre_pixmap(lap.tyre_context.visual_compound, size=18)
            if pixmap is not None:
                tyre_cell.setIcon(QIcon(pixmap))
        table.setItem(0, 0, tyre_cell)

        values = [
            format_lap_time(lap.sector1_ms),
            format_lap_time(lap.sector2_ms),
            format_lap_time(lap.sector3_ms),
            format_lap_time(lap.lap_time_ms),
            "✓" if lap.is_valid else "✗"
        ]
        for col, text in enumerate(values, start=1):
            item = cell(text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(0, col, item)

        fit_table_height(table)
        return table