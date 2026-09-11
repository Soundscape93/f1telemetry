"""One session as a ``ShareDocument`` - what Session detail's Share exports. Qt-free, so every
string the image says about a session is unit-tested the way ``race_control``'s are (E19).

**It says what the page says.** Every driver is named by the page's own resolver, handed in as
``name_of`` (E1c); the slot label comes from the session's weekend slot, never its raw type (core
invariant #5); the penalty rows, their heading and their note are ``race_control``'s; and every
classification cell is the ``formatting`` helper ``build_classification_table`` calls for it. This
module arranges them and re-derives none. That the arrangement agrees with the page's own table was
checked cell by cell, offscreen, on every session in the database.

**Where a still image cannot say it the same way, it says it in the open.** The page flips a
penalised finisher's TIME cell to its penalty badge and back, and a qualifying car's GAP cell to its
grid penalty; an image cannot flip, so each becomes a column of its own - ``PEN`` and ``GRID
PENALTY`` - present only when some row has one. The position-change triangle takes its own narrow
column, because a cell has one colour and the triangle's is not the position's. A reconstructed
classification says so under its title, since the page's only sign of it - points muted to ``~8`` -
is easy to miss in a photo.

**The header facts are the session's, not the player's.** The page's details grid is about the
player - position, points, grid slot, passes, team - and none of that belongs in a league's result.
The image carries the session's fastest lap, a race's distance, the weather and the temperatures,
and leaves out whichever of those was never captured rather than printing "Not captured" into a
chat.
"""
from __future__ import annotations

from ...protocol.enums import ResultStatus
from ...protocol.reference import team_display_name, track_name
from ...version import __version__
from ..components.share_document import (
    Align,
    Cell,
    Column,
    Facts,
    Icon,
    IconKind,
    Notes,
    ShareDocument,
    Table,
    Tone,
    file_stem,
)
from ..formatting import (
    MIXED_WEATHER_LABEL,
    compound_for_lap,
    estimate_points,
    format_grid,
    format_grid_penalty,
    format_lap_gap,
    format_lap_time,
    format_penalty_badge,
    format_position_change,
    is_race,
    race_result,
    recorded_label,
    session_best_lap_ms,
    session_fastest_lap,
    slot_label,
    track_air_temp_label,
    weather_label,
)
from .race_control import grid_penalty_places, summarise_penalties

# The page's columns in the page's order (``build_classification_table``), plus the one each layout
# gains because an image cannot flip a cell: a race's PEN and a best-lap session's GRID PENALTY.
_RACE_COLUMNS = (
    Column("POS", Align.RIGHT), Column("", Align.CENTER), Column("DRIVER", wrap=True),
    Column("TEAM", wrap=True), Column("GRID", Align.RIGHT), Column("STOPS", Align.RIGHT),
    Column("BEST", Align.RIGHT), Column("TIME", Align.RIGHT), Column("PEN"),
    Column("PTS", Align.RIGHT))
_RACE_PENALTY_COLUMN = 8
_BEST_LAP_COLUMNS = (
    Column("POS", Align.RIGHT), Column("DRIVER", wrap=True), Column("TEAM", wrap=True),
    Column("TYRE", Align.CENTER), Column("BEST", Align.RIGHT), Column("GAP", Align.RIGHT),
    Column("GRID PENALTY"))
_GRID_PENALTY_COLUMN = 6
_PENALTY_COLUMNS = (
    Column("LAP", Align.RIGHT), Column("DRIVER", wrap=True), Column("OUTCOME", wrap=True),
    Column("REASON", wrap=True))

_CHANGE_TONES = {"gain": Tone.GAIN, "loss": Tone.LOSS}

_RECONSTRUCTED_NOTE = ("Rebuilt from telemetry: the game sent no final classification for this "
                       "session, so the order may differ from the game's")
_ESTIMATES_CLAUSE = " and points marked ~ are estimates"


def session_document(session, slot, penalties=(), name_of=lambda entry: entry.driver_name,
                     placement: tuple[str, int] | None = None) -> ShareDocument:
    """One session as its image: the header facts, the final classification and race control.

    ``slot`` is the session's weekend slot (``domain.season.slot_for_session``), the only thing that
    tells a Sprint Race from the Grand Prix. ``penalties`` are its stored ``PENA`` rows, as
    ``EventStore.load_penalties`` returns them. ``name_of`` is the resolver the page names drivers
    with. ``placement`` is ``(season, round number)`` when the session is assigned to a round, the
    season already named as ``components.season_phrase`` names it.

    The file name leads with the date and time the session was recorded - the one thing that tells
    two attempts at a slot apart, so the app never has to number them (core invariant #5).
    """
    label = slot_label(slot.session_type, slot.is_sprint_race)
    track = track_name(session.track_id)
    recorded = recorded_label(session.recorded_at) if session.recorded_at is not None else ""
    meta = [placement[0], f"Round {placement[1]}"] if placement is not None else []
    if recorded:
        meta.append(recorded)
    return ShareDocument(
        title=f"{track} — {label}",
        name=file_stem(*recorded.replace(":", "").split(), track, label),
        meta="  ·  ".join(meta),
        blocks=(_facts(session, name_of),
                _classification(session, slot, label, penalties, name_of),
                _race_control(session, penalties, name_of)),
        footer=f"f1telemetry v{__version__}")


