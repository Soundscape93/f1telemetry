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
    QMenu,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QToolButton,
    QVBoxLayout,
    QWidget
)

from ...protocol.reference import track_name
from ..components import (
    CarStatusGraphic,
    TracePlot,
    TrackMap,
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
from ..style import MUTED_TEXT_QSS, apply_bold, apply_font, apply_heading
from .comparison import (
    SCOPE_BEST,
    SCOPE_SESSION,
    SCOPE_WEEKEND,
    best_lap_label,
    candidate_laps,
)
from .track_layout import TrackLayoutProvider

_MAX_COMPARE = 5    # base lap + up to this many overlaid laps (kept ≤ TracePlot's palette)


class DetailPage(QWidget):
    """One lap's full detail; emits ``overview_requested`` to go back (or if the lap vanished)."""

    overview_requested = Signal()

    def __init__(self, session_store, lap_store, parent=None):
        super().__init__(parent)
        self._sessions = session_store
        self._laps = lap_store
        self._layouts = TrackLayoutProvider(session_store, lap_store)
        self._current_uid: str | None = None            # the lap on screen, for reload()
        self._colorblind = trace_colorblind()  # colorblind reference, persisted
        self._plot: TracePlot | None = None
        self._base_trace = None
        self._base_lap_number: int | None = None
        self._base_label = ""
        self._compare_actions: list = []        # checkable menu actions carrying LapRefs

        outer = QVBoxLayout(self)
        header = QHBoxLayout()
        back = QPushButton("← Laps")
        back.clicked.connect(self.overview_requested.emit)
        self._title = QLabel()
        apply_heading(self._title, size_px=18)
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
            self._current_uid = None
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

        # beneath: left column = tyre box + car-status graphic (visual overview);
        # right = the exact-number damage + setup tables
        columns = QHBoxLayout()
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        if lap.tyre_context is not None or lap.damage is not None:
            graphic = CarStatusGraphic()
            graphic.set_lap(lap.tyre_context, lap.damage)
            left.addWidget(self._car_status_panel(graphic, lap.tyre_context, lap.fuel_in_tank))
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
        
        # bottom: telemetry graphs, with a compare picker + colour-blind toggle in the header
        self._base_trace = lap.trace
        self._base_lap_number = lap.lap_number
        self._base_label = best_lap_label(self._sessions, uid, lap.lap_number)
        self._compare_actions = []
        self._plot = TracePlot(lap.trace, colorblind=self._colorblind) if lap.trace is not None else None
        if self._plot is not None and session is not None:
            self._plot.set_sectors(session.sector2_start_m, session.sector3_start_m)

        # track map: only when this lap carries Motion; hover on the traces moves its marker.
        # Prefer the canonical median line for the whole weekend; fall back to this lap's own
        # line when the weekend has to few Motion laps to build a stable median.
        if lap.trace is not None and lap.trace.has_motion:
            track_map = TrackMap()
            if session is not None:
                track_map.set_sectors(session.sector2_start_m, session.sector3_start_m)
            layout = self._layouts.layout_for(uid)
            if layout is not None:
                track_map.set_layout(layout)
            else:
                track_map.set_trace(lap.trace)
            self._body.addWidget(self._panel("Track Map", track_map))
            if self._plot is not None:
                self._plot.cursor_moved.connect(track_map.set_cursor_distance)

        caption_host = QWidget()
        caption_row = QHBoxLayout(caption_host)
        caption_row.setContentsMargins(0, 0, 0, 0)
        caption = QLabel("Telemetry")
        apply_bold(caption)
        caption.setContentsMargins(0, 0, 0, 0)
        caption_row.addWidget(caption)
        if lap.trace is not None:
            compare = self._build_compare_menu(uid, lap)
            if compare is not None:
                caption_row.addSpacing(12)
                caption_row.addWidget(compare)
        caption_row.addStretch(1)
        if lap.trace is not None:
            toggle = QCheckBox("Colour-blind palette")
            toggle.setChecked(self._colorblind)
            toggle.toggled.connect(self._on_colorblind_toggled)
            caption_row.addWidget(toggle)
        self._body.addWidget(caption_host)

        if self._plot is not None:
            self._body.addWidget(self._plot)       # sizes itself; the QScrollArea scrolls
        else:
            missing = QLabel("No telemetry trace stored for this lap.")
            missing.setStyleSheet(MUTED_TEXT_QSS)
            self._body.addWidget(missing)
        self._body.addStretch(1)

    def invalidate_layouts(self) -> None:
        """Forget the cached canonical track maps; the next lap rebuilds them (PRIORITIES -> ALL)."""
        self._layouts.invalidate()

    def reload(self) -> None:
        """Re-render the lap currently on screen, if any. No-op before the first load()."""
        if self._current_uid is not None and self._base_lap_number is not None:
            self.load(self._current_uid, self._base_lap_number)

    def _on_colorblind_toggled(self, enabled: bool) -> None:
        """Persists the palette choice and recolour the live plot in place."""
        self._colorblind = enabled
        set_trace_colorblind(enabled)
        if self._plot is not None:
            self._plot.set_colorblind(enabled)

    def _build_compare_menu(self, uid: str, lap) -> QWidget | None:
        """A 'Compare ▾' button whose checkable menu lists laps to overlay, or None if there are none.
        
        Candidates come from ``comparison.candidate_laps`` grouped by scope (best / same session / weekend):
        ticking any extras rebuilds the overlay via ``_on_compare_changed``.
        """
        groups = candidate_laps(self._sessions, self._laps, uid, lap.lap_number)
        if not groups:
            return None
        button = QToolButton()
        button.setText("Compare ▾")
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        # No stylesheet - it would freeze the button's text colour at apply time (A4b).
        # The old "padding: 2px 6px" becomes a minimum size off the natural hint.
        button.setMinimumSize(button.sizeHint().width() + 12, button.sizeHint().height() + 4)
        menu = QMenu(button)
        self._compare_actions = []
        for scope in (SCOPE_BEST, SCOPE_SESSION, SCOPE_WEEKEND):
            refs = groups.get(scope)
            if not refs:
                continue
            menu.addSection(scope)
            for ref in refs:
                action = menu.addAction(ref.label)
                action.setCheckable(True)
                action.setData(ref)
                action.toggled.connect(self._on_compare_changed)
                self._compare_actions.append(action)
        button.setMenu(menu)
        return button
    
    def _on_compare_changed(self, checked: bool = False) -> None:
        """Reload the plot from the base lap plus every ticked comparison lap (or single if none)."""
        if self._plot is None or self._base_trace is None:
            return
        refs = [a.data() for a in self._compare_actions if a.isChecked()][:_MAX_COMPARE]
        if not refs:
            self._plot.set_trace(self._base_trace)
            return
        traces = [self._base_trace]
        labels = [self._base_label]
        for ref in refs:
            other = self._laps.load(ref.session_uid, ref.lap_number)
            if other is None or other.trace is None:
                continue
            traces.append(other.trace)
            labels.append(ref.label)
        self._plot.set_traces(traces, labels)

    @staticmethod
    def _panel(caption: str, widget: QWidget) -> QWidget:
        """A captioned, top-aligned column wrapping one widget."""
        panel = QWidget()
        box = QVBoxLayout(panel)
        box.setContentsMargins(0, 0, 0, 0)
        cap = QLabel(caption)
        apply_bold(cap)
        box.addWidget(cap)
        box.addWidget(widget)
        box.addStretch(1)
        return panel
    
    @staticmethod
    def _car_status_panel(graphic: QWidget, tyre_context, fuel_in_tank: float | None) -> QWidget:
        """The Car Status column: a caption row (title + compound icon + tyre age + fuel), then the
        car-status graphic. Age and fuel are per-lap boundary state; ``fuel_in_tank`` is the tank mass
        at lap start, shwon as "-" when the lap predates fuel capture (re-ingest to populate)."""
        panel = QWidget()
        box = QVBoxLayout(panel)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        cap = QLabel("Car Status")
        apply_bold(cap)
        head.addWidget(cap)
        if tyre_context is not None:
            pixmap = tyre_pixmap(tyre_context.visual_compound, size=16)
            if pixmap is not None:
                icon = QLabel()
                icon.setPixmap(pixmap)
                head.addWidget(icon)
            age = tyre_context.age_laps
            age_label = QLabel(f"{age} lap{'s' if age != 1 else ''} old")
            apply_font(age_label, size_px=11)
            head.addWidget(age_label)
        fuel_text = f"{fuel_in_tank:.1f} kg" if fuel_in_tank is not None else "—"
        prefix = "· Fuel: " if tyre_context is not None else "Fuel: "
        fuel_label = QLabel(prefix + fuel_text)
        apply_heading(fuel_label, size_px=11)
        head.addWidget(fuel_label)
        head.addStretch(1)
        box.addLayout(head)

        box.addWidget(graphic)
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