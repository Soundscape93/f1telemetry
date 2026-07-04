"""The session classification table - the results grid shown for one captured session.

A view-agnostic builder: it renders a session's classification the way the game's results
screen reads (position, driver, number, team, and a result/points-or-laps pair that differs
for race vs non-race sessions). The weekend view, and later the Sessions / Laps surfaces,
all compose this same table instead of rebuilding it.

Names are resolved through an injected ``name_of`` callable so this module never needs to know
about league rosters: callers pass ``display_name_fn(roster)`` for LEAGUE views and the default
(the entry's own name) everywhere else.
"""

from __future__ import annotations

from PySide6.QtWidgets import QTableWidget

from ..formatting import is_race, non_race_result, race_result
from ...domain.roster import LeagueRoster, league_display_name
from ...protocol.reference import team_name
from .tables import cell, fit_table_height, tidy_table


def display_name_fn(roster: LeagueRoster | None):
    """A per-render name resolver: the league display name when a roster is present, else the
    entry's own shown name. Injected into result cells so non-LEAGUE views stay unchanged."""
    if roster is None:
        return lambda entry: entry.driver_name
    return lambda entry: league_display_name(entry, roster)


def build_classification_table(session, name_of=lambda entry: entry.driver_name) -> QTableWidget:
    """Return a classification table for one session (no surrounding chrome).

    ``name_of`` resolves each entry's shown name; it defaults to the entry's own driver name.
    """
    race_session = is_race(session.session_type)
    if race_session:
        columns = ["Pos", "Driver", "No.", "Team", "Time", "Points"]
    else:
        columns = ["Pos", "Driver", "No.", "Team", "Best lap", "Laps"]
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    tidy_table(table)

    entries = session.classification.entries if session.classification else []
    winner = next((e for e in entries if e.position == 1), entries[0] if entries else None)
    table.setRowCount(len(entries))
    for i, entry in enumerate(entries):
        table.setItem(i, 0, cell(str(entry.position)))
        table.setItem(i, 1, cell(name_of(entry)))
        table.setItem(i, 2, cell(str(entry.race_number)))
        table.setItem(i, 3, cell(team_name(entry.team_id)))
        if race_session:
            table.setItem(i, 4, cell(race_result(entry, winner)))
            table.setItem(i, 5, cell(str(entry.points)))
        else:
            table.setItem(i, 4, cell(non_race_result(entry, session.session_type)))
            table.setItem(i, 5, cell(str(entry.num_laps)))
    fit_table_height(table)
    return table
