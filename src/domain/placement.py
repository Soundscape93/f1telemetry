"""Which round a stored session belongs in - the rules the proposal and the pipeline share.

Qt-free and store-free, like ``season.weekend_slots``, so both sides of the app can use them:
``ui/sessions/assignment`` builds the picker's *suggested* marks and the weekend proposal on these,
and the pipeline - which must not import ``ui/`` - will build E1e's automatic career assignment on
the same ones (DECISIONS -> Storage). They moved here from ``ui/sessions/assignment`` unchanged
rather than being restated: two copies of "which season does this career id name" would drift
apart, and the copy that writes is the one that can least afford to.

**The career rule is the only one that writes without asking, so it is the strict one.**
``suggested_placement`` answers wherever a career id reaches and leaves the choice to the user;
``plan_career_placements`` writes only where nine conditions hold, and holds a session - and says
why - when one of the last four fails. It takes neither of the proposal's shortcuts. The proposal
reads a season id equal to the weekend id as an online mode, which is exactly what a career's first
weekend reports; and it answers a repeated track with the first free round, which a write must not
guess. The two also part ways on a slot driven more than once: the proposal offers none of its
attempts, while the career rule writes the latest, because a restart means the earlier run went
wrong.

Named ``placement``, not ``assignment``, on purpose: ``ui/sessions/assignment`` already has that
name, and two modules sharing one is what made "no caller remains" unprovable by grep when the
round-centric weekend page was retired.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum, auto
from typing import Sequence

from .models import SessionResult
from .season import Season, SeasonMode

Placement = tuple[int, int]         # (season_id, round_number)


def attempt_counts(sessions: Sequence[SessionResult]) -> Counter[int]:
    """How many attempts share each ``session_link_id`` in one weekend.

    The link id rather than the ``WeekendSlot``, deliberately. A retry keeps the whole identifier
    and changes only ``session_uid`` / ``recorded_at`` (TELEMETRY_NOTES), so this is exact in all
    72 measured sessions - while ``weekend_slots`` falls back to one slot per session on a row with
    no stored ``weekend_structure``, which would split a repeat attempt into two single-session
    slots and silently defeat the rule that exists to catch it.
    """
    return Counter(session.session_link_id for session in sessions)


def repeated_links(sessions: Sequence[SessionResult]) -> set[int]:
    """The ``session_link_id``s this weekend holds more than one attempt at."""
    return {link for link, held in attempt_counts(sessions).items() if held > 1}


def weekend_mates(session: SessionResult, all_sessions: Sequence[SessionResult]) -> list[SessionResult]:
    """Every stored session recorded in the same weekend, the session itself included."""
    return [s for s in all_sessions if s.weekend_link_id == session.weekend_link_id]


def career_season(session: SessionResult, all_sessions: Sequence[SessionResult],
                   placements: dict[int, Placement]) -> int | None:
    """The season this session's career identifier already names, or None if it names none.

    Seasons are user-authored and carry no link id, so the only bridge from a career identifier to
    a season is a session already placed in one. Two seasons sharing the identifier is ambiguous
    and answers None - ask rather than guess.
    """
    named = {placements[s.session_uid][0] for s in all_sessions
             if s.season_link_id == session.season_link_id and s.session_uid in placements}
    return next(iter(named)) if len(named) == 1 else None


def weekends_by_round(season_id: int, all_sessions: Sequence[SessionResult],
                       placements: dict[int, Placement]) -> dict[int, set[int]]:
    """Which weekends each round of one season already holds."""
    weekend_of_uid = {s.session_uid: s.weekend_link_id for s in all_sessions}
    holders: dict[int, set[int]] = {}
    for uid, (placed_season, round_number) in placements.items():
        if placed_season != season_id or uid not in weekend_of_uid:
            continue
        holders.setdefault(round_number, set()).add(weekend_of_uid[uid])
    return holders


# The game modes E1e writes for, each paired with the season mode it may be written into. Raw ids,
# never names (core invariant #9). 78 and 79 are measured; 27 and 28 are the same two careers on
# the 2025 cars, allow-listed on that basis with no capture of either in this database. The pairing
# keeps a career out of a season of the other career mode: a misfiled career is left to the picker.
CAREER_GAME_MODES: dict[int, SeasonMode] = {
    27: SeasonMode.MY_TEAM,             # My Team Career '25
    28: SeasonMode.DRIVER_CAREER,       # Driver Career '25
    78: SeasonMode.DRIVER_CAREER,       # Driver Career '26
    79: SeasonMode.MY_TEAM,             # My Team Career '26
}


class HoldReason(Enum):
    """Why a session was held instead of written - the four conditions that are reported."""

    NO_TRACK_ROUND = auto()          # the calendar holds its track at no round, or at several
    ROUNDS_DISAGREE = auto()         # the track's round is not the round its weekend index gives
    ROUND_TAKEN = auto()            # the track's round holds a different weekend
    SUPERSEDED = auto()              # it is not the latest stored attempt at its slot


@dataclass(frozen=True)
class CareerHold:
    """One new career session left to the user, with what the report needs to say why."""

    session_uid: int
    season_id: int
    reason: HoldReason
    track_round: int | None         # where the calendar has its track; None unless at exactly one round
    index_round: int                # where its weekend index puts it: (weekend - season) / 100 + 1


@dataclass(frozen=True)
class CareerPlan:
    """What to write for a batch of newly stored sessions, and what to hold back.

    Plain values, so a worker can hand the plan to the GUI thread as it is. ``assigned`` pairs each
    session uid with its placement, in the order the sessions were recorded; ``unassigned`` pairs
    each earlier attempt a written one takes out of its round with the placement it leaves.
    """

    assigned: tuple[tuple[int, Placement], ...] = ()
    unassigned: tuple[tuple[int, Placement], ...] = ()
    held: tuple[CareerHold, ...] = ()


def _recorded_key(session: SessionResult) -> tuple[bool, float]:
    """Capture-time sort key tolerating rows without one.

    Restated rather than imported, as ``ui/sessions/assignment`` restates it: ``season``'s own is
    private to its module. Unstamped rows sort first, and the time is compared as a float because a
    stored row reads back naive while a freshly saved one is aware.
    """
    recorded = session.recorded_at
    return (recorded is not None, recorded.timestamp() if recorded is not None else 0.0)


def _other_attempts(session: SessionResult,
                    all_sessions: Sequence[SessionResult]) -> list[SessionResult]:
    """Every other stored attempt at this session's slot, in recorded order."""
    return sorted((s for s in weekend_mates(session, all_sessions)
                   if s.session_link_id == session.session_link_id
                   and s.session_uid != session.session_uid), key=_recorded_key)


