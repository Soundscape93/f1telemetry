"""The session classification table - the results grid shown for one captured session.

A view-agnostic builder: it renders a session's classification the way the game's results
screen reads. Race sessions show position (with a grid-vs-finish change triangle), driver
(with a nationality flag), team, grid, stops, best lap, time (alternating with a penalty badge),
and points; non-race sessions show position, driver, team, tyre, best lap, and gap to the
session's fastest lap.
The weekend view, and later the Sessions / Laps surfaces, all compose this same table instead
of rebuilding it.

Names are resolved through an injected ``name_of`` callable so this module never needs to know
about league rosters: callers pass ``display_name_fn(roster)`` for LEAGUE views and the default
(the entry's own name) everywhere else. AI cars already carry their canonical full name (baked
into ``driver_name`` by the normalizer); human online names are left untouched.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QTableWidget, QTableWidgetItem

from ..formatting import (
    compound_for_lap,
    estimate_points,
    format_grid,
    format_grid_penalty,
    format_lap_gap,
    format_lap_time,
    format_penalty_badge,
    format_position_change,
    is_race,
    non_race_result,
    race_result,
    session_best_lap_ms,
)
from ...domain.roster import LeagueRoster, league_display_name
from ...protocol.enums import ResultStatus
from ...protocol.reference import team_display_name
from ..style import FASTEST_LAP, MUTED_TEXT, POSITION_GAIN, POSITION_LOSS
from .flags import flag_icon
from .tables import cell, fit_columns, fit_table_height, hold_column_width, tidy_table
from .tyres import tyre_pixmap

# Position-change colours (Pos triangle), from the shared palette in ``ui/style`` so the
# gain-green is the same green the session detail uses for a personal-best lap.
_POS_COLORS = {"gain": POSITION_GAIN, "loss": POSITION_LOSS}


# How often the Time cell flips between the race time and the penalty badge.
_ALTERNATE_MS = 2000


# The one column that alternates, per layout: a race's TIME, and a practice/qualifying GAP.
_TIME_COLUMN = 6
_GAP_COLUMN = 5


def display_name_fn(roster: LeagueRoster | None):
    """A per-render name resolver: the league display name when a roster is present, else the
    entry's own shown name. Injected into result cells so non-LEAGUE views stay unchanged."""
    if roster is None:
        return lambda entry: entry.driver_name
    return lambda entry: league_display_name(entry, roster)


def _pos_change_widget(position: int, glyph: str, kind: str) -> QLabel:
    """A POS cell showing the finishing position plus a bold, coloured change triangle
    (green up / red down / neutral dash)."""
    color = _POS_COLORS.get(kind)
    styled = (
        f'<span style="color:{color}; font-weight:700">{glyph}</span>'
        if color
        else f'<span style="font-weight:700">{glyph}</span>'
    )
    label = QLabel(f"{position}&nbsp;&nbsp;{styled}")
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setContentsMargins(6, 0, 6, 0)
    return label


def _tyre_widget(pixmap) -> QLabel:
    """A TYRE cell holding a centred compound tyre icon."""
    label = QLabel()
    label.setPixmap(pixmap)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


def _points_cell(entry, reconstructed: bool, is_sprint_race: bool) -> QTableWidgetItem:
    """The PTS cell. For a normal (game-reported) result it's the official points; for a
    reconstructed result - where no Final Classification packet supplied points - it shows a muted
    estimate (``~25``) from finishing position, or blank for a non-finisher. Display-only: this
    number never reaches standings (see analysis.standings)."""
    if not reconstructed:
        return cell(str(entry.points))
    est = estimate_points(entry.position, entry.result_status, is_sprint_race)
    item = cell("" if est is None else f"~{est}")
    item.setForeground(QColor(MUTED_TEXT))
    return item


def _wire_penalty_alternation(
    table: QTableWidget, penalty_cells: list[tuple[QTableWidgetItem, str, str]]) -> None:
    """Flip a penalised car's result cell between what it says and its penalty badge.

    Two callers, one mechanism: a race finisher's TIME cell alternates with the seconds a penalty
    added to it, and a practice/qualifying car's GAP cell alternates with the grid places it was
    penalised. Both are facts that have no column of their own and would cost one.

    The timer is parented to the table, so it's disposed with it; the closure it drives keeps
    the cell list alive for as long as the connection lives.
    """
    if not penalty_cells:
        return
    timer = QTimer(table)
    state = {"show_badge": False}

    def _tick() -> None:
        state["show_badge"] = not state["show_badge"]
        for item, time_str, badge_str in penalty_cells:
            item.setText(badge_str if state["show_badge"] else time_str)

    timer.timeout.connect(_tick)
    timer.start(_ALTERNATE_MS)


