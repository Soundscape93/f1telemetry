"""A season's standings as a ``ShareDocument`` - what the season page and the weekend page export
(E19). Qt-free, so every string the image says about a championship is unit-tested the way
``race_control``'s are.

**Here rather than under a surface, because two surfaces ask for it.** The season page shares the
standings as they stand; the weekend page shares them *as of its round*, beside that weekend's
sessions. Seasons must not import from ``sessions/``, and nothing under ``components/`` may import
a surface package at all - so the one builder both want lives beside the model it builds.

**As of round N is a slice, not a second computation.** ``rounds_with_results`` hands back one
entry per calendar round in order, and every helper in ``analysis.standings`` flattens rounds into
sessions - so dropping the rounds after N is the whole of it, and the totals are the same code that
paints the season page.

**One rule for which standings apply.** ``driver_standings`` is the only place that chooses between
the roster-grouped league table and the plain by-name one, and the season page calls it for its own
table too. Two copies of that choice would be a table and an image that can disagree about the same
season, which is precisely what an exported result must never do (core invariant #7 is why the
league branch groups by roster session keys rather than by race number).

**It says what it could not count.** Standings skip a race the game sent no final classification
for - those points are not derivable, so a reconstructed race contributes nothing. On the page that
is invisible; in a photo it would read as a driver having had a bad weekend. So the count of rounds
that actually scored is on the meta line, and a race that was skipped is named under the table.

**The season is handed in already named.** ``components.season_phrase`` lives beside a
``QMessageBox``, and importing it here would put Qt in a module the suite loads - the same reason
``session_share`` takes its ``placement`` pre-named rather than deriving it.
"""
from __future__ import annotations

from ...analysis.standings import (
    constructor_standings_for_rounds,
    league_standings_for_rounds,
    standings_for_rounds,
)
from ...protocol.enums import RACE_SESSION_TYPES
from ...protocol.reference import team_display_name, track_name
from ...version import __version__
from .share_document import (
    Align,
    Cell,
    Column,
    Icon,
    IconKind,
    Notes,
    ShareDocument,
    Table,
    Tone,
    file_stem,
)

# The season page's own columns, in the season page's order.
_DRIVER_COLUMNS = (
    Column("POS", Align.RIGHT), Column("DRIVER", wrap=True), Column("NO.", Align.RIGHT),
    Column("POINTS", Align.RIGHT))
_CONSTRUCTOR_COLUMNS = (
    Column("POS", Align.RIGHT), Column("TEAM", wrap=True), Column("POINTS", Align.RIGHT))

_NOTHING_SCORED = ("No round has scored points yet - standings count only a race the game sent a "
                   "final classification for.")


def driver_standings(rounds, roster=None):
    """The driver standings for these rounds: the league table when there is a roster, else by name.

    The one place that choice is made. A league groups by ``roster.session_keys`` - a whole
    classification at a time - because a race number is unique only among humans and the AI field
    runs the real-world ones (core invariant #7), so a per-entry number would sum an AI into a
    member's row. The season page renders this and the image is built from it, so the two cannot
    disagree about the same season.
    """
    if roster is None:
        return standings_for_rounds(rounds)
    return league_standings_for_rounds(rounds, roster)


def standings_document(season, rounds, season_name: str, roster=None,
                       through: int | None = None) -> ShareDocument:
    """A season's standings as its image: the drivers' table, then the constructors'.

    ``rounds`` is the season's whole calendar as ``rounds_with_results`` returns it - never a slice
    the caller made, because the meta line counts against its length. ``season_name`` is the season
    as ``components.season_phrase`` names it, handed in so this module stays Qt-free.
    ``through`` is the round the standings are taken as of, or None for everything stored.

    The file name leads with the season rather than a date, since standings are of a championship
    and not of a moment; a second export of the same round is numbered by ``unique_path``.
    """
    counted = _through(rounds, through)
    drivers = driver_standings(counted, roster)
    constructors = constructor_standings_for_rounds(counted)
    skipped = _skipped_note(counted)
    where = f" after round {through}" if through is not None else ""
    return ShareDocument(
        title=f"{season_name} — Standings{where}{_at(rounds, through)}",
        name=file_stem(f"Season {season.number}", season.nickname or "",
                       f"Standings round {through}" if through is not None else "Standings"),
        meta=f"{_scoring(counted)} of {len(rounds)} rounds counted",
        blocks=_blocks(drivers, constructors, skipped),
        footer=f"f1telemetry v{__version__}")