def _career_target(session: SessionResult, all_sessions: Sequence[SessionResult],
                   seasons: Sequence[Season],
                   placements: dict[int, Placement]) -> tuple[Season, int] | None:
    """The season a career session names and the round its weekend index gives - conditions 1-5.

    None wherever one of them fails, and nothing is said about it.
    """
    mode = CAREER_GAME_MODES.get(session.game_mode)
    if mode is None or session.session_uid in placements:
        return None
    season_id = career_season(session, all_sessions, placements)
    if season_id is None:
        return None
    season = next((s for s in seasons if s.season_id == season_id), None)
    if season is None or season.mode != mode:
        return None
    offset = session.weekend_link_id - session.season_link_id
    if offset < 0 or offset % 100:
        return None
    return season, offset // 100 + 1


def _career_hold(session: SessionResult, season: Season, index_round: int,
                 all_sessions: Sequence[SessionResult],
                 placements: dict[int, Placement]) -> CareerHold | None:
    """Conditions 6-9, in order: the first that fails names the hold, and None means write."""
    rounds = [r.round_number for r in season.rounds if r.track_id == session.track_id]
    track_round = rounds[0] if len(rounds) == 1 else None
    taken = weekends_by_round(season.season_id, all_sessions, placements).get(index_round, set())
    # At or after it, not only after: two attempts recorded at the same moment have no latest one.
    not_earlier = [s for s in _other_attempts(session, all_sessions)
                   if _recorded_key(s) >= _recorded_key(session)]
    if track_round is None:
        reason = HoldReason.NO_TRACK_ROUND
    elif track_round != index_round:
        reason = HoldReason.ROUNDS_DISAGREE
    elif taken - {session.weekend_link_id}:
        reason = HoldReason.ROUND_TAKEN
    elif not_earlier:
        reason = HoldReason.SUPERSEDED
    else:
        return None
    return CareerHold(session_uid=session.session_uid, season_id=season.season_id, reason=reason,
                      track_round=track_round, index_round=index_round)


def plan_career_placements(new: Sequence[SessionResult], all_sessions: Sequence[SessionResult],
                           seasons: Sequence[Season],
                           placements: dict[int, Placement]) -> CareerPlan:
    """Where E1e writes each newly stored career session, and which of them it holds.

    ``new`` is what a fresh recording or an import stored for the first time - never a re-ingest or
    a restore, which is the caller's to guarantee - and ``all_sessions`` is every stored session,
    ``new`` included. A write needs all nine of these, checked in this order (DECISIONS -> Storage):

    1. an allow-listed game mode (``CAREER_GAME_MODES``);
    2. the session not already placed;
    3. exactly one season holding a session with its ``season_link_id``;
    4. that season in the mode its game mode pairs with;
    5. a weekend index, ``(weekend_link_id - season_link_id) / 100``, that is a whole number, zero
       or more;
    6. the season's calendar holding its track exactly once;
    7. that round equal to the index + 1;
    8. that round holding no other weekend;
    9. it being the latest stored attempt at its slot.

    **Failing 1-5 is silent**: such a session is not in a career placed in a season, so nothing was
    expected of it. **Failing 6-9 holds it**, and the first condition to fail is the reason.

    **The latest attempt at a slot is the one written**, because a restart means the earlier run
    went wrong. An attempt with a later one stored fails 9 wherever that later one came from - the
    same recording, a separate one, or an import - so an older attempt never displaces a newer one.
    Writing the latest takes every earlier attempt at its slot out of that same round
    (``unassigned``), including one placed by hand, because standings count every assigned race.
    An attempt placed in any other round is left alone, and condition 2 never moves a placed
    session. Recording the attempts separately therefore ends in the same placements as recording
    them together.

    The round comes from the track and the index has to agree with it. Neither is corrected towards
    the other, because the index rests on two careers and no skipped weekend.

    Sessions are taken in recorded order and each write counts towards the next, so a whole new
    weekend fills its round and a second weekend claiming that round is held behind the first.
    """
    working = dict(placements)
    assigned: list[tuple[int, Placement]] = []
    unassigned: list[tuple[int, Placement]] = []
    held: list[CareerHold] = []
    for session in sorted(new, key=_recorded_key):
        target = _career_target(session, all_sessions, seasons, working)
        if target is None:
            continue
        season, index_round = target
        hold = _career_hold(session, season, index_round, all_sessions, working)
        if hold is not None:
            held.append(hold)
            continue
        placement = (season.season_id, index_round)
        for earlier in _other_attempts(session, all_sessions):
            if working.get(earlier.session_uid) == placement:
                del working[earlier.session_uid]
                unassigned.append((earlier.session_uid, placement))
        working[session.session_uid] = placement
        assigned.append((session.session_uid, placement))
    return CareerPlan(assigned=tuple(assigned), unassigned=tuple(unassigned), held=tuple(held))
