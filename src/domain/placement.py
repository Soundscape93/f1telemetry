"""Which round a stored session belongs in - the rules the proposal and the pipeline share.

Qt-free and store-free, like ``season.weekend_slots``, so both sides of the app can use them:
``ui/sessions/assignment`` builds the picker's *suggested* marks and the weekend proposal on these,
and the pipeline - which must not import ``ui/`` - will build E1e's automatic career assignment on
the same ones (DECISIONS -> Storage). They moved here from ``ui/sessions/assignment`` unchanged
rather than being restated: two copies of "which season does this career id name" would drift
apart, and the copy that writes is the one that can least afford to.

Named ``placement``, not ``assignment``, on purpose: ``ui/sessions/assignment`` already has that
name, and two modules sharing one is what made "no caller remains" unprovable by grep when the
round-centric weekend page was retired.
"""
from __future__ import annotations

from collections import Counter
from typing import Sequence

from .models import SessionResult

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
