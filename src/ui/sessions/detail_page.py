"""The session detail page - what one session was, how it finished, and how it was driven.

Five boxes over the shared classification builder: a 4x3 details grid and the final
classification side by side, the player's laps and the session's race control below them, and
(branch 2c) the stacked pace / tyre-life charts under that.

"nothing happened", so it has a third state that says which (``sessions.race_control``).

The details grid's three E15 cells follow the same rule from the other side. Each returns None
from ``ui.formatting`` when its value was never captured, and this page renders that as a muted
``Not captured`` rather than as the em dash it uses for "does not apply to this session type" -
two different absences that must not read alike (DECISIONS -> UI).

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
    build_readout_grid,
    cell,
    clear_layout,
    confirm_and_delete,
    display_name_fn,
    fit_columns,
    fit_table_height,
    session_weather,
    tidy_table,
)
from ..components.flags import flag_icon
from ..components.tyres import tyre_pixmap
from ..formatting import (
    NOT_CAPTURED,
    NOT_CAPTURED_TOOLTIP,
    format_grid,
    format_lap_time,
    is_race,
    lap_gap_label,
    laps_completed_label,
    overtakes_label,
    overtakes_tooltip,
    player_best_lap_ms,
    player_points_label,
    recorded_label,
    session_best_lap_ms,
    session_context_label,
    slot_label,
    time_of_day_label,
    time_of_day_tooltip,
    track_air_temp_label,
    track_air_temp_tooltip,
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
from ..season_roster import SeasonRosterFiles
from .lap_context import analyse_session
from .league_names import SessionRosters
from .race_control import grid_penalty_places, summarise_penalties
from .stint_charts import StintCharts

_MID_ROW_MAX_H = 500            # the Laps / Race control row is capped; those two boxes scroll inside it
_LAPS_TABLE_MAX_H = 440         # _MID_ROW_MAX_H less the box's heading and margins
_FLAG_SIZE = QSize(28, 21)      # the classification table's nationality flag, 4:3
_ICON_SIZE = QSize(22, 22)      # the Laps box's compound icon, same as the laps overview
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

    def __init__(self, session_store, season_store, capture_store=None, lap_store=None, 
                 event_store=None, rosters=None, parent=None):
        super().__init__(parent)
        self._sessions = session_store
        self._seasons = season_store
        self._captures = capture_store
        self._laps = lap_store
        self._events = event_store
        # A league member who raced with online-name sharing off captured as "Player"; this resolves
        # that through the season's saved roster (E1c). Built here when the container did not inject
        # one, so the names are right by default rather than only when a caller remembers to wire it.
        self._rosters = rosters or SessionRosters(season_store, SeasonRosterFiles())
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
        # Re-read the assignments and roster files for this paint: assigning a session on the
        # Seasons surface, or hand-editing a roster JSON, has to show up without a restart.
        self._rosters.invalidate()
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

        # Read once for the page: the classification0s grid badges and the Race control box are
        # two readings of the same rows, and two queries could not disagree bt would still be two.
        penalties = self._stored_penalties(session)

        # The passes are read once too, and only the details grid reads them: the Race control box
        # lists penalties and nothing else. Field-wide rows, because whether the session has *any*
        # is what tells "+0 / -0" apart from "not captured".
        overtakes = self._stored_overtakes(session)

        # one resolver for the page, so the Classification and the Race control box cannot name
        # the same driver differently. Non-generic captured names win, so this is a no-op for a
        # session whose drivers shared their online names (E1c).
        name_of = display_name_fn(self._rosters.roster_for_session(session.session_uid))

        self._body.addWidget(self._top_row(session, slot, label, laps, penalties, overtakes, name_of))
        self._body.addWidget(self._middle_row(session, laps, analysis, penalties, name_of))
        self._body.addWidget(self._charts_row(analysis))
        self._body.addStretch(1)

    # --- rows ------------------------------------------------------------------------------------
    def _top_row(self, session, slot, label: str, laps, penalties=(), overtakes=(),
                 name_of=lambda entry: entry.driver_name) -> QWidget:
        """Session details beside the final classification.

        Neither box is height-capped. The classification is sized to show every driver and the
        page's own scroll area takes the overflow - capping the row turned a 20-car field into six
        visible rows, which is worse than scrolling the page.
        """
        details = _box("Session details", 
                       self._details_box(session, slot, label, laps, overtakes))
        classification = _box(f"Final classification · {label}",
                                build_classification_table(session, name_of, 
                                                           is_sprint_race=slot.is_sprint_race, 
                                                           grid_penalties=grid_penalty_places(penalties)), fill=True)
        return _row(details, classification)

    def _middle_row(self, session, laps, analysis, penalties=(), 
                    name_of=lambda entry: entry.driver_name) -> QWidget:
        """The player's laps beside the session's race control, capped.

        The Laps table scrolls itself (header pinned); the Race control panel is plain widgets, so
        it takes a scroll area. A race can issue any number of penalties and the box must not be
        able to grow the page (DECISIONS -> UI) - the worst session in this database is eleven
        rows, and the cap is what keeps that a property of the box rather than of the data."""
        return _row(_box("Laps", self._laps_table(session, laps, analysis)),
                    _box("Race control", self._race_control_panel(session, penalties, name_of),
                          scroll=True), max_height=_MID_ROW_MAX_H)

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
    def _details_grid(self, session, slot, label: str, laps, overtakes=()) -> QWidget:
        """The 4x3 read out: results, pace, conditions, context."""
        player = self._player(session)
        position =f"P{player.position}" if player is not None else "\u2014"

        best_ms = session_best_lap_ms(session)
        best = QLabel(format_lap_time(best_ms) if best_ms else "\u2014")
        best.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if best_ms:
            best.setStyleSheet(FASTEST_LAP_QSS)
            best.setToolTip("Fastest lap of the session")

        return build_readout_grid([
            (("Position", position), 
             ("Points", player_points_label(session, slot.is_sprint_race)),
             ("Started", format_grid(player.grid_position) if player is not None else "\u2014")),
            (("Fastest lap", best), 
             ("Laps completed", laps_completed_label(session, stored_laps=len(laps))),
             ("Overtakes +/\u2212", _captured_cell(overtakes_label(session, overtakes), 
                                                    overtakes_tooltip(session, overtakes)))),
            (("Difficulty", self._difficulty_label(session)), 
             ("Conditions", WeatherIcon(session_weather(session), size_px=24)),
             ("Track & air temp", _captured_cell(track_air_temp_label(session), 
                                                 track_air_temp_tooltip(session)))),
            (("Team & mode", session_context_label(session, label)), 
             ("Recorded", recorded_label(session.recorded_at)),
             ("Time of day", _captured_cell(time_of_day_label(session), 
                                             time_of_day_tooltip(session)))),
        ])
    
    def _details_box(self, session, slot, label: str, laps, overtakes=()) -> QWidget:
        """The read-out grid, with the circuit outline filling the space below it.

        A race classification is twenty rows tall and the grid is four, so without something in
        it the left box is mostly blank. The map takes that space when it can be drawn and a
        plain stretch takes it when it can't, so a session with no Motion data still lays out
        correctly rather than leaving a gap where a map should be.
        """
        host = QWidget()
        box = QVBoxLayout(host)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self._details_grid(session, slot, label, laps, overtakes))
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

    def _race_control_panel(self, session, penalties=(),
                            name_of=lambda entry: entry.driver_name) -> QWidget:
        """What race control did to this session: its penalties, field-wide.

        **The player's passes were weighed for this box and left out** (DECISIONS -> UI, E15
        branch 3). A pass is not a race-control action, so the box's own title argues against it;
        the details grid's ``Overtakes +/-`` is on the same screen and a count line here would be
        the only number on the page stated twice; and the measurement settles it - a list would
        have *under*filled the box in 16 of the 17 races here that hold passes (median 3 rows, 5 or
        fewer in 12 of them) and, in the seventeenth, printed 42 rows of which sixteen are one
        incident inside 5.7 seconds, with 40% of all 95 player race rows the same pair swapping
        back within 30 s. The count absorbs that; a list of rows reads as a fault.

        It stays a panel rather than a bare table so the section keeps its own heading and empty
        state, which the three-state honesty rule needs.
        """
        panel = QWidget()
        box = QVBoxLayout(panel)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self._penalties_section(session, penalties, name_of))
        box.addStretch(1)
        return panel

    def _penalties_section(self, session, penalties=(), 
                           name_of=lambda entry: entry.driver_name) -> QWidget:
        """The session's penalties - every car's, named, in the order they were issued.

        Field-wide rather than the player's: what a league reader opens this page for is what
        happened to the whole field, and ``EventStore`` stores it that way. Every text decision -
        the wording, the three states, the driver join - is ``race_control.summarise_penalties``,
        so this only lays out what it returns.

        The rows are the ones ``reload`` already read. They used to be re-read here, which made the
        page query ``EventStore`` twice for the same session while the comment above the first read
        said it happened onece.
        """
        entries = session.classification.entries if session.classification else ()
        summary = summarise_penalties(penalties, entries, name_of)

        host = QWidget()
        box = QVBoxLayout(host)
        box.setContentsMargins(0, 0, 0, 0)
        heading = QLabel(summary.heading)
        apply_bold(heading)
        box.addWidget(heading)
        for line in summary.aggregates:
            box.addWidget(QLabel(line))
        box.addWidget(_muted_label(summary.note))
        if summary.rows:
            box.addWidget(_penalty_table(summary.rows))
        return host

    # --- data ------------------------------------------------------------------------------------
    def _stored_laps(self, session) -> list:
        """The player's stored laps for this session, cheaply (DB rows only, no traces)."""
        if self._laps is None:
            return ()
        return self._laps.list(str(session.session_uid))

    def _stored_penalties(self, session) -> tuple:
        """The session's stored penalties - every car's, in the store's lap-then-frame order.

        Read from ``EventStore`` and not from the session: ``SessionStore.load`` maps named fields
        and has never populated ``SessionResult.penalties``. An empty read is not a clean session
        (see ``race_control``), which is why the empty tuple goes on to be interpreted rather than
        tested for here.
        """
        if self._events is None:
            return ()
        return self._events.load_penalties(str(session.session_uid))

    def _stored_overtakes(self, session) -> tuple:
        """The session's stored passes - every car's, in the order the game announced them.

        Field-wide, though only the player's count is shown, and that is deliberate rather than
        incidental: whether the session holds *any* pass rows is the only thing that tells a real
        ``+0 / -0`` apart from a session ingested before ``PIPELINE_VERSION`` 5. Six of the 20 races
        in this database have no player passes and every one is a start from pole and a win.

        Arrival order, not lap-then-frame like the penalties - two passes can share a frame and a
        pass is not "greater" than another. Nothing on screen is ordered, only counted, so that
        never reaches the user.
        """
        if self._events is None:
            return ()
        return self._events.load_overtakes(str(session.session_uid))
    
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
                                  lap_store=self._laps, event_store=self._events):
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


