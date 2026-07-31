"""Championship standings - points summed per driver across a season's classifications.

Pure computation over ``SessionResult``s (no storage, no Qt, no UI) so the season view computes
standings by handing it the sessions it already loaded. The only subtlety is driver identity
across rounds, which is injected: ``key`` identifies one entry at a time - by name (stable for
AI, so right for Career and MyTeam) or by race number (stable per human, so right for
Multiplayer) - while ``group`` identifies a whole classification at once. A league passes
``group``, because race numbers are unique only among humans: e.g. telling a member on 11 from the AI
Perez on 11 needs the rest of the grid in view (see ``domain.roster.LeagueRoster.session_keys``).
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Sequence
from dataclasses import dataclass

from ..domain.models import ClassificationEntry, SessionResult
from ..domain.season import RoundResults
from ..domain.roster import LeagueRoster, league_display_name
from ..protocol.enums import RACE_SESSION_TYPES


@dataclass(frozen=True)
class StandingRow:
    """One row in a season's standings: a driver and their total points across the season."""
    position: int
    driver_name: str
    race_number: int
    points: int


@dataclass(frozen=True)
class ConstructorRow:
    """One row in a season's constructor standings: a team and its total points."""
    position: int
    team_id: int
    points: int


def by_driver_name(entry: ClassificationEntry) -> Hashable:
    """Identify a driver by name - stable for AI opponents (Career, MyTeam)."""
    return entry.driver_name

def by_race_number(entry: ClassificationEntry) -> Hashable:
    """Identify a driver by race number - stable per human across lobbies (Multiplayer)."""
    return entry.race_number



@dataclass
class _Accumulator:
    """Mutable accumulator for a driver's total points across a season."""
    name: str
    number: int
    points: int = 0


def compute_standings(
        sessions: Iterable[SessionResult],
        key: Callable[[ClassificationEntry], Hashable] = by_driver_name,
        display: Callable[[ClassificationEntry], str] | None = None,
        group: Callable[[Sequence[ClassificationEntry]], Sequence[Hashable]] | None = None,
        ) -> tuple[StandingRow, ...]:
    """Total points per driver across the given sessions, ranked.

    Only race-type sessions are counted (``RACE_SESSION_TYPES`` - RACE/RACE_2/RACE_3, which
    includes the sprint race). Every other session type is skipped: the game does NOT zero the
    final classification's ``m_points`` for non-scoring sessions - it leaves the field holding
    the most recent race's points (so a practice/quali/shootout echoes the last race
    result). The UDP spec defines ``m_points`` as points scored in that session and the packet
    as end-of-race only, so those non-race values are stale and summing them would double-count.
    A season's quali/practice results can therefore be passed in alongside its races and are
    simply ignored.

    ``key`` groups drivers across rounds one entry at a time. ``group`` is the classification-wide
    alternative and wins when given: it receives a session's entries and returns one key per
    entry, so a resolver can use the whole grid as context and guarantee no two cars in a session
    share a row (a league passes ``roster.session_keys``). ``display`` chooses the shown name
    (default: the entry's own driver name). Ties break by points then name (deterministic); full
    FIA countback is a later refinement.
    """
    name_of = display or (lambda entry: entry.driver_name)
    totals: dict[Hashable, _Accumulator] = {}
    for session in sessions:
        if session.classification is None:
            continue
        if session.classification.is_reconstructed:
            continue                       # no Final Classification packet -> no official points
        if session.session_type not in RACE_SESSION_TYPES:
            continue
        entries = session.classification.entries
        keys = list(group(entries)) if group is not None else [key(entry) for entry in entries]
        for entry, k in zip(entries, keys, strict=True):
            acc = totals.get(k)
            if acc is None:
                acc = _Accumulator(name=name_of(entry), number=entry.race_number, points=0)
                totals[k] = acc
            acc.points += entry.points
            # keep the most recently seen name/number as the display identity; for a league
            # member whose shown name drifts between lobbies, the latest round wins.
            acc.name = name_of(entry)
            acc.number = entry.race_number

    ranked = sorted(totals.values(), key=lambda a: (-a.points, a.name))
    return tuple(
        StandingRow(position=i, driver_name=a.name, race_number=a.number, points=a.points)
        for i, a in enumerate(ranked, start=1)
    )


def standings_for_rounds(
    rounds: Iterable[RoundResults],
    key: Callable[[ClassificationEntry], Hashable] = by_driver_name,
    display: Callable[[ClassificationEntry], str] | None = None,
    group: Callable[[Sequence[ClassificationEntry]], Sequence[Hashable]] | None = None,
) -> tuple[StandingRow, ...]:
    """Convenience for the season view: flatten ``rounds_with_results`` output into its
    sessions and compute standings over them."""
    sessions = [session for round in rounds for session in round.sessions]
    return compute_standings(sessions, key=key, display=display, group=group)


def compute_constructor_standings(
        sessions: Iterable[SessionResult]) -> tuple[ConstructorRow, ...]:
    """Total points per team across the given sessions, ranked.

    Points are summed per ``team_id`` across race-type sessions only (``RACE_SESSION_TYPES``);
    other session types are skipped because the game leaves stale last-race points in a non-race
    classification's ``m_points`` (see ``compute_standings``), which would otherwise double-count.
    Ties break by points then team_id (deterministic)."""
    totals: dict[int, int] = {}
    for session in sessions:
        if session.classification is None:
            continue
        if session.classification.is_reconstructed:
            continue                       # no Final Classification packet -> no official points
        if session.session_type not in RACE_SESSION_TYPES:
            continue
        for entry in session.classification.entries:
            totals[entry.team_id] = totals.get(entry.team_id, 0) + entry.points

    ranked = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    return tuple(
        ConstructorRow(position=i, team_id=team_id, points=points)
        for i, (team_id, points) in enumerate(ranked, start=1)
    )


def constructor_standings_for_rounds(
        rounds: Iterable[RoundResults]) -> tuple[ConstructorRow, ...]:
    """Convenience for the season view: flatten ``rounds_with_results`` output into its
    sessions and compute constructor standings over them."""
    sessions = [session for round in rounds for session in round.sessions]
    return compute_constructor_standings(sessions)


def league_standings_for_rounds(
    rounds: Iterable[RoundResults], roster: LeagueRoster) -> tuple[StandingRow, ...]:
    """League standings across a season's rounds: drivers are grouped and labelled by their
    resolved roster member, so a member whose shown name drifts between lobbies is still one row.

    Grouping goes through ``roster.session_keys`` (a whole classification at a time) rather than a
    per-entry key, because a member's race number is unique only among humans - the AI field runs
    the real-world numbers, so an AI sharing a member's number would otherwise be summed into that
    member's row and could even relabel it. AI drivers are *not* filtered out: this is a full-grid
    championship view, they simply keep their own rows. Display prefers a captured public online
    name and falls back to the roster when the capture only says ``Player``.
    """
    return standings_for_rounds(
        rounds,
        display=lambda entry: league_display_name(entry, roster),
        group=roster.session_keys,
    )
