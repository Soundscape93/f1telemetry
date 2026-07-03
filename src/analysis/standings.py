"""Championship standings - points summed per driver across a season's classifications.

Pure computation over ``SessionResult``s (no storage, no Qt, no UI) so the season view computes
standings by handling it the sessions it already loaded. The only subtlety is driver identity
across rounds, which is injected as a ``key``: by name (stable for AI, so right for Career and
MyTeam) or by race number (stable per human, so right for Multiplayer). The league roster slice
will add a roster-resolved key on top of the same function.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass

from ..domain.models import ClassificationEntry, SessionResult
from ..domain.season import RoundResults
from ..domain.roster import LeagueRoster


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
        display: Callable[[ClassificationEntry], str] | None = None) -> tuple[StandingRow, ...]:
    """Total points per driver across the given sessions, ranked.
    
    Points are summed across every classification; non-scoring sessions (practice, quali)
    carry zero point, so no session-type filtering is needed - a season's quali results can
    be passed in alongside its races and simply contribute nothing. ``key`` groups drivers
    across rounds; ``display`` chooses the shwon name (default: the entry's own driver name).
    For a league both are the roster resolver, so rows group and label by canonical membler.
    Ties break by points then name (deterministic); full FIA countback is a later refinement.
    """
    name_of = display or (lambda entry: entry.driver_name)
    totals: dict[Hashable, _Accumulator] = {}
    for session in sessions:
        if session.classification is None:
            continue
        for entry in session.classification.entries:
            k = key(entry)
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
    display: Callable[[ClassificationEntry], str] | None = None
    ) -> tuple[StandingRow, ...]:
    """Convenience for the season view: flatten ``rounds_with_results`` output into its
    sessions and compute standings over them."""
    sessions = [session for round in rounds for session in round.sessions]
    return compute_standings(sessions, key, display)


def compute_constructor_standings(
        sessions: Iterable[SessionResult]) -> tuple[ConstructorRow, ...]:
    """Total points per team across the given sessions, ranked.

    Points are summed per ``team_id`` across every classification (non-scoring sessions
    contribute zero, so no session-type filtering is needed). Ties break by points then
    team_id (deterministic)."""
    totals: dict[int, int] = {}
    for session in sessions:
        if session.classification is None:
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
    resolved roster member (online name first, race number as fallback), so a member whose
    shown name drifts between lobbies is still one row under their canonical name."""
    return standings_for_rounds(rounds, key=roster.member_of, display=roster.member_of)