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


@dataclass(frozen=True)
class StandingRow:
    """One row in a season's standings: a driver and their total points across the season."""
    position: int
    driver_name: str
    race_number: int
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
        key: Callable[[ClassificationEntry], Hashable] = by_driver_name) -> tuple[StandingRow, ...]:
    """Total points per driver across the given sessions, ranked.
    
    Points are summed across every classification; non-scoring sessions (practice, quali)
    carry zero point, so no session-type filtering is needed - a season's quali results can
    be passed in alongside its races and simply contribute nothing. Ties break by points then
    name (deterministic); full FIA countback on finishing positions is a later refinement.
    """
    totals: dict[Hashable, _Accumulator] = {}
    for session in sessions:
        if session.classification is None:
            continue
        for entry in session.classification.entries:
            k = key(entry)
            acc = totals.get(k)
            if acc is None:
                acc = _Accumulator(name=entry.driver_name, number=entry.race_number, points=0)
                totals[k] = acc
            acc.points += entry.points
            # keep the most recently seen name/number as the display identity; for a league
            # member whose shown name drifts between lobbies, the latest round wins.
            acc.name = entry.driver_name
            acc.number = entry.race_number

    ranked = sorted(totals.values(), key=lambda a: (-a.points, a.name))
    return tuple(
        StandingRow(position=i, driver_name=a.name, race_number=a.number, points=a.points)
        for i, a in enumerate(ranked, start=1)
    )


def standings_for_rounds(
    rounds: Iterable[RoundResults],
    key: Callable[[ClassificationEntry], Hashable] = by_driver_name) -> tuple[StandingRow, ...]:
    """Convenience for the season view: flatten ``rounds_with_results`` output into its
    sessions and compute standings over them."""
    sessions = [session for round in rounds for session in round.sessions]
    return compute_standings(sessions, key)