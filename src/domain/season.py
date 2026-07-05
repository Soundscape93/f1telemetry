"""Season-layer domain models - user-authored championship configuration.

Unlike everything else in the domain layer, these don't come out of a capture: a Season is something
the user creates, and captured sessions get assigned ont its round. ``SeasonMode``is the user's own
organizing categorazation, intentionally separate from the game's ``game_mode``(which is more granular
and doesn't map one-to-one - a league weekend reports as an online custom lobby, not "league").
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Sequence

from ..protocol.enums import RACE_SESSION_TYPES, SessionType, safe_enum
from .models import SessionResult

# Raw session-type ints that race for championship points. Both the Sprint Race and the Grand
# Prix report RACE (15); they are told apart by position in the weekend, not by this value.
_RACE_TYPE_VALUES = frozenset(int(t) for t in RACE_SESSION_TYPES)


def _is_race_type(session_type) -> bool:
    """Whether a session type (enum or raw int) uses the race format (Sprint Race or Grand Prix)."""
    return int(session_type) in _RACE_TYPE_VALUES


class SeasonMode(IntEnum):
    """How the user organizes a season. Not the game's mode."""

    MY_TEAM = 0
    DRIVER_CAREER = 1
    GRAND_PRIX = 2
    LEAGUE = 3


@dataclass(frozen=True)
class SeasonRound:
    """One round in a season's calendar; an ordingal and the track it's run at."""

    round_number: int
    track_id: int


@dataclass(frozen=True)
class Season:
    """A user-authored championship: a mode, a number, an optional nichname, and an ordered
    calendar of rounds, pinned to one game format (the  'all tracks' calendar differs by
    format). ``season_id``is none unit the season has been persisted.
    """

    mode: SeasonMode
    number: int
    game_format: int
    nickname: str | None = None
    rounds: tuple[SeasonRound, ...] = ()
    season_id: int | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class RoundResults:
    """A round paired with the captured sessions assigned to it. Each session carries its own
    ``session_type`` (Q1, Q2, Q3, SQ1, SQ2, SQ3, Sprint, Race, ect...) and classification, so
    this is all the season view needs to render a weekend.
    """

    round_number: int
    track_id: int
    sessions: tuple[SessionResult, ...] = ()


@dataclass(frozen=True)
class WeekendSlot:
    """One position in a weekend's session sequence - captured or still pending.

    A weekend is more than the sessions we happened to capture: the game's ``weekend_structure``
    lists every session in running order (Practice -> Sprint Shootouts -> Sprint Race ->
    Qualifying -> Race for a sprint weekend). A ``WeekendSlot`` is one of those positions, with
    the captured ``SessionResult`` if we have it or ``None`` if it's still pending.

    ``is_sprint_race`` / ``is_grand_prix`` resolve the ambiguity raw ``session_type`` can't: both
    races report ``SessionType.RACE`` (15), and only their position in the weekend tells them
    apart. ``is_grand_prix`` marks the weekend's *final* race - the one the calendar Results
    column and the "Race pending" state care about.
    """

    order: int                              # position in the weekend, 0-based
    session_type: SessionType | int
    session: SessionResult | None = None
    is_sprint_race: bool = False
    is_grand_prix: bool = False


def _weekend_structure(sessions: Sequence[SessionResult]) -> tuple[int, ...]:
    """The weekend's session-type sequence, taken from whichever captured session carries it.

    Every session in a weekend reports the same ``weekend_structure``; we take the longest one
    present to be robust to the odd empty/legacy row. Returns ``()`` when nothing carries it
    (rows saved before the field existed), which drops callers onto the link-id fallback.
    """
    structures = [s.weekend_structure for s in sessions if s.weekend_structure]
    return max(structures, key=len) if structures else ()


