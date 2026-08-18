"""The laps overview - foldable per-session cards over the player's stored laps.

One collapsible card per captured session that has stored laps (newest first): the header shows
the track and session label, with the lap-count / best lap / recorded-time meta line: expanding
reveals that session's laps (number, time, tyre, validity), and double-clicking a lap opens its
detail. A search box filters cards by track / session label, and a checkbox limits to valid laps.

Laps are listed cheaply via ``LapStore.list`` (DB rows only, no Parquet traces); the detail page
hydrates a single lap's trace on demand.
"""
from __future__ import annotations

from datetime import datetime
from functools import partial

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QTableWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...domain.season import slot_for_session
from ...protocol.reference import track_name
from ..components import cell, clear_layout, fit_table_height, tidy_table
from ..components.tyres import tyre_pixmap
from ..formatting import format_lap_time, slot_label
from ..style import MUTED_TEXT_QSS, apply_bold, apply_heading


def _recorded_label(recorded_at: datetime | None) -> str:
    """Local-time 'YYYY-MM-DD HH:MM' for a recorded_at (UTC-aware -> local), or en em dash."""
    if recorded_at is None:
        return "—"
    if recorded_at.tzinfo is not None:
        recorded_at = recorded_at.astimezone()
    return recorded_at.strftime("%Y-%m-%d %H:%M")


class OverviewPage(QWidget):
    """Foldable per-session lap cards with a track/sessiion filter."""

    lap_requested = Signal(str, int)  # session_uid (str, uint64-safe), lap_number

    def __init__(self, session_store, lap_store, parent=None):
        super().__init__(parent)
        self._sessions = session_store
        self._laps = lap_store
        self._expanded: set[str] = set()  # uids whose card is opne (survives a re-filter)
        self._query = ""
        self._valid_only = False

        outer = QVBoxLayout(self)

        title = QLabel("Laps")
        apply_heading(title, size_px=20)
        outer.addWidget(title)

        controls = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter by track or session")
        self._search.textChanged.connect(self._on_search)
        controls.addWidget(self._search, 1)
        valid = QCheckBox("Valid laps only")
        valid.toggled.connect(self._on_valid_toggle)
        controls.addWidget(valid)
        outer.addLayout(controls)

        self._body = QVBoxLayout()
        host = QWidget()
        host.setLayout(self._body)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

    # --- filters ---------------------------------------------------------
    def _on_search(self, text: str) -> None:
        self._query = text.strip().lower()
        self.reload()

    def _on_valid_toggle(self, checked: bool) -> None:
        self._valid_only = checked
        self.reload()

    # --- build -----------------------------------------------------------
    def reload(self) -> None:
        """Rebuild the cards from the stores, honouring the current filter."""
        clear_layout(self._body)
        all_sessions = self._sessions.list_sessions()
        shown = 0
        for session in all_sessions:
            uid = str(session.session_uid)
            laps = self._laps.list(uid)
            if self._valid_only:
                laps = tuple(lap for lap in laps if lap.is_valid)
            if not laps:
                continue
            slot = slot_for_session(session, all_sessions)
            label = slot_label(slot.session_type, slot.is_sprint_race)
            track = track_name(session.track_id)
            if self._query and self._query not in f"{track} {label}".lower():
                continue
            self._body.addWidget(self._session_card(session, uid, track, label, laps))
            shown += 1
        if shown == 0:
            empty = QLabel(self._empty_message())
            empty.setStyleSheet(MUTED_TEXT_QSS)
            self._body.addWidget(empty)
        self._body.addStretch(1)

    def _empty_message(self) -> str:
        if self._query or self._valid_only:
            return "No laps match the filter."
        return "No laps stored yet - record or ingest a session with the player driving."
    
    def _session_card(self, session, uid, track, label, laps) -> QWidget:
        """A collapsible card for a session with its laps."""
        card = QFrame()
        vbox = QVBoxLayout(card)
        vbox.setContentsMargins(0, 0, 0, 0)

        best = min((lap.lap_time_ms for lap in laps if lap.lap_time_ms), default=None)
        header = QHBoxLayout()
        toggle = QToolButton()
        toggle.setCheckable(True)
        toggle.setChecked(uid in self._expanded)
        toggle.setText(f"{track} — {label}")
        toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toggle.setArrowType(
            Qt.ArrowType.DownArrow if toggle.isChecked() else Qt.ArrowType.RightArrow
        )
        # No stylesheet - it would freeze the button's text colour at apply time (A4b).
        # border: name -> setAutoRaise, font-weight: 600 -> apply_bold, padding -> minimum height.
        toggle.setAutoRaise(True)
        apply_bold(toggle)
        toggle.setMinimumHeight(toggle.sizeHint().height() + 4)
        toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        header.addWidget(toggle)
        header.addStretch(1)

        count = f"{len(laps)} lap" + ("s" if len(laps) != 1 else "")
        best_str = f"  ·  best {format_lap_time(best)}" if best else ""
        meta = QLabel(f"{count}{best_str}  ·  {_recorded_label(session.recorded_at)}")
        meta.setStyleSheet(MUTED_TEXT_QSS)
        header.addWidget(meta)
        vbox.addLayout(header)

        table = self._lap_table(uid, laps)
        table.setVisible(toggle.isChecked())
        toggle.toggled.connect(partial(self._toggle_card, uid, table, toggle))
        vbox.addWidget(table)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        vbox.addWidget(line)
        return card
    
    def _toggle_card(self, uid: str, table: QTableWidget, toggle: QToolButton, expanded: bool) -> None:
        table.setVisible(expanded)
        toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        if expanded:
            self._expanded.add(uid)
        else:
            self._expanded.discard(uid)

    def _lap_table(self, uid: str, laps) -> QTableWidget:
        columns = ["LAP", "TIME", "TYRE", "VALID"]
        table = QTableWidget(len(laps), len(columns))
        table.setHorizontalHeaderLabels(columns)
        tidy_table(table)
        table.setIconSize(QSize(22, 22))
        table.setToolTip("Double-click a lap to open its telemetry detail.")
        for i, lap in enumerate(laps):
            lap_item = cell(str(lap.lap_number))
            lap_item.setData(Qt.ItemDataRole.UserRole, lap.lap_number)
            table.setItem(i, 0, lap_item)
            table.setItem(i, 1, cell(format_lap_time(lap.lap_time_ms)))
            tyre_item = cell("")
            pixmap = tyre_pixmap(lap.tyre_context.visual_compound) if lap.tyre_context else None
            if pixmap is not None:
                tyre_item.setIcon(QIcon(pixmap))
            table.setItem(i, 2, tyre_item)
            table.setItem(i, 3, cell("✓" if lap.is_valid else "✗"))
        fit_table_height(table)
        table.cellDoubleClicked.connect(partial(self._open_lap, uid, table))
        return table
    
    def _open_lap(self, uid: str, table: QTableWidget, row: int, _col: int) -> None:
        item = table.item(row, 0)
        if item is not None:
            self.lap_requested.emit(uid, item.data(Qt.ItemDataRole.UserRole))
