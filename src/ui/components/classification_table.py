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
from PySide6.QtWidgets import QLabel, QTableWidget, QTableWidgetItem

from ..formatting import (
    compound_for_lap,
    format_grid,
    format_lap_gap,
    format_lap_time,
    format_penalty_badge,
    format_position_change,
    is_race,
    non_race_result,
    race_result,
)
from ...domain.roster import LeagueRoster, league_display_name
from ...protocol.enums import ResultStatus
from ...protocol.reference import team_display_name
from .flags import flag_icon
from .tables import cell, fit_table_height, tidy_table
from .tyres import tyre_pixmap

# Position-change colours (Pos triangle). Chosen to read on both light and dark palettes.
_POS_COLORS = {"gain": "#3fb950", "loss": "#f85149"}

# How often the Time cell flips between the race time and the penalty badge.
_ALTERNATE_MS = 2000


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
    label.setStyleSheet("background: transparent;")
    return label


def _tyre_widget(pixmap) -> QLabel:
    """A TYRE cell holding a centred compound tyre icon."""
    label = QLabel()
    label.setPixmap(pixmap)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet("background: transparent;")
    return label


def _wire_penalty_alternation(
    table: QTableWidget, penalty_cells: list[tuple[QTableWidgetItem, str, str]]
) -> None:
    """Flip each penalised finisher's TIME cell between its race time and its penalty badge.

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


def build_classification_table(session, name_of=lambda entry: entry.driver_name) -> QTableWidget:
    """Return a classification table for one session (no surrounding chrome).

    ``name_of`` resolves each entry's shown name; it defaults to the entry's own driver name.
    """
    race_session = is_race(session.session_type)
    if race_session:
        columns = ["POS", "DRIVER", "TEAM", "GRID", "STOPS", "BEST", "TIME", "PTS"]
    else:
        columns = ["POS", "DRIVER", "TEAM", "TYRE", "BEST", "GAP"]
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    tidy_table(table)
    table.setIconSize(QSize(28, 21))    # nationality flag in the DRIVER cell (4:3)

    entries = session.classification.entries if session.classification else []
    winner = next((e for e in entries if e.position == 1), entries[0] if entries else None)
    table.setRowCount(len(entries))

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
            table.setItem(i, 5, cell(format_lap_time(entry.best_lap_time_ms)))
            time_str = race_result(entry, winner)
            time_item = cell(time_str)
            table.setItem(i, 6, time_item)
            table.setItem(i, 7, cell(str(entry.points)))
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
            table.setItem(i, 4, cell(non_race_result(entry, session.session_type)))
            table.setItem(i, 5, cell(format_lap_gap(entry, winner)))

    _wire_penalty_alternation(table, penalty_cells)
    fit_table_height(table)
    return table
