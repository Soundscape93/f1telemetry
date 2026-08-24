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

from ..protocol.enums import RACE_SESSION_TYPES, ResultStatus, SessionType, Weather
from ..protocol.reference import team_display_name

# Position-change glyphs (race Pos cell): filled triangles read closer to the game than
# the arrowhead code points, and bold cleanly. Em dash = no change / unknown grid.
_TRIANGLE_UP = "▲"     # ▲
_TRIANGLE_DOWN = "▼"   # ▼
_EM_DASH = "—"         # —
_PENALTY_FLAG = "⚑"    # ⚑

_RACE_TYPES = RACE_SESSION_TYPES

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

_WEATHER_LABELS = {
    Weather.CLEAR: "Clear",
    Weather.LIGHT_CLOUD: "Light cloud",
    Weather.OVERCAST: "Overcast",
    Weather.LIGHT_RAIN: "Light rain",
    Weather.HEAVY_RAIN: "Heavy rain",
    Weather.STORM: "Storm"
}


def is_race(session_type: SessionType) -> bool:
    """Whether the session type uses the race result layout (time/gap) vs a best-lap layout."""
    return session_type in _RACE_TYPES


# Championship points by finishing position (1-based). F1 25/26 scoring: the Grand Prix awards
# the top 10 and the Sprint the top 8; there is no fastest-lap point (dropped for 2025+). Used
# only for the muted estimate on reconstructed race tables - never persisted or summed into
# standings (see analysis.standings, which skips reconstructed sessions).
_GP_POINTS = (25, 18, 15, 12, 10, 8, 6, 4, 2, 1)
_SPRINT_POINTS = (8, 7, 6, 5, 4, 3, 2, 1)


def estimate_points(position: int, result_status: ResultStatus, is_sprint_race: bool = False) -> int | None:
    """Best-guess championship points for a finishing position, for reconstructed race tables.

    Returns standard F1 25/26 points (Grand Prix, or Sprint when ``is_sprint_race``) for a
    finisher in the scoring positions, 0 for a finisher outside them, and None for a driver who
    didn't finish (no position to score). An estimate for display only: it assumes standard game
    scoring and can't know classified-DNF or custom league rules, so it is shown muted and never
    reaches standings.
    """
    if result_status != ResultStatus.FINISHED:
        return None
    table = _SPRINT_POINTS if is_sprint_race else _GP_POINTS
    if 1 <= position <= len(table):
        return table[position - 1]
    return 0


def slot_label(session_type, is_sprint_race: bool = False) -> str:
    """Return prettified session-type name, e.g. RACE -> Race.

    ``is_sprint_race`` overrides the RACE label to "Sprint Race" - both report SessionType.RACE,
    so only the weekend context (see domain.season.weekend_slots) can tell them apart.
    """
    if is_sprint_race:
        return "Sprint Race"
    name = getattr(session_type, "name", None)
    return name.replace("_", " ").title() if name else str(session_type)


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


def compound_for_lap(tyre_stints, lap_num: int) -> int | None:
    """The visual tyre compound in use on ``lap_num`` - the fastest-lap tyre for the tyre cell.

    Stints are chronological with ``end_lap`` the last lap of each (the final/current stint uses
    a sentinel like 255), so the first stint whose ``end_lap`` reaches ``lap_num`` is the one that
    covered it. Returns None when there's no timed lap (``lap_num == 0``) or no stint data; falls
    back to the last stint if ``lap_num`` runs past every recorded ``end_lap``.
    """
    if not lap_num or not tyre_stints:
        return None
    for stint in tyre_stints:
        if lap_num <= stint.end_lap:
            return stint.visual_compound
    return tyre_stints[-1].visual_compound


def format_position_change(grid_position: int, position: int) -> tuple[str, str]:
    """The race Pos change indicator as ``(glyph, kind)``.

    ``kind`` is one of ``gain``/``loss``/``same``/``none`` so the view can colour the glyph
    (green up / red down / neutral dash) without this Qt-free module knowing about palettes.
    ``grid_position <= 0`` means a pit-lane / unknown start, shown as a neutral dash.
    """
    if grid_position <= 0:
        return (_EM_DASH, "none")
    delta = grid_position - position
    if delta > 0:
        return (_TRIANGLE_UP, "gain")
    if delta < 0:
        return (_TRIANGLE_DOWN, "loss")
    return (_EM_DASH, "same")


