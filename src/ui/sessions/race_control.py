"""What race control did to a session, as rows a widget can render - Qt-free, so the rules are
unit-testable the way ``tyre_stints`` is.

Turns the ``PENA`` rows ``EventStore.load_penalties`` returns into one line each. Everything that
decides *text* lives here - the wording, the ordering, the three states and the driver join - and
the widget only sets labels.

**Field-wide, and every row names its driver** (DECISIONS -> UI). The whole field's penalties are
what a league reader opens the page for, and the alternative was measured before it was rejected:
filtering to non-AI cars drops 54 of the 129 rows in this database, is *identical to player-only*
in 35 of 42 penalised sessions - because 34 of them have one human in the field - and empties four
boxes that had 8, 6, 3 and 1 penalties in them. A box reading "no penalties" over a race that
issued eight is exactly the failure the honesty rule below exists to prevent.

The join is ``classification.entries`` by ``vehicle_index``, and it is the only join available:
``SessionStore`` does not persist ``participants``. It resolves 129 of 129 rows here, including the
seven penalised sessions whose classification was reconstructed from telemetry. A row that cannot
be resolved still renders, as ``Car 14`` - dropping a penalty because its driver is unknown is the
silent loss this whole feature exists to undo.

**Three states, because an empty read is not a clean session.** ``SessionResult.penalties`` is
empty for every session ingested before ``PIPELINE_VERSION`` 5, so emptiness means "not captured"
and never "nothing happened" - the domain model says so outright. Rows present are listed; no rows
*but* a classification that records a penalty is the honest contradiction, and says the detail has
not been read yet; only when neither has anything does the box speak, and even then it speaks about
the store rather than about the session.

**Two textual rules keep the game from contradicting itself**, and both are stated rather than
hidden: an invalidation's name loses its trailing "without reason", which is the game's HUD wording
for "no reason shown to the driver" and reads as a denial of the reason printed beside it; and an
infringement that repeats the penalty's own words loses the repeat, so ``Retired`` +
``Retired mechanical failure`` is one statement rather than two. Every tooltip carries both names
exactly as the game sent them, so nothing tidied here is lost.

**The second car is named whenever the game gave one, and the data decides that, not a list of
infringements.** ``other_vehicle_index`` is all-or-nothing per infringement: present on 44 of 44
Small Collisions, 1 of 1 Big Collision and 3 of 3 Blocking rows, absent on all 81 rows of every
other kind, resolving to a classification entry 48 of 48 times and never naming the car itself. So
a reason that carries one reads "... with <driver>" and every other reason is untouched, with no
type test in between.

Order is the store's - lap, then frame - and is not re-derived. Replay-recovered rows carry
``frame = 0`` and sort first within their lap, which is the only ordering they can offer; 2 of the
129 rows here are such rows and they need no display special case.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from ...protocol.reference import infringement_name, penalty_name
from ..formatting import format_penalty_badge

_EM_DASH = "\u2014" # em dash
_MIDDLE_DOT = "\u00b7" # middle dot

# Types 12, 13 and 15 append this to an otherwise identical name (10, 11, 14). The game means "the
# driver was shown no reason", not "there is no reason" - and the row prints the reason.
_WITHOUT_REASON = re.compile(r"\s+without reason$", re.IGNORECASE)

_NOT_APPLICABLE = "not applicable"

# Penalty type 2. Grid places are summed off these rows rather than read from the classification,
# which counts penalties and not places - see ``grid_penalty_places``.
_GRID_PENALTY = 2

# The three states' muted lines. The last one is deliberately a claim about the *store*: a session
# ingested before PIPELINE_VERSION 5 holds no rows and cannot be told apart from a clean one.
_COUNTED_NOTE = "{count} counted towards the classification."
_NOT_READ_NOTE = "Penalty detail hasn't been read from this session's capture yet."
_NONE_STORED_NOTE = "No penalties are stored for this session."

_HEADING = "Penalties"


@dataclass(frozen=True)
class PenaltyRow:
    """One penalty as three cells and a tooltip - everything the widget needs and nothing else.
    
    ``outcome`` and ``reason`` are separate because they are separate columns: what race control
    did, and what it did it for. Splitting them lets the outcome column stay narrow while the
    reason takes the slack, which is what makes 70 warnings scannable rather than a wall.
    """

    lap_number: int
    driver: str                 # the entry's shown name, or ``Car 14`` when it cannot be resolved
    nationality_id: int | None  # for the flag the classification table already shows; None if unresolved
    outcome: str                # e.g. "Warning", "Time penalty, +5 s", "Grid penalty, 5 places"
    reason: str                 # e.g. "Small Collision with Max Verstappen"; "" when it adds nothing
    is_sporting: bool           # the subset the classification counts; the widget bolds it
    is_human: bool              # not AI-controlled; the widget bolds the driver cell
    tooltip: str


@dataclass(frozen=True)
class PenaltySummary:
    """A session's penalties half of the Race control box, in whichever of its three states applies.

    ``rows`` and ``aggregates`` are mutually exclusive by construction: rows are listed whenever
    there are any, so a session with stored penalties can never fall through to an empty state.
    """

    note: str       # the muted line under the heading; always present
    rows: tuple[PenaltyRow, ...] = ()
    aggregates: tuple[str, ...] = ()  # per-driver badge lines, when only the total is known
    sporting_count: int = 0

    @property
    def total(self) -> int:
        """How many penalties this session stored."""
        return len(self.rows)

    @property
    def heading(self) -> str:
        """The section heading, counting the rows it is actually about.

        The count is a ``len()`` over the very rows below it, never a stored aggregate - the same
        rule DECISIONS sets for the overtake counts, and for the same reason: a heading and the
        list under it must not be able to disagree.
        """
        return f"{_HEADING} ({self.total})" if self.rows else _HEADING


def summarise_penalties(penalties: Sequence, entries: Sequence = ()) -> PenaltySummary:
    """A session's penalties as the box should show them.

    ``penalties`` are ``SessionPenalty`` rows in ``EventStore.load_penalties`` order, and
    ``entries`` are the session's ``ClassificationEntry`` rows, used to name the cars and to tell
    an AI apart from a human. Both are allowed to be empty, and each emptiness means something
    different: no penalties is one of the three states below, while no entries only costs the rows
    their names.
    """
    by_index = {entry.vehicle_index: entry for entry in entries}

    if penalties:
        rows = tuple(_row(penalty, by_index) for penalty in penalties)
        sporting = sum(1 for row in rows if row.is_sporting)
        return PenaltySummary(note=_COUNTED_NOTE.format(count=sporting),
                                rows=rows, sporting_count=sporting)

    aggregates = _aggregate(entries)
    if aggregates:
        return PenaltySummary(note=_NOT_READ_NOTE, aggregates=aggregates)
    return PenaltySummary(note=_NONE_STORED_NOTE)


def grid_penalty_places(penalties: Sequence) -> dict[int, int]:
    """How many grid places each car was penalised in this session, by ``vehicle_index``.

    Summed over the car's grid-penalty rows, because the game issues them one at a time: in
    ``972807263...`` (a league Q1) two cars each took **two** 5-place penalties and start ten
    places back, which the classification's ``num_penalties`` records only as "2". Places are the
    fact a reader wants and the count is not - one 10-place penalty and two 5-place ones put the
    car in the same slot.

    Every grid penalty in this database is issued in a qualifying session and none in a race, which
    is why this feeds the non-race half of the classification table; the race half already
    alternates its TIME cell with the seconds a time penalty added.
    """
    places: dict[int, int] = {}
    for penalty in penalties:
        if penalty.penalty_type == _GRID_PENALTY and penalty.places_gained:
            places[penalty.vehicle_index] = (places.get(penalty.vehicle_index, 0) + penalty.places_gained)
    return places


# --- one row ---------------------------------------------------------------------------------
def _row(penalty, by_index: dict) -> PenaltyRow:
    entry = by_index.get(penalty.vehicle_index)
    driver = _driver_label(penalty.vehicle_index, entry)
    other = _other_driver(penalty, by_index)
    return PenaltyRow(
        lap_number=penalty.lap_number,
        driver=driver,
        nationality_id=getattr(entry, "nationality_id", None),
        outcome=_outcome(penalty),
        reason=_reason(penalty, other),
        is_sporting=penalty.is_sporting,
        # Unresolved reads as not-human: the bold says "the game called this car human", and an
        # answer we don't have must not be asserted.
        is_human=entry is not None and not entry.is_ai,
        tooltip=_tooltip(penalty, driver, other))


def _other_driver(penalty, by_index: dict) -> str | None:
    """The other car in the incident, named, or None when the game did not give one.

    No infringement test: the packet's own 255 sentinel already decides it, and it decides cleanly
    - see the module docstring for the 48-of-48 measurement.
    """
    index = penalty.other_vehicle_index
    if index is None:
        return None
    return _driver_label(index, by_index.get(index))


def _driver_label(vehicle_index: int, entry) -> str:
    """The car's shown name, or ``Car 14``.

    The blank check is not defensive padding: a classification row can carry an empty shown name
    (``domain.roster`` treats "" and "Player" as generic), and an empty cell would read as a
    rendering fault rather than as a driver the game declined to name.
    """
    name = (getattr(entry, "driver_name", "") or "").strip() if entry is not None else ""
    return name or f"Car {vehicle_index}"


def _outcome(penalty) -> str:
    """What race control did, with what it cost attached to it."""
    name = _WITHOUT_REASON.sub("", penalty_name(penalty.penalty_type))
    qualifier = _qualifier(penalty)
    return f"{name}, {qualifier}" if qualifier else name


def _qualifier(penalty) -> str:
    """The added time and the places lost, when the game gave either.

    ``places_gained`` is legitimately ``0`` in 75 of the 129 rows here and ``None`` in 47, and the
    two are different facts: "gained no places" against "does not apply to this penalty". Neither
    earns a clause on the row - a warning that cost nothing should not say so eleven times in one
    box - and the tooltip is where they stay told apart, spelled out rather than implied.
    """
    parts = []
    if penalty.time_s is not None:
        parts.append(f"+{penalty.time_s} s")
    if penalty.places_gained not in (None, 0):
        places = penalty.places_gained
        parts.append(f"{places} place" if places == 1 else f"{places} places")
    return ", ".join(parts)


def _reason(penalty, other: str | None = None) -> str:
    """The infringement, minus any repeat of the words the penalty has already said, plus the other
    car when the game named one.

    ``Retired`` + ``Retired mechanical failure`` is the case that forces the de-duplication - 19
    rows here - and the rule is a prefix test rather than a table of pairs, so ``Black flag timer``
    against the identically named infringement collapses to one statement too. The remainder has to
    start on a word boundary, or a short penalty name could chop an unrelated infringement mid-word.

    "with" is right for the 45 collision rows that carry a second car and merely serviceable for
    the 3 blocking ones, where the other car is the one *being* blocked. A second connector for
    three rows would be a special case earning less than it costs.
    """
    raw = infringement_name(penalty.infringement_type)
    lead = penalty_name(penalty.penalty_type)
    rest = raw[len(lead):]
    if raw.casefold().startswith(lead.casefold()) and (not rest or rest[:1].isspace()):
        raw = rest.strip()
    return f"{raw} with {other}" if (raw and other) else raw


def _tooltip(penalty, driver: str, other: str | None = None) -> str:
    """The whole fact, including the three fields the row leaves off or tidies.

    Both names are the game's own, untidied: the row is where the wording is made to read, and this
    is where what the game actually sent stays recoverable.
    """
    return "\n".join((
        f"Lap {penalty.lap_number} {_MIDDLE_DOT} {driver}",
        f"{penalty_name(penalty.penalty_type)} {_EM_DASH} "
        f"{infringement_name(penalty.infringement_type)}",
        f"Other car: {other if other is not None else _NOT_APPLICABLE}",
        f"Places gained: {_NOT_APPLICABLE if penalty.places_gained is None else penalty.places_gained}",
        f"Added time: {_NOT_APPLICABLE if penalty.time_s is None else f'{penalty.time_s} s'}",
        f"Counted towards the classification: {'yes' if penalty.is_sporting else 'no'}",
    ))


# --- the state where only the total survived ------------------------------------------------
def _aggregate(entries: Sequence) -> tuple[str, ...]:
    """One badge line per driver the classification says was penalised, in finishing order.

    ``format_penalty_badge`` is the classification table's own badge, called exactly as that table
    calls it, so the two surfaces cannot word the same fact differently.
    """
    lines = []
    for entry in entries:
        badge = format_penalty_badge(entry.num_penalties, entry.penalties_time_s)
        if badge:
            lines.append(f"{_driver_label(entry.vehicle_index, entry)} {_EM_DASH} {badge}")
    return tuple(lines)
