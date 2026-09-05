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


def _recorded_order(session: SessionResult) -> tuple[bool, float]:
    """Sort key ordering a slot's repeat attempts by capture time, tolerating rows without one.

    ``recorded_at`` is optional, so unstamped rows sort first and keep their incoming order (the
    sort is stable). The time is compared as a float rather than as a ``datetime`` because every
    stored row reads back naive while ``SessionStore.save`` stamps an aware UTC one when a result
    carries none - comparing the two raises ``TypeError``.
    """
    recorded = session.recorded_at
    return (recorded is not None, recorded.timestamp() if recorded is not None else 0.0)


class SeasonMode(IntEnum):
    """How the user organizes a season. Not the game's mode."""

    MY_TEAM = 0
    DRIVER_CAREER = 1
    GRAND_PRIX = 2
    LEAGUE = 3


# Season modes driven against other people, so they resolve standings through a hand-maintained
# roster (online names + race numbers). LEAGUE is the game's League Racing; GRAND_PRIX covers
# multiplayer GP lobbies - used for 2026 leagues, whose DLC cars aren't available in League Racing.
# The solo career modes (MY_TEAM, DRIVER_CAREER) race fixed-identity AI and never need a roster.
ROSTER_SEASON_MODES = frozenset({SeasonMode.LEAGUE, SeasonMode.GRAND_PRIX})


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
    Qualifying -> Race for a sprint weekend). A ``WeekendSlot`` is one of those positions, holding
    every captured attempt at it - or nothing at all while the slot is still pending.

    ``sessions`` is a tuple because a slot can hold more than one: a restarted or re-driven session
    keeps the same season, weekend and session link ids, the same ``session_type`` and the same
    track as the attempt it replaces, and only ``session_uid`` and ``recorded_at`` differ. They are
    ordered by ``recorded_at``, and **the app never picks one of them** - which attempt "counts" is
    a judgement about that session, not a fact in the telemetry. See DECISIONS -> UI.

    ``is_sprint_race`` / ``is_grand_prix`` resolve the ambiguity raw ``session_type`` can't: both
    races report ``SessionType.RACE`` (15), and only their position in the weekend tells them
    apart. ``is_grand_prix`` marks the weekend's *final* race - the one the calendar Results
    column and the "Race pending" state care about.
    """

    order: int                              # position in the weekend, 0-based
    session_type: SessionType | int
    sessions: tuple[SessionResult, ...] = ()    # every attempt, recorded order; () = pending
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


def _slots_from_structure(ordered: list[SessionResult], structure: tuple[int, ...]
) -> list[WeekendSlot]:
    """Align captured sessions onto the game-reported weekend structure.

    ``ordered`` is the weekend's captured sessions sorted by ``session_link_id`` then capture time
    (their true running order, with a slot's repeat attempts in the order they were driven).
    Non-race session types are unique within a weekend, so they map straight to their structure
    index; the race-type sessions are **grouped by ``session_link_id`` first** and the groups then
    laid onto the race positions in order, so the earlier-driven race takes the Sprint slot and the
    later one the Grand Prix. Uncaptured positions become pending slots (``sessions=()``).

    Grouping the races is what keeps a re-driven Sprint out of the Grand Prix's position: attempts
    at one slot share a ``session_link_id``, so pairing *sessions* with positions handed the second
    Sprint attempt the Grand Prix's slot and lost the real Grand Prix outright (invariant #5).

    A session whose type isn't in the structure lands nowhere; ``weekend_slots`` checks for that
    and drops the whole weekend onto the link-order fallback rather than losing it.
    """
    type_counts = Counter(structure)
    first_index_of: dict[int, int] = {}
    for i, t in enumerate(structure):
        first_index_of.setdefault(t, i)

    race_positions = [i for i, t in enumerate(structure) if _is_race_type(t)]
    gp_index = race_positions[-1] if race_positions else None

    assigned: dict[int, list[SessionResult]] = {}
    race_groups: dict[int, list[SessionResult]] = {}
    for session in ordered:
        raw = int(session.session_type)
        if _is_race_type(raw):
            race_groups.setdefault(session.session_link_id, []).append(session)
        elif type_counts[raw] == 1:
            assigned.setdefault(first_index_of[raw], []).append(session)
    for group, position in zip(race_groups.values(), race_positions):
        assigned.setdefault(position, []).extend(group)

    return [
        WeekendSlot(
            order=i,
            session_type=safe_enum(SessionType, t),
            sessions=tuple(assigned.get(i, ())),
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

    One slot per captured session, so this path cannot lose one - which is also why
    ``weekend_slots`` falls back to it when the structure can't account for every session. A
    slot's repeat attempts therefore show up here as consecutive single-session slots rather than
    as one slot holding both.
    """
    final = ordered[-1] if ordered else None
    gp = final if final is not None and _is_race_type(final.session_type) else None
    return [
        WeekendSlot(
            order=i,
            session_type=session.session_type,
            sessions=(session,),
            is_sprint_race=_is_race_type(session.session_type) and session is not gp,
            is_grand_prix=session is gp,
        )
        for i, session in enumerate(ordered)
    ]


def weekend_slots(sessions: Sequence[SessionResult]) -> list[WeekendSlot]:
    """The ordered slots for one weekend's captured sessions.

    Sorts by ``session_link_id`` (the true running order), then by capture time so a slot's repeat
    attempts come back in the order they were driven - both attempts carry the same link id, so
    that tie-break is the only thing that can order them. When the game-reported
    ``weekend_structure`` is available, returns a slot for every session in the weekend - captured
    or pending - with the Sprint Race and Grand Prix correctly distinguished.

    **No session is ever dropped.** A structure that can't account for every captured session is
    not this weekend's structure - ``_weekend_structure`` takes the longest one any session
    carries, so a short or stale row can leave a type with no position - and the link-order
    fallback, one slot per session, is used instead. It gives up the pending slots, which is the
    lesser loss on a weekend whose structure already disagrees with what was captured.

    Pass the sessions of a single weekend (same ``weekend_link_id``); mixing weekends is not
    meaningful.
    """
    ordered = sorted(sessions, key=lambda s: (s.session_link_id, _recorded_order(s)))
    structure = _weekend_structure(ordered)
    if structure:
        slots = _slots_from_structure(ordered, structure)
        if sum(len(slot.sessions) for slot in slots) == len(ordered):
            return slots
    return _slots_from_link_order(ordered)


def grand_prix_session(sessions: Sequence[SessionResult]) -> SessionResult | None:
    """The captured Grand Prix (final race) for a weekend, or None if it isn't captured yet.

    This is what the calendar Results column shows - never a Sprint Race. Returns None both when
    no race is captured and when only a Sprint (with the Grand Prix still pending) is.

    A Grand Prix driven more than once is resolved *upstream*, by what the user assigned to the
    round: ``rounds_with_results`` returns the assigned sessions, so this normally sees a single
    attempt (DECISIONS -> UI). Handed two anyway, it returns the earliest - which is what the old
    placement already did, so the Results column doesn't change - as a deterministic tie-break and
    not a judgement about which attempt counts.
    """
    for slot in weekend_slots(sessions):
        if slot.is_grand_prix and slot.sessions:
            return slot.sessions[0]
    return None


def slot_for_session(
    session: SessionResult, siblings: Sequence[SessionResult]) -> WeekendSlot:
    """Resolve one session's slot within its weekend, given the pool of known sessions.

    ``siblings`` is any collection that includes the session's weekend-mates (e.g. the whole
    store); it's filtered to the matching ``weekend_link_id``. Lets an isolated view - the
    capture picker - label a Sprint Race correctly. Falls back to a bare slot if the session's
    weekend can't be reconstructed.

    The slot returned is the *position*, so it carries every attempt at it and not only the one
    asked about; callers want it for ``is_sprint_race`` / ``is_grand_prix``, which belong to the
    position rather than to any one attempt.
    """
    weekend = [s for s in siblings if s.weekend_link_id == session.weekend_link_id]
    for slot in weekend_slots(weekend):
        if any(s.session_uid == session.session_uid for s in slot.sessions):
            return slot
    return WeekendSlot(order=0, session_type=session.session_type, sessions=(session,))