def build_classification_table(
    session, name_of=lambda entry: entry.driver_name, is_sprint_race: bool = False, 
    scrollable: bool = False, grid_penalties=None) -> QTableWidget:
    """Return a classification table for one session (no surrounding chrome).

    ``name_of`` resolves each entry's shown name; it defaults to the entry's own driver name.
    ``is_sprint_race`` (from the weekend context) picks the Sprint points table when estimating
    points for a reconstructed race - the two share ``SessionType.RACE`` and can't be told apart
    from the session alone.

    ``grid_penalties`` maps ``vehicle_index`` to the grid places that car was penalised, from
    ``sessions.race_control.grid_penalty_places`` over the session's stored ``PENA`` rows. It is
    optional because it needs an ``EventStore`` the caller may not hold - the weekend page does not,
    and simply shows no grid badges - and because a session ingested before ``PIPELINE_VERSION`` 5
    has no rows to build it from. Only practice and qualifying read it: every grid penalty in this
    database is issued there, and a race's TIME cell already alternates with its own badge.

    ``scrollable`` leaves the table's height to its container instead of freezing it to fit every row.
    The default (False) is the sized-to-context behaviour every existing caller relies on;
    the session detail page passes True because it puts the table in a height-capped box beside a
    much shorter details grid, and a 20-row table would otherwise decide that row's height.
    """
    race_session = is_race(session.session_type)
    reconstructed = session.classification is not None and session.classification.is_reconstructed
    if race_session:
        columns = ["POS", "DRIVER", "TEAM", "GRID", "STOPS", "BEST", "TIME", "PTS"]
    else:
        columns = ["POS", "DRIVER", "TEAM", "TYRE", "BEST", "GAP"]
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    tidy_table(table)
    table.setIconSize(QSize(28, 21))    # nationality flag in the DRIVER cell (4:3)

    grid_places = grid_penalties or {}
    entries = session.classification.entries if session.classification else []
    winner = next((e for e in entries if e.position == 1), entries[0] if entries else None)
    table.setRowCount(len(entries))
    # The session's fastest lap time is painted blue, the same blue the detail page uses
    fastest_ms = session_best_lap_ms(session)

    penalty_cells: list[tuple[QTableWidgetItem, str, str]] = []
    for i, entry in enumerate(entries):
        driver_item = cell(name_of(entry))
        flag = flag_icon(entry.nationality_id)
        if flag is not None:
            driver_item.setIcon(flag)
        table.setItem(i, 1, driver_item)
        table.setItem(i, 2, cell(team_display_name(entry.team_id)))
        if race_session:
            glyph, kind = format_position_change(entry.grid_position, entry.position)
            table.setCellWidget(i, 0, _pos_change_widget(entry.position, glyph, kind))
            table.setItem(i, 3, cell(format_grid(entry.grid_position)))
            table.setItem(i, 4, cell(str(entry.num_pit_stops)))
            best_item = cell(format_lap_time(entry.best_lap_time_ms))
            if fastest_ms and entry.best_lap_time_ms == fastest_ms:
                best_item.setForeground(QColor(FASTEST_LAP))
            table.setItem(i, 5, best_item)
            time_str = race_result(entry, winner)
            time_item = cell(time_str)
            table.setItem(i, 6, time_item)
            table.setItem(i, 7, _points_cell(entry, reconstructed, is_sprint_race))
            badge = format_penalty_badge(entry.num_penalties, entry.penalties_time_s)
            if badge and entry.result_status == ResultStatus.FINISHED:
                penalty_cells.append((time_item, time_str, badge))
        else:
            table.setItem(i, 0, cell(str(entry.position)))
            table.setItem(i, 3, cell(""))
            compound = compound_for_lap(entry.tyre_stints, entry.best_lap_num)
            pixmap = tyre_pixmap(compound) if compound is not None else None
            if pixmap is not None:
                table.setCellWidget(i, 3, _tyre_widget(pixmap))
            # Outside the tyre branch on purpose: 84 of this database's 949 practice/qualifying
            # rows have no compound for their best lap, and nesting the time inside the icon left
            # every one of them with an empty BEST cell.
            best_item = cell(format_lap_time(entry.best_lap_time_ms))
            if fastest_ms and entry.best_lap_time_ms == fastest_ms:
                best_item.setForeground(QColor(FASTEST_LAP))
            table.setItem(i, 4, best_item)
            gap_str = format_lap_gap(entry, winner)
            gap_item = cell(gap_str)
            table.setItem(i, 5, gap_item)
            # A grid penalty is served in the *race*, so it changes nothing about this session's
            # result - which is why it rides the GAP cell rather than BEST, where alternating it
            # would read as if the lap time itself had been penalised.
            grid_badge = format_grid_penalty(grid_places.get(entry.vehicle_index, 0))
            if grid_badge:
                penalty_cells.append((gap_item, gap_str, grid_badge))

    _wire_penalty_alternation(table, penalty_cells)
    # DRIVER and TEAM take the spare width; POS/GRID/STOPS/BEST/TIME/PTS stay as narrow as their contents.
    fit_columns(table, stretch={1, 2})
    # ...except the one column that alternates, which is sized for both of its texts and pinned.
    # Left to resize itself it would grow and shrink every two seconds and shove DRIVER and TEAM
    # about with it; those two have width to spare and are where the difference comes from.
    hold_column_width(table, _TIME_COLUMN if race_session else _GAP_COLUMN, penalty_cells)
    if not scrollable:
        fit_table_height(table)
    return table
