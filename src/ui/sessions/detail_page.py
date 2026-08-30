"""The session detail page - what one session was, how it finished, and how it was driven.

Five boxes over the shared classification builder: a 4x2 details grid and the final
classification side by side, the player's laps and any penalties below them, and (branch 2c) the
stacked pace / tyre-life charts under that.

Three things here are data-honesty rules rather than layout, and each is enforced in the Qt-free
``formatting`` helpers so they stay testable: points are shown only for races because the stored
value is a stale championship figure on every other session type; laps completed comes from the
classification rather than the stored lap rows, which can be short; and the penalties box has a
separate state for "penalties happened but we don't store their detail" so it never claims a
penalised session was clean.

The classification table is ``components.build_classification_table``, the same builder the
weekend page uses - this page must never grow a second one. A lap row emits upward rather than
reaching for the Laps surface itself: pages never reference siblings, so the hop to a lap's
telemetry goes through ``SessionsView`` to ``MainWindow`` (PRIORITIES -> A1).
"""
from __future__ import annotations

from functools import partial

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ... import paths
from ...domain.season import slot_for_session
from ...pipeline import resolve_capture_path
from ...protocol.reference import track_name
from ..components import (
    WeatherIcon,
    TrackMap,
    build_classification_table,
    build_pair_grid,
    cell,
    clear_layout,
    confirm_and_delete,
    fit_table_height,
    tidy_table,
)
from ..components.tyres import tyre_pixmap
from ..formatting import (
    format_lap_time,
    format_penalty_badge,
    is_race,
    lap_gap_label,
    laps_completed_label,
    player_best_lap_ms,
    player_points_label,
    recorded_label,
    session_best_lap_ms,
    session_context_label,
    slot_label,
)
from ..style import (
    FASTEST_LAP,
    FASTEST_LAP_QSS,
    MUTED_TEXT,
    MUTED_TEXT_QSS,
    PERSONAL_BEST,
    apply_bold,
    apply_heading
)
from .lap_context import analyse_session
from .stint_charts import StintCharts

_MID_ROW_MAX_H = 500            # the Laps / Penalties row is capped; those two boxes scroll inside it
_LAPS_TABLE_MAX_H = 440         # _MID_ROW_MAX_H less the box's heading and margins
_ICON_SIZE = QSize(22, 22)          # the Laps box's compound icon, same as the laps overview
_TRACK_MAP_MIN_H = 160          # enough for the outline to read at a glance, not enough to dominate
_NO_STINTS = ("No tyre stint ran long enough to chart — a stint needs at least two laps on one set "
              "of tyres.")
# Stated, never silently corrected for. A stint-relative overlay conflates tyre degradation with
# fuel burn-off, and the shared axis puts that difference exactly where a reader will credit it to
# the tyre. A correction needs a track- and car-dependent kg->seconds coefficient, so picking one
# here would swap an honest raw number for a confident estimate on a page whose job is "what
# actually happened". Fuel-corrected lap time is an Analytics (E3) item (DECISIONS -> UI).
_FUEL_CAVEAT = ("Observed lap times, not tyre performance: the car sheds roughly 1.1–1.3 kg of fuel "
                "a lap, so a later stint is partly quicker because it is lighter, not only because "
                "of the compound or the tyre's condition. No fuel correction is applied here. "
                "The scale holds the closest 8 seconds to your fastest racing lap — laps into and "
                "out of the pits are left out of it — so anything slower draws clipped at the top "
                "edge; hover it for the real time. Each run's average leaves out the same laps, "
                "plus a race's standing start, so it is the pace of the run rather than of the "
                "stop; an incident lap still counts, because nothing stored says it was one.")