def format_grid(grid_position: int) -> str:
    """The Grid cell: the starting slot, or an em dash for a pit-lane / unknown start."""
    return str(grid_position) if grid_position > 0 else _EM_DASH


def format_lap_gap(entry, winner) -> str:
    """The quali/practice Gap cell: the gap to the session's fastest lap, an em dash for the
    leader or for a driver who set no time."""
    if winner is None or entry is winner or entry.position == 1:
        return _EM_DASH
    if not entry.best_lap_time_ms or not winner.best_lap_time_ms:
        return _EM_DASH
    return format_gap((entry.best_lap_time_ms - winner.best_lap_time_ms) / 1000)


def format_penalty_badge(num_penalties: int, penalties_time_s: int) -> str | None:
    """A penalty indicator like ``⚑ ×1 (+3s)``, or None when the driver has no penalty.

    The Time cell alternates between the race time and this badge for penalised finishers.
    """
    if num_penalties <= 0 and penalties_time_s <= 0:
        return None
    parts = [_PENALTY_FLAG]
    if num_penalties > 0:
        parts.append(f"×{num_penalties}")
    if penalties_time_s > 0:
        parts.append(f"(+{penalties_time_s}s)")
    return " ".join(parts)


def race_winner_summary(session, name_of=lambda entry: entry.driver_name) -> str | None:
    """Return the race winner as ``Driver / Team`` for a race session, or None if unavailable.

    ``name_of`` resolves the winner's shown name; it defaults to the entry's own driver name
    and lets a caller inject a league display name without this module knowing about rosters.
    """
    if not is_race(session.session_type) or session.classification is None:
        return None
    winner = session.classification.winner
    if winner is None:
        return None
    return f"{name_of(winner)} / {team_display_name(winner.team_id)}"


def weather_label(weather) -> str:
    """'Clear' / 'Light rain' for a Weather value, tolerant of a raw int from ``safe_enum``.
    
    Enums are stored as raw ints (core invariant #9), so a value newer than our enum arrives
    here as a plain int rather than a member - it must render as something, not crash.
    """
    label = _WEATHER_LABELS.get(weather)
    if label is not None:
        return label
    name = getattr(weather, "name", None)
    return name.replace("_", " ").capitalize() if name else str(weather)


def recorded_label(recorded_at) -> str:
    """Local-time 'YYYY-MM-DD HH:MM' for a session's ``recorded_at``, or an em dash if unset.

    Stored as UTC: a tz-aware value is converted to local time, a naive one (older rows) shown
    as-is. Shared, because it had already been copied into the laps overview and the weekend
    page before the sessions surface would have made it a fourth copy.
    """
    if recorded_at is None:
        return "\u2014"
    if recorded_at.tzinfo is not None:
        recorded_at = recorded_at.astimezone()
    return recorded_at.strftime("%Y-%m-%d %H:%M")


def session_fastest_lap(session, name_of=lambda entry: entry.driver_name) -> str | None:
    """The session's fastest lap as ``Driver - M:SS.mmm``, or None if unavailable.

    Reads the classification's own ``best_lap_time_ms``, so a caller listing every session stays
    at one query - no ``LapStore`` hydration, which would also only ever cover the player's car.

    ``0`` means "no time set", not "instant lap", which is why this is a min over the non-zero
    entries: a plain ``min`` would report a driver who never completed a lap as the fastest of
    the session. Entries arrive in finishing order, so a tie resolves to the higher-placed
    driver.
    """
    if session.classification is None:
        return None
    timed = [e for e in session.classification.entries if e.best_lap_time_ms]
    if not timed:
        return None
    best = min(timed, key=lambda entry: entry.best_lap_time_ms)
    return f"{name_of(best)} — {format_lap_time(best.best_lap_time_ms)}"


def session_leader(session, name_of=lambda entry: entry.driver_name) -> str | None:
    """The name at the top of the classification, whatever the session type.
    
    Every session has one: a race has a winner, and a practice or qualifying session has whoever
    ended up P1. ``Classification.winner`` is already "the first-place entry" rather than
    anything race-specific, so this is a thin wrapper over it - what a caller *labels* it is the
    caller's business. Distinct from :func:`race_winner_summary`, which is races-only and adds
    the team, and which the seasons detail page still wants.
    """
    if session.classification is None:
        return None
    leader = session.classification.winner
    return None if leader is None else name_of(leader)
