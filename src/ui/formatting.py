"""Presentation helers for classification tables - pure and Qt-free, so they're unit-testable
and shared across views.

Formats a classification row's result cell the way the game's results screen reads:
    * race:         - the winner's total time, a gap to the winnter for lead-lap cars,
                      "+N laps" for lappged cars, and a status (DNF,DSQ,NC,DNS) for non-finishers.
    * qualifying/ 
    sprint shootout - the best lap time, or a status for a driver who didn't set a time (DNF,DSQ,NC,DNS).
    * practice /
      time trial    - just the best lap time (never a status).

Gaps and the winner's time include post-race penalties (``total_race_time_s + penalties_time_s``)
so they line up with the classification order.
"""

from __future__ import annotations

from ..protocol.enums import ResultStatus, SessionType

_RACE_TYPES = frozenset({SessionType.RACE, SessionType.RACE_2, SessionType.RACE_3})

__QUALI_TYPES = frozenset({SessionType.QUALIFYING_1, SessionType.QUALIFYING_2, SessionType.QUALIFYING_3,
                           SessionType.SHORT_QUALIFYING, SessionType.ONE_SHOT_QUALIFYING,
                            SessionType.SPRINT_SHOOTOUT_1, SessionType.SPRINT_SHOOTOUT_2, SessionType.SPRINT_SHOOTOUT_3,
                             SessionType.SHORT_SPRINT_SHOOTOUT, SessionType.ONE_SHOT_SPRINT_SHOOTOUT,
})

# Short tags for drivers who didn't finish; any status not here is treated as finished.
_STATUS_LABELS = {
    ResultStatus.DID_NOT_FINISH: "DNF", 
    ResultStatus.RETIRED: "DNF",
    ResultStatus.DISQUALIFIED: "DSQ",
    ResultStatus.NOT_CLASSIFIED: "NC",
    ResultStatus.INACTIVE: "DNS"
}


def is_race(session_type: SessionType) -> bool:
    """Whether the session type uses the race result layout (time/gap) vs a best-lap layout."""
    return session_type in _RACE_TYPES


def _finished(status) -> bool:
    """Whether the driver finished the race."""
    return status == ResultStatus.FINISHED


def _status_label(status) -> str:
    """Short tag for a non-finished driver, or a dash for a finished driver."""
    return _STATUS_LABELS.get(status, "\u2014")


def _effective_time(entry) -> float:
    """On-track race time plus post-race penalties, i.e. time as classified."""
    return entry.total_race_time_s + entry.penalties_time_s


def format_race_time(seconds: float) -> str:
    """A full race/session time as [H:]M:SS.mmm (em dash if unset)."""
    if seconds <= 0:
        return "\u2014"
    ms = round(seconds * 1000)
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs = rem / 1000
    if hours:
        return f"{hours}:{minutes:02}:{secs:06.3f}"
    return f"{minutes}:{secs:06.3f}"


def format_gap(seconds: float) -> str:
    """A signed gap as +S.mmm or +M:SS.mmm (a leading '-' os kept, thou it's rare)"""
    ms = round(seconds * 1000)
    sign = "-" if ms < 0 else "+"
    ms = abs(ms)
    minutes, rem = divmod(ms, 60_000)
    secs = rem / 1000
    if minutes:
        return f"{sign}{minutes}:{secs:06.3f}"
    return f"{sign}{secs:.3f}"


def format_lap_time(ms: int) -> str:
    """A lap time in milliseconsds as M:SS.mmm (em dash if unset)."""
    if not ms:
        return "\u2014"
    minutes, rem = divmod(ms, 60_000)
    secs = rem / 1000
    return f"{minutes}:{secs:06.3f}"


def race_result(entry, winner) -> str:
    """The race 'time' cell: the winner's total, a gap for lead-lap cars, '+N laps' for lapped
    cars, or a status for non-finishers."""
    if not _finished(entry.result_status):
        return _status_label(entry.result_status)
    if winner is None or entry is winner or entry.position == 1:
        return format_race_time(_effective_time(entry))
    laps_down = winner.num_laps - entry.num_laps
    if laps_down > 0:
        return f"+{laps_down} lap" + ("s" if laps_down != 1 else "")
    return format_gap(_effective_time(entry) - _effective_time(winner))


def non_race_result(entry, session_type) -> str:
    """The non-race 'best lap' cell: a status for qualifying non-finisher, otherwise the best
    lap time (practice/ tt never show a status)."""
    if session_type in __QUALI_TYPES and not _finished(entry.result_status):
        return _status_label(entry.result_status)
    if entry.best_lap_time_ms:
        return format_lap_time(entry.best_lap_time_ms)
    return "\u2014"
    