class DetailPage(QWidget):
    """One captured session: what it was, where it came from, and how it finished."""

    overview_requested = Signal()
    sessions_changed = Signal()
    lap_requested = Signal(str, int)  # session_uid (str, uint64-safe), lap_number

    def __init__(self, session_store, season_store, capture_store=None, lap_store=None, parent=None):
        super().__init__(parent)
        self._sessions = session_store
        self._seasons = season_store
        self._captures = capture_store
        self._laps = lap_store
        self._session_uid: str | None = None

        outer = QVBoxLayout(self)

        header = QHBoxLayout()
        back = QPushButton("← Sessions")
        back.clicked.connect(self.overview_requested.emit)
        self._title = QLabel()
        apply_heading(self._title, size_px=20)
        header.addWidget(back)
        header.addSpacing(12)
        header.addWidget(self._title)
        header.addStretch(1)
        self._recorded = QLabel()
        self._recorded.setStyleSheet(MUTED_TEXT_QSS)
        header.addWidget(self._recorded)
        outer.addLayout(header)

        self._subtitle = QLabel()
        self._subtitle.setStyleSheet(MUTED_TEXT_QSS)
        # The uid is here to be copied into a bug report, so it has to be selectable.
        self._subtitle.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(self._subtitle)

        source_row = QHBoxLayout()
        self._source = QLabel()
        self._source.setStyleSheet(MUTED_TEXT_QSS)
        source_row.addWidget(self._source)
        source_row.addStretch(1)
        delete = QPushButton("Delete...")
        delete.clicked.connect(self._on_delete)
        source_row.addWidget(delete)
        outer.addLayout(source_row)

        self._body = QVBoxLayout()
        host = QWidget()
        host.setLayout(self._body)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

    def load(self, session_uid: str) -> None:
        """Populate the page for one session uid."""
        self._session_uid = str(session_uid)
        self.reload()

    def reload(self) -> None:
        """Re-query the session and rebuild; leave for the overview if it has vanished."""
        clear_layout(self._body)
        session, slot = self._current()
        if session is None:
            self.overview_requested.emit()      # deleted underneath us, or a re-ingest dropped it
            return

        label = slot_label(slot.session_type, slot.is_sprint_race)
        self._title.setText(f"{track_name(session.track_id)} — {label}")
        self._recorded.setText(recorded_label(session.recorded_at))
        self._subtitle.setText(f"uid {session.session_uid} · Source capture: {self._capture_label(session)}")

        laps = self._stored_laps(session)
        # One classification for the page: the Laps box's indicators, the run split and the pace
        # averages all read this, so a lap the table flags and a lap the average drops are the same
        # lap by construction (ui/sessions/lap_context.py). ``is_race`` covers the Sprint Race too,
        # which shares its session_type with the Grand Prix (core invariant #5).
        analysis = analyse_session(laps, standing_start=is_race(slot.session_type))
        self._body.addWidget(self._top_row(session, slot, label, laps))
        self._body.addWidget(self._middle_row(session, laps, analysis))
        self._body.addWidget(self._charts_row(analysis))
        self._body.addStretch(1)

    # --- rows ------------------------------------------------------------------------------------
    def _top_row(self, session, slot, label: str, laps) -> QWidget:
        """Session details beside the final classification.

        Neither box is height-capped. The classification is sized to show every driver and the
        page's own scroll area takes the overflow - capping the row turned a 20-car field into six
        visible rows, which is worse than scrolling the page.
        """
        details = _box("Session details", 
                       self._details_box(session, slot, label, laps))
        classification = _box(f"Final classification · {label}",
                                build_classification_table(session, is_sprint_race=slot.is_sprint_race), fill=True)
        return _row(details, classification)

    def _middle_row(self, session, laps, analysis) -> QWidget:
        """The player's laps beside the session's penalties, capped.
        
        The Laps table scrolls itself, (header pinned), the penalties panel is plain widgets so it
        gets a scroll area for when E15 is done."""
        return _row(_box("Laps", self._laps_table(session, laps, analysis)),
                    _box("Penalties", self._penalties_panel(session), scroll=True),
                    max_height=_MID_ROW_MAX_H)

    def _charts_row(self, analysis) -> QWidget:
        """The stacked pace and tyre-life charts, under the laps.

        One box rather than two: the charts share a single x-axis inside one pyqtgraph layout, so a
        stint lap reads straight down from wear to pace, and two boxes would put a frame through the
        middle of that. Uncapped in height - the widget fixes its own, and the page scrolls.

        A session with no chartable stint gets an honest sentence instead of an empty plot: a single
        flying lap in dry qualifying genuinely has no stint to draw.
        """
        if not analysis.stints:
            return _box("Tyre stints & pace", _muted_label(_NO_STINTS))
        host = QWidget()
        box = QVBoxLayout(host)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(StintCharts(analysis))
        box.addWidget(_muted_label(_FUEL_CAVEAT))
        return _box("Tyre stints & pace", host)

    # --- boxes -----------------------------------------------------------------------------------
    def _details_grid(self, session, slot, label: str, laps) -> QWidget:
        """The 4x2 read out: results, pace, conditions, context."""
        player = self._player(session)
        position =f"P{player.position}" if player is not None else "\u2014"

        best_ms = session_best_lap_ms(session)
        best = QLabel(format_lap_time(best_ms) if best_ms else "\u2014")
        best.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if best_ms:
            best.setStyleSheet(FASTEST_LAP_QSS)
            best.setToolTip("Fastest lap of the session")

        return build_pair_grid([
            (("Position", position), ("Points", player_points_label(session, slot.is_sprint_race))),
            (("Fastest lap", best), ("Laps completed", laps_completed_label(session, stored_laps=len(laps)))),
            (("Difficulty", self._difficulty_label(session)), ("Conditions", WeatherIcon(session.weather, size_px=24))),
            (("Team & mode", session_context_label(session, label)), ("Recorded", recorded_label(session.recorded_at))),
        ])

    def _details_box(self, session, slot, label: str, laps) -> QWidget:
        """The read-out grid, with the circuit outline filling the space below it.

        A race classification is twenty rows tall and the grid is four, so without something in
        it the left box is mostly blank. The map takes that space when it can be drawn and a
        plain stretch takes it when it can't, so a session with no Motion data still lays out
        correctly rather than leaving a gap where a map should be.
        """
        host = QWidget()
        box = QVBoxLayout(host)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self._details_grid(session, slot, label, laps))
        track = self._track_map(session, laps)
        if track is not None:
            box.addSpacing(6)
            caption = QLabel("Track map")
            apply_bold(caption)
            caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            box.addWidget(caption)
            box.addWidget(track, 0, Qt.AlignmentFlag.AlignHCenter)
        box.addStretch(1)
        return host

    def _track_map(self, session, laps) -> QWidget | None:
        """The circuit, drawn from the player's fastest stored lap - or None if it can't be.

        Deliberately ``TrackMap.set_trace`` (the driven-lap fallback) rather than the canonical
        median line the Laps surface draws. The median comes from ``TrackLayoutProvider``, which
        walks every Motion lap of the whole weekend - measured at roughly a second of Parquet
        reading before its cache warms - and lives in ``ui/laps/``, which this surface must not
        import from. One lap is one read, measured at ~10 ms, and needs nothing new.

        The fastest lap is the one chosen because it is the cleanest line the player drove; an
        out-lap or a spin would draw an excursion as though it were the circuit.
        """
        if self._laps is None or not laps:
            return None
        fastest = min((lap for lap in laps if lap.lap_time_ms),
                      key=lambda lap: lap.lap_time_ms, default=None)
        if fastest is None:
            return None
        hydrated = self._laps.load(str(session.session_uid), fastest.lap_number)
        if hydrated is None or hydrated.trace is None or not hydrated.trace.has_motion:
            return None
        track = TrackMap()
        # Sector colours before the draw, exactly as the laps detail does it - the map has to read
        # the same on both surfaces. set_sectors validates the pair, so a session that never
        # reported the boundaries falls back to a single-colour outline on its own.
        track.set_sectors(session.sector2_start_m, session.sector3_start_m)
        track.set_trace(hydrated.trace)
        # No hover marker here: nothing drives it. The laps detail wires it to the trace plot's
        # cursor; this map is a static outline, so the dot would just be a red spot on the S/F line.
        track.set_cursor_distance(-1)
        track.setMinimumHeight(_TRACK_MAP_MIN_H)
        return track
    
    def _laps_table(self, session, laps, analysis) -> QWidget:
        """The player's laps, one clickable row each, with the gap to *my* fastest lap.

        A single click opens the lap - unlike the laps overview, where the row is also a fold
        target and the first click is already spoken for. Deliberate, and recorded in DECISIONS.

        The ``CTX`` column carries the lap-context chips - START, OUT, IN, SC, RED - from the same
        classification the pace chart's averages use. There is one chip per reason a lap leaves a
        run's average and no chip that isn't one, so a lap missing from an average can always be
        seen to be missing, and the row's tooltip says why. Muted rather than coloured: they are
        context, not a result, and the fastest-lap colours in this table have to keep standing out.
        """
        if not laps:
            return _muted_label(
                "No laps were stored for this session." if self._laps is not None
                else "Lap data is unavailable.")

        player_best = player_best_lap_ms(laps)
        session_best = session_best_lap_ms(session)
        # Blue when player's best is also the session's, green when it's only a personal best.
        # The `player_best and` guard matters: with no timed laps both sides are None, and a bare
        # equality would call that a session-fastest lap and paint it blue.
        best_color = FASTEST_LAP if player_best and player_best == session_best else PERSONAL_BEST

        columns = ["LAP", "TYRE", "GAP", "TIME", "CTX"]
        table = QTableWidget(len(laps), len(columns))
        table.setHorizontalHeaderLabels(columns)
        tidy_table(table)
        table.setIconSize(_ICON_SIZE)    # the Laps box's compound icon
        table.setCursor(Qt.CursorShape.PointingHandCursor)
        table.setToolTip("Click a lap to open its telemetry.")
        for row, lap in enumerate(laps):
            number = cell(str(lap.lap_number))
            number.setData(Qt.ItemDataRole.UserRole, lap.lap_number)
            table.setItem(row, 0, number)

            tyre = cell("")
            pixmap = tyre_pixmap(lap.tyre_context.visual_compound) if lap.tyre_context else None
            if pixmap is not None:
                tyre.setIcon(QIcon(pixmap))
            table.setItem(row, 1, tyre)

            table.setItem(row, 2, cell(lap_gap_label(lap.lap_time_ms, player_best)))
            time_item = cell(format_lap_time(lap.lap_time_ms))
            if player_best and lap.lap_time_ms == player_best:
                time_item.setForeground(QColor(best_color))
            table.setItem(row, 3, time_item)

            context = analysis.for_lap(lap.lap_number)
            flags = cell(" ".join(context.indicators))
            tooltip = context.tooltip
            if flags is not None:
                # On the whole row, not just the chip: the user hovering a lap *time* that looks
                # out of place is the one asking "why isn't this in the average?", and a two-letter
                # chip three columns away is not where they are pointing.
                for column in range(table.columnCount()):
                    item = table.item(row, column) or flags
                    item.setToolTip(tooltip)
            if context.indicators:
                # setForeground, never a stylesheet: a stylesheet freezes the palette at apply time
                # and survives a theme switch (core invariant #11). MUTED_TEXT reads on both grounds.
                flags.setForeground(QColor(MUTED_TEXT))
            table.setItem(row, 4, flags)
        fit_table_height(table, max_height=_LAPS_TABLE_MAX_H)
        table.cellClicked.connect(partial(self._open_lap, table))
        return table

    def _penalties_panel(self, session) -> QWidget:
        """What we can honestly say about penalties, which is less than the box implies.

        Only the aggregate is stored (``num_penalties`` / ``penalties_time_s`` on the player's
        entry); the type and the lap live in ``PENA`` Event packets the assembler never reads
        (PRIORITIES -> E15). So a penalised session must not fall through to the empty state and
        report itself as clean - it gets the aggregate plus a note about what is missing.
        """
        player = self._player(session)
        badge = format_penalty_badge(player.num_penalties, player.penalties_time_s) \
            if player is not None else None
        if badge is None:
            return _muted_label("No penalties were recorded for this session.")

        panel = QWidget()
        box = QVBoxLayout(panel)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(QLabel(badge))
        box.addWidget(_muted_label("Per-penalty detail (type and lap) isn't stored yet."))
        box.addStretch(1)
        return panel

    # --- data ------------------------------------------------------------------------------------
    def _stored_laps(self, session) -> list:
        """The player's stored laps for this session, cheaply (DB rows only, no traces)."""
        if self._laps is None:
            return ()
        return self._laps.list(str(session.session_uid))

    @staticmethod
    def _player(session):
        entries = session.classification.entries if session.classification else ()
        return next((entry for entry in entries if entry.is_player), None)

    def _current(self):
        """The loaded session and its weekend slot, or ``(None, None)`` if it is gone.

        ``slot_for_session`` needs the other sessions of the weekend to tell a Sprint Race from
        the Grand Prix (core invariant #5), so the whole list is read either way.
        """
        if self._session_uid is None:
            return None, None
        all_sessions = self._sessions.list_sessions()
        session = next(
            (s for s in all_sessions if str(s.session_uid) == self._session_uid), None)
        if session is None:
            return None, None
        return session, slot_for_session(session, all_sessions)

    @staticmethod
    def _difficulty_label(session) -> str:
        """AI difficulty, an em dash when a session with AI predates the capture, else 'No AI'.

        Same three-way reading as the overview: ``ai_difficulty == 0`` means both "no AI here" and
        "stored before PIPELINE_VERSION 3", and ``is_ai`` on the entries is what tells them apart.
        """
        if session.ai_difficulty:
            return str(session.ai_difficulty)
        entries = session.classification.entries if session.classification else ()
        return "\u2014" if any(entry.is_ai for entry in entries) else "No AI"

    def _capture_label(self, session) -> str:
        """Which archive this session came from, or an honest note about why it can't say.

        Three distinct answers, because they mean different things to a user: no capture row at
        all (pruned, or ingested before capture metadata was recorded), a row whose archive has
        moved or been deleted, and the normal case. The middle one is exactly what blocks a
        restore later, so it must not read the same as the first.
        """
        if self._captures is None:
            return "—"
        metas = self._captures.for_session(str(session.session_uid))
        if not metas:
            return "not recorded"
        captures_dir = str(paths.captures_dir())
        found = sorted(m.file_name for m in metas
                       if resolve_capture_path(m, captures_dir) is not None)
        if not found:
            return f"{metas[0].file_name}  (archive not found)"
        return ", ".join(found)

    # --- actions ---------------------------------------------------------------------------------
    def _open_lap(self, table: QTableWidget, row: int, column: int) -> None:
        """Ask for one lap's telemetry; the container and window make the cross-surface hop."""
        item = table.item(row, 0)
        if item is not None and self._session_uid is not None:
            self.lap_requested.emit(self._session_uid, item.data(Qt.ItemDataRole.UserRole))

    def _on_delete(self) -> None:
        """Delete this session through the shared guard, then leave - this page has no subject."""
        if self._session_uid is None:
            return
        if not confirm_and_delete(self, int(self._session_uid), self._sessions, self._seasons,
                                  lap_store=self._laps):
            return
        self.sessions_changed.emit()
        self.overview_requested.emit()