# --- the blocks ------------------------------------------------------------------------------------
def _blocks(drivers, constructors, skipped: str) -> tuple:
    """The two tables - or, with nothing to rank, one line saying so rather than two empty grids.

    A heading over nothing is a legal table, but an image of two of them says less than a sentence
    does, and this is a real state: a round whose race has not been driven yet.
    """
    if not drivers and not constructors:
        lines = (Cell(_NOTHING_SCORED),) + ((Cell(skipped, Tone.MUTED),) if skipped else ())
        return (Notes(lines, title="Standings"),)
    return (_driver_table(drivers, skipped), _constructor_table(constructors))


def _driver_table(drivers, note: str) -> Table:
    """Every driver with their flags, their number, and their total - the page's own columns."""
    return Table(_DRIVER_COLUMNS,
                 tuple((Cell(str(row.position)),
                        Cell(row.driver_name, icon=Icon(IconKind.FLAG, row.nationality_id)),
                        Cell(str(row.race_number)),
                        Cell(str(row.points), strong=True)) for row in drivers),
                 title="Drivers", note=note)


def _constructor_table(constructors) -> Table:
    """Teams named as the page names them - ``team_display_name``, so "Ferrari '26" reads as Ferrari."""
    return Table(_CONSTRUCTOR_COLUMNS,
                 tuple((Cell(str(row.position)),
                        Cell(team_display_name(row.team_id)),
                        Cell(str(row.points), strong=True)) for row in constructors),
                    title="Constructors")


# --- what the rounds say -------------------------------------------------------------------------------------
def _through(rounds, through: int | None) -> tuple:
    """The rounds the standings are taken over: everything, or everything up to and including N."""
    if through is None:
        return rounds
    return tuple(round for round in rounds if round.round_number <= through)


def _scoring(rounds) -> int:
    """How many of these rounds put points on the board - ``compute_standings``'s own test."""
    return sum(1 for round in rounds if any(_scored(session) for session in round.sessions))


def _skipped_note(rounds) -> str:
    """What the totals had to leave out, or nothing when they left nothing out.

    Invisible on the page, where a race that awarded no points simply is not there. In a photo the
    same silence reads as a driver having had a bad weekend, so it is said instead.
    """
    races = sum(1 for round in rounds for session in round.sessions if _reconstructed(session))
    if not races:
        return ""
    if races == 1:
        return ("One race is missing from these totals: the game sent no final classification for "
                "it, so it awarded no points.")
    return (f"{races} races are missing from these totals: the game sent no final classification "
            "for them, so they awarded no points.")


def _scored(session) -> bool:
    """A race whose points the standings counted."""
    return (session.session_type in RACE_SESSION_TYPES and session.classification is not None
            and not session.classification.is_reconstructed)


def _reconstructed(session) -> bool:
    """A race the standings had to skip: rebuilt from telemetry, so its points are not derivable."""
    return (session.session_type in RACE_SESSION_TYPES and session.classification is not None
            and session.classification.is_reconstructed)


def _at(rounds, through: int | None) -> str:
    """" (Suzuka)" - which track that round was, or nothing when the round is not on the calendar."""
    if through is None:
        return ""
    round = next((r for r in rounds if r.round_number == through), None)
    return "" if round is None else f" ({track_name(round.track_id)})"