# --- the blocks ------------------------------------------------------------------------------------
def _facts(session, name_of) -> Facts:
    """What the session was: its fastest lap, a race's distance, its weather and temperatures."""
    pairs = []
    fastest = session_fastest_lap(session, name_of)
    if fastest is not None:
        pairs.append(("Fastest lap", Cell(fastest, Tone.FASTEST)))
    if is_race(session.session_type) and session.total_laps > 0:
        # A race's distance. ``total_laps`` means nothing outside a race - a practice session
        # reports 1 against the 7 laps actually run (``formatting.laps_completed_label``).
        pairs.append(("Laps", Cell(str(session.total_laps))))
    weather = MIXED_WEATHER_LABEL if session.is_mixed_weather else weather_label(session.weather)
    pairs.append(("Weather", Cell(weather)))
    temperatures = track_air_temp_label(session)
    if temperatures is not None:
        pairs.append(("Track / air", Cell(temperatures)))
    return Facts(tuple(pairs))


def _classification(session, slot, label: str, penalties, name_of) -> Table:
    """The final classification, laid out as the page lays it out for this kind of session."""
    entries = session.classification.entries if session.classification else ()
    reconstructed = session.classification is not None and session.classification.is_reconstructed
    # ``build_classification_table``'s own winner and fastest-lap rules, so the image measures every
    # gap from the same car and paints the same lap blue.
    winner = next((e for e in entries if e.position == 1), entries[0] if entries else None)
    fastest_ms = session_best_lap_ms(session)
    race = is_race(session.session_type)
    if race:
        columns, optional = _RACE_COLUMNS, _RACE_PENALTY_COLUMN
        rows = [_race_row(entry, winner, fastest_ms, reconstructed, slot.is_sprint_race, name_of)
                for entry in entries]
    else:
        places = grid_penalty_places(penalties)
        columns, optional = _BEST_LAP_COLUMNS, _GRID_PENALTY_COLUMN
        rows = [_best_lap_row(entry, winner, fastest_ms, places, name_of) for entry in entries]
    if not any(row[optional].text for row in rows):
        columns = columns[:optional] + columns[optional + 1:]
        rows = [row[:optional] + row[optional + 1:] for row in rows]
    note = ""
    if reconstructed:
        note = _RECONSTRUCTED_NOTE + (_ESTIMATES_CLAUSE if race else "") + "."
    return Table(columns, tuple(rows), title=f"Final classification · {label}", note=note)


def _race_control(session, penalties, name_of) -> Table | Notes:
    """The Race control box in whichever of its three states applies.

    ``summarise_penalties`` decides every word, exactly as it does for the page; this lays it out.
    """
    entries = session.classification.entries if session.classification else ()
    summary = summarise_penalties(penalties, entries, name_of)
    title = f"Race control · {summary.heading}"
    if not summary.rows:
        # The page's order: a line per penalised driver, then the muted note beneath them.
        return Notes(tuple(Cell(line) for line in summary.aggregates)
                     + (Cell(summary.note, Tone.MUTED),), title=title)
    return Table(_PENALTY_COLUMNS, tuple(_penalty_row(row) for row in summary.rows),
                 title=title, note=summary.note)


# --- the rows --------------------------------------------------------------------------------------
def _race_row(entry, winner, fastest_ms, reconstructed: bool, is_sprint_race: bool,
              name_of) -> tuple[Cell, ...]:
    glyph, kind = format_position_change(entry.grid_position, entry.position)
    badge = format_penalty_badge(entry.num_penalties, entry.penalties_time_s)
    return (Cell(str(entry.position)),
            Cell(glyph, _CHANGE_TONES.get(kind, Tone.PLAIN), strong=True),
            _driver(entry, name_of),
            Cell(team_display_name(entry.team_id)),
            Cell(format_grid(entry.grid_position)),
            Cell(str(entry.num_pit_stops)),
            _best_lap(entry, fastest_ms),
            Cell(race_result(entry, winner)),
            # The badge the page flips a finisher's TIME cell to - and only a finisher's, as there.
            Cell(badge if badge and entry.result_status == ResultStatus.FINISHED else ""),
            _points(entry, reconstructed, is_sprint_race))


def _best_lap_row(entry, winner, fastest_ms, places: dict[int, int], name_of) -> tuple[Cell, ...]:
    compound = compound_for_lap(entry.tyre_stints, entry.best_lap_num)
    # A grid penalty is served in the race, so as on the page it sits beside the gap and not the lap.
    grid_penalty = format_grid_penalty(places.get(entry.vehicle_index, 0))
    return (Cell(str(entry.position)),
            _driver(entry, name_of),
            Cell(team_display_name(entry.team_id)),
            Cell(icon=Icon(IconKind.TYRE, compound)) if compound is not None else Cell(),
            _best_lap(entry, fastest_ms),
            Cell(format_lap_gap(entry, winner)),
            Cell(grid_penalty or ""))


def _penalty_row(row) -> tuple[Cell, ...]:
    """One penalty, weighted as the page weights it: a human driver, and a penalty that counts."""
    flag = Icon(IconKind.FLAG, row.nationality_id) if row.nationality_id is not None else None
    return (Cell(str(row.lap_number)),
            Cell(row.driver, strong=row.is_human, icon=flag),
            Cell(row.outcome, strong=row.is_sporting),
            Cell(row.reason))


def _driver(entry, name_of) -> Cell:
    return Cell(name_of(entry), icon=Icon(IconKind.FLAG, entry.nationality_id))


def _best_lap(entry, fastest_ms: int | None) -> Cell:
    fastest = bool(fastest_ms) and entry.best_lap_time_ms == fastest_ms
    return Cell(format_lap_time(entry.best_lap_time_ms), Tone.FASTEST if fastest else Tone.PLAIN)


def _points(entry, reconstructed: bool, is_sprint_race: bool) -> Cell:
    """The points the game awarded - or, with no Final Classification to award them, the page's
    muted estimate, blank for a car that did not finish."""
    if not reconstructed:
        return Cell(str(entry.points))
    estimate = estimate_points(entry.position, entry.result_status, is_sprint_race)
    return Cell("" if estimate is None else f"~{estimate}", Tone.MUTED)