def _penalty_table(rows) -> QTableWidget:
    """One row per penalty, read like the Laps table beside it: a header, then lap / driver / what.

    A table rather than laid-out labels, because it is one: four aligned columns with a header is
    what makes a list of eleven scannable, and it inherits the alignment, the row striping and the
    flag-in-the-driver-cell that the classification table already reads by. LAP and DRIVER first,
    the way that table orders POS and DRIVER - and because OUTCOME is the word "Warning" on 70 of
    the 129 rows in this database, so leading with it would put a wall of the same word where the
    varying columns should be.

    Two independent uses of one font weight, in two columns that cannot be confused: a bold driver
    is a human rather than an AI car, and a bold outcome is a penalty the classification counts.
    Weight and not colour, so nothing here can freeze a palette (core invariant #11). The tooltip
    goes on every cell, because a reader pointing at a lap number is asking about that row.

    Height is left to fit every row and the box's scroll area takes the overflow - the box is
    already capped, and branch 3's passes section will scroll with this rather than beside it.
    """
    columns = ["LAP", "DRIVER", "OUTCOME", "REASON"]
    table = QTableWidget(len(rows), len(columns))
    table.setHorizontalHeaderLabels(columns)
    tidy_table(table)
    table.setIconSize(_FLAG_SIZE)       # nationality flag in the DRIVER cell (4:3)

    for index, row in enumerate(rows):
        lap = cell(str(row.lap_number))
        lap.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        driver = cell(row.driver)
        if row.nationality_id is not None:
            flag = flag_icon(row.nationality_id)
            if flag is not None:
                driver.setIcon(flag)
        if row.is_human:
            _bold_cell(driver)
        outcome = cell(row.outcome)
        if row.is_sporting:
            _bold_cell(outcome)
        for column, item in enumerate((lap, driver, outcome, cell(row.reason))):
            item.setToolTip(row.tooltip)
            table.setItem(index, column, item)
    # REASON alone takes the spare width. Stretching DRIVER beside it split the slack evenly and
    # left the longest column short - "Small Collision with Andra-Kimi Antonelli" is twice a
    # driver name - while DRIVER sized to its contents is exactly as wide as the longest name.
    fit_columns(table, stretch={3})
    fit_table_height(table)
    return table


def _bold_cell(item) -> None:
    """Bold one table cell. ``setFont``, never a stylesheet - see ``ui/style`` and invariant #11."""
    font = item.font()
    font.setBold(True)
    item.setFont(font)


def _captured_cell(text: str | None, tooltip: str = "") -> QLabel:
    """A details-grid value, or a muted ``Not captured`` when ``ui.formatting`` returned None.

    The only thing decided here is the *painting*. Which of the two absences applies is decided
    Qt-free: an em dash comes back as a string and means "does not apply to this session type",
    while None means "we do not have it" and is the one that reads muted (DECISIONS -> UI). A row
    ingested before the value existed must never render as a confident number.
    """
    label = QLabel(text if text is not None else NOT_CAPTURED)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    if text is None:
        # MUTED_TEXT_QSS states its colour outright, the one stylesheet invariant #11 allows.
        label.setStyleSheet(MUTED_TEXT_QSS)
    label.setToolTip(tooltip if text is not None else NOT_CAPTURED_TOOLTIP)
    return label


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