def _slots_from_structure(
    ordered: list[SessionResult], structure: tuple[int, ...]
) -> list[WeekendSlot]:
    """Align captured sessions onto the game-reported weekend structure.

    ``ordered`` is the weekend's captured sessions sorted by ``session_link_id`` (their true
    running order). Non-race session types are unique within a weekend, so they map straight to
    their structure index; the (possibly two) race-type sessions map onto the race positions in
    order, so the earlier-recorded race takes the Sprint slot and the later one the Grand Prix.
    Uncaptured positions become pending slots (``session=None``).
    """
    type_counts = Counter(structure)
    first_index_of: dict[int, int] = {}
    for i, t in enumerate(structure):
        first_index_of.setdefault(t, i)

    race_positions = [i for i, t in enumerate(structure) if _is_race_type(t)]
    gp_index = race_positions[-1] if race_positions else None

    assigned: dict[int, SessionResult] = {}
    race_sessions = [s for s in ordered if _is_race_type(s.session_type)]
    for session in ordered:
        raw = int(session.session_type)
        if _is_race_type(raw):
            continue                                 # placed together, in order, below
        if type_counts[raw] == 1:
            assigned[first_index_of[raw]] = session
    for session, position in zip(race_sessions, race_positions):
        assigned[position] = session

    return [
        WeekendSlot(
            order=i,
            session_type=safe_enum(SessionType, t),
            session=assigned.get(i),
            is_sprint_race=_is_race_type(t) and i != gp_index,
            is_grand_prix=i == gp_index,
        )
        for i, t in enumerate(structure)
    ]


def _slots_from_link_order(ordered: list[SessionResult]) -> list[WeekendSlot]:
    """Fallback slots for legacy rows without a stored ``weekend_structure``.

    Uses only ``session_link_id`` order: the Grand Prix is the weekend's final session when that
    session is a race; any earlier race-type session is therefore a Sprint. If the final captured
    session isn't a race (e.g. only the Sprint + Qualifying are in), the Grand Prix is pending and
    no slot is marked ``is_grand_prix``.
    """
    final = ordered[-1] if ordered else None
    gp = final if final is not None and _is_race_type(final.session_type) else None
    return [
        WeekendSlot(
            order=i,
            session_type=session.session_type,
            session=session,
            is_sprint_race=_is_race_type(session.session_type) and session is not gp,
            is_grand_prix=session is gp,
        )
        for i, session in enumerate(ordered)
    ]


def weekend_slots(sessions: Sequence[SessionResult]) -> list[WeekendSlot]:
    """The ordered slots for one weekend's captured sessions.

    Sorts by ``session_link_id`` (the true running order) and, when the game-reported
    ``weekend_structure`` is available, returns a slot for every session in the weekend -
    captured or pending - with the Sprint Race and Grand Prix correctly distinguished. Pass the
    sessions of a single weekend (same ``weekend_link_id``); mixing weekends is not meaningful.
    """
    ordered = sorted(sessions, key=lambda s: s.session_link_id)
    structure = _weekend_structure(ordered)
    if structure:
        return _slots_from_structure(ordered, structure)
    return _slots_from_link_order(ordered)


def grand_prix_session(sessions: Sequence[SessionResult]) -> SessionResult | None:
    """The captured Grand Prix (final race) for a weekend, or None if it isn't captured yet.

    This is what the calendar Results column shows - never a Sprint Race. Returns None both when
    no race is captured and when only a Sprint (with the Grand Prix still pending) is.
    """
    for slot in weekend_slots(sessions):
        if slot.is_grand_prix and slot.session is not None:
            return slot.session
    return None


def slot_for_session(
    session: SessionResult, siblings: Sequence[SessionResult]
) -> WeekendSlot:
    """Resolve one session's slot within its weekend, given the pool of known sessions.

    ``siblings`` is any collection that includes the session's weekend-mates (e.g. the whole
    store); it's filtered to the matching ``weekend_link_id``. Lets an isolated view - the
    capture picker - label a Sprint Race correctly. Falls back to a bare slot if the session's
    weekend can't be reconstructed.
    """
    weekend = [s for s in siblings if s.weekend_link_id == session.weekend_link_id]
    for slot in weekend_slots(weekend):
        if slot.session is not None and slot.session.session_uid == session.session_uid:
            return slot
    return WeekendSlot(order=0, session_type=session.session_type, session=session)