def _box(title: str, content: QWidget, fill: bool = False, scroll: bool = False) -> QWidget:
    """One titled section: a bold heading over its content, inside a light frame.

    A framed ``QLabel`` heading rather than a ``QGroupBox``: a group box draws its title in the
    *widget's* own font, so sizing the title up would size every child that inherits it. Here only
    the heading is styled, and ``StyledPanel`` follows the palette with no stylesheet at all.

    ``fill`` pushes the content to the top, leaving empty space below its last row, so the shorter
    box in a row sits naturally beside a taller one instead of stretching its rows apart.

    ``scroll`` puts the content in a scroll area, for a box inside a height-capped row whose
    content has no upper bound. It supersedes ``fill``: the scroll area already takes the spare
    height, so a stretch beside it would have nothing to push against. A *table* does not need
    this - left unfrozen it scrolls itself and keeps its header row pinned, which a scroll area
    around the whole table would not.
    """
    frame = QFrame()
    frame.setFrameShape(QFrame.Shape.StyledPanel)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(10, 8, 10, 10)
    heading = QLabel(title)
    apply_heading(heading, size_px=17)
    layout.addWidget(heading)

    if scroll:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(content)
        layout.addWidget(area, 1)
        return frame

    layout.addWidget(content)
    if fill:
        layout.addStretch(1)
    return frame


def _row(left: QWidget, right: QWidget, max_height: int | None = None) -> QWidget:
    """Two equal-width boxes side by side; the row is as tall as its taller box."""
    host = QWidget()
    layout = QHBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(left, 1)
    layout.addWidget(right, 1)
    if max_height is not None:
        host.setMaximumHeight(max_height)
    return host


def _muted_label(text: str) -> QLabel:
    """A muted, wrapping label for an empty state or a caveat.

    ``MUTED_TEXT_QSS`` sets ``color:`` explicitly, the one kind of stylesheet A4 leaves alone -
    it can't freeze a colour it states outright (core invariant #11).
    """
    label = QLabel(text)
    label.setStyleSheet(MUTED_TEXT_QSS)
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
    return label
