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

from ..pipeline import RestoreProblem
from ..protocol.enums import RACE_SESSION_TYPES, ResultStatus, SessionType, Weather
from ..protocol.reference import game_mode_name, team_display_name, track_name

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

    Two race-shaped corrections, both display-only:

    ``is_sprint_race`` overrides the label to "Sprint Race". Only weekend context can decide it
    (``domain.season.weekend_slots``), so a caller with no weekend - the deleted-sessions manager -
    cannot pass it, and a deleted sprint reads as "Race" there.

    **Every other race type reads "Race", never "Race 2".** On a sprint weekend the game reports
    the Sprint as ``RACE`` (15) and the Grand Prix as ``RACE_2`` (16) - verified against this
    database's ``weekend_structure`` of ``[1, 10, 11, 12, 15, 5, 6, 7, 16]`` - so the raw enum name
    put "Race 2" on the Grand Prix in every view that labels a session. The weekend's *final* race
    is the Grand Prix and earlier races are Sprints (core invariant #5), which ``weekend_slots``
    already resolves by position; the ordinal inside the enum name is not something a user needs.
    It also makes the number useful where there is no weekend at all: a tombstone reading 16 is a
    Grand Prix whatever else is unknown about it.
    """
    if is_sprint_race:
        return "Sprint Race"
    if is_race(session_type):
        return "Race"
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


def format_grid_penalty(places: int) -> str | None:
    """A grid-penalty indicator like ``⚑ 10-place grid``, or None when the car carries none.

    Separate from ``format_penalty_badge`` rather than folded into it, because the two answer
    different questions from different sources. That badge reads the classification's own
    aggregate - a count and the seconds added to a race time - and a **grid** penalty adds no
    seconds, so it renders there as a bare ``⚑ ×2`` that never says what it cost. The places come
    from the stored ``PENA`` rows instead (``race_control.grid_penalty_places``), and the count of
    penalties is dropped on purpose: two 5-place penalties and one 10-place penalty put the car in
    exactly the same grid slot, so the places are the fact and the row count is not.
    """
    if places <= 0:
        return None
    return f"{_PENALTY_FLAG} {places}-place grid"


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


def _player_entry(session):
    """The player's classification entry, or None.
    
    Iterates the entries rather than using ``Classification.player`` so this module keeps working
    on any object that merely exposes ``entries`` - which is what the unit tests build, and what
    every other helper already assumes.
    """
    entries = session.classification.entries if session.classification else ()
    return next((entry for entry in entries if entry.is_player), None)


def session_best_lap_ms(session) -> int | None:
    """The fastest lap of the whole session in milliseconds, or None if nobody set one.

    The raw counterpart to :func:`session_fastest_lap`, which formats a driver + time for display.
    The detail page needs the bare number to decide whether *my* fastest lap is also the
    session's - i.e. whether it is painted blue or green.

    ``0`` means "no time set", so this is a min over the non-zero entries (see
    :func:`session_fastest_lap` for why that matters).
    """
    entries = session.classification.entries if session.classification else ()
    timed = [entry.best_lap_time_ms for entry in entries if entry.best_lap_time_ms]
    return min(timed) if timed else None


def player_best_lap_ms(laps) -> int | None:
    """The fastest of the player's own stored laps in milliseconds, or None if none is timed."""
    timed = [lap.lap_time_ms for lap in laps if lap.lap_time_ms]
    return min(timed) if timed else None


def lap_gap_label(lap_time_ms: int | None, best_ms: int | None) -> str:
    """The Laps box's Gap cell: a gap to the driver's own personal best, not the sessions.
    
    An em dash for the reference lap itself, for a lap with no time, and when there is no
    reference. Two laps that tie on the best time both read as the reference - honest, and rare
    enough not to be worth breaking the tie arbitrarily.
    """
    if not lap_time_ms or not best_ms or lap_time_ms == best_ms:
        return _EM_DASH
    return format_gap((lap_time_ms - best_ms) / 1000)


def player_points_label(session, is_sprint_race: bool = False) -> str | None:
    """The details grid's points cell - the player's points, or an em dash outside a race.

    **The gate is a correctness fix, not a tidiness one.** The stored value is only meaningful for
    a race: checked against real captures, ``PRACTICE_1`` player rows carry ``points 25`` and
    ``QUALIFYING_1`` rows carry ``25`` and ``8``, because the game reports a carried-over
    championship figure in the Final Classification packet on non-race session types. Printing it
    would state a number that is simply untrue.

    A **reconstructed** race has no official points, so it shows the same muted ``~N`` estimate the
    classification table shows rather than a bare ``0`` - the two are on screen together and must
    not disagree.
    """
    if not is_race(session.session_type):
        return _EM_DASH
    player = _player_entry(session)
    if player is None:
        return _EM_DASH
    if session.classification is not None and session.classification.is_reconstructed:
        estimate = estimate_points(player.position, player.result_status, is_sprint_race)
        return _EM_DASH if estimate is None else f"~{estimate}"
    return str(player.points)


def laps_completed_label(session, stored_laps: int = 0) -> str:
    """The details grid's laps cell: ``29 / 29`` in a race, a bare count elsewhere.

    A stand-in for on-track overtakes, which are not stored - the game sends them as ``OVTK``
    Event packets and the assembler never reads Event packets at all (PRIORITIES -> E15). This
    cell becomes real overtakes once that lands.

    Two data facts shape it. The count comes from the classification's ``num_laps`` rather than
    from the stored lap rows, because a recording that started late stores fewer laps than were
    actually driven (real captures show 27 stored against 29 completed). And the ``/ total`` only
    appears for races: ``total_laps`` is the *race* distance and is meaningless elsewhere - real
    practice sessions carry ``total_laps 1`` against 7 laps actually run.
    """
    player = _player_entry(session)
    completed = player.num_laps if player is not None and player.num_laps else stored_laps
    if is_race(session.session_type) and session.total_laps > 0:
        return f"{completed} / {session.total_laps}"
    return str(completed)


def session_context_label(session, session_label: str) -> str:
    """The details grid's context cell: team, game mode and session type.

    ``session_label`` is the caller's already-resolved slot label, because only the weekend
    context can tell a Sprint Race from a Grand Prix (core invariant #5).
    """
    bits = []
    player = _player_entry(session)
    if player is not None:
        bits.append(team_display_name(player.team_id))
    bits.append(game_mode_name(session.game_mode))
    bits.append(session_label)
    return "  ·  ".join(bits)


# --- the deleted-session manager ------------------------------------------------------------

def format_size(num_bytes: int) -> str:
    """Bytes as MB/GB - an import moves hundreds of MB, and a capture chooser has to say so.

    Promoted out of ``main_window`` when the restore chooser became its second caller: two copies
    of one session differ in size before they differ in anything else a person can see.
    """
    mb = num_bytes / (1024 * 1024)
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{mb:.0f} MB"


def deleted_session_cells(deleted) -> tuple[str, str, str, str]:
    """The deleted-sessions table's four descriptive columns for one tombstone.

    Every field but the uid is nullable - a tombstone written by an older build, or rolled back
    from a failed restore of a session whose row was already gone, may know nothing else at all -
    so each column falls back to an em dash instead of inventing a value.

    **The session column cannot say "Sprint Race".** The tombstone carries ``session_type``, and a
    sprint reports RACE (15) exactly as an ordinary race does; only the weekend the session sat in
    separates them (core invariant #5), and that is gone with the session. A sprint weekend's Grand
    Prix *is* recoverable - it reports RACE_2 (16), which ``slot_label`` renders as "Race" - so the
    limitation is narrower than it looks: it bites type 15 only. The view says so in a tooltip
    rather than guessing here.
    """
    return (
        _EM_DASH if deleted.session_type is None else slot_label(deleted.session_type),
        _EM_DASH if deleted.track_id is None else track_name(deleted.track_id),
        recorded_label(deleted.recorded_at),
        recorded_label(deleted.deleted_at),
    )


def deleted_capture_label(known_names, found_names) -> str:
    """The manager's capture column: the file a restore would read, or why there isn't one.

    Three answers, because they mean different things and have different ways out - the same three
    the session detail page gives for a stored session, in the width a table cell has:

    * **no capture row at all** - pruned, or ingested before capture metadata was recorded. This
      session can never be restored, and Forget is the only way its row leaves the list.
    * **rows, but nothing findable** - the file moved or was deleted. Every known name is shown,
      not a chosen one, so it always matches what a refusal will name, and Help → Find moved
      captures may bring it back.
    * **findable** - the file restore would read. Several are counted rather than listed, because
      the chooser is where they get named properly.
    """
    if not known_names:
        return "not recorded"
    if not found_names:
        return f"{', '.join(known_names)}  (archive not found)"
    if len(found_names) > 1:
        return f"{found_names[0]}  (+{len(found_names) - 1} more)"
    return found_names[0]


def capture_choice_label(capture) -> str:
    """One line of the "which recording?" chooser: file, who recorded it, size, when it was read.

    Every field is there because it is something that tells two copies of one session apart: the
    same session recorded by two league members gives two files of different sizes, and the same
    file imported twice gives two ingest stamps. ``recorded_by`` is unset for a capture made on
    this machine as well as for one whose recorder was never recorded, so it says "unknown" rather
    than claiming either (it is a property of the *file* - E13's, not Sessions').
    """
    return "  ·  ".join((
        capture.file_name,
        f"recorded by {capture.recorded_by}" if capture.recorded_by else "recorder unknown",
        format_size(capture.file_size),
        f"read {recorded_label(capture.ingested_at)}",
    ))


def restore_message(outcome) -> str:
    """What a finished restore says to the user - one sentence per ``RestoreProblem``.

    The wording lives here, Qt-free and tested, rather than at the call site, because a refusal is
    a *normal* answer for this job and two of them have to be told apart carefully: a recording
    whose file has gone missing can be found again, while a session no capture row mentions can
    never be restored at all and only Forget will clear it. Reading the same in both cases would
    send someone hunting for a file that was never recorded (E1/E2 plan -> Restore = single-capture
    re-ingest).
    """
    name = outcome.capture_name or "the recording"
    if outcome.restored:
        return f"Restored the session from {name}, with its laps and their traces."
    if outcome.reason is RestoreProblem.ARCHIVE_MISSING:
        return (f"The recording for this session can't be found ({name}). Restore needs it — try "
                "Help → Find moved captures, or import it again. The session is still listed as "
                "deleted.")
    if outcome.reason is RestoreProblem.NO_CAPTURE_ROW:
        return ("Nothing in the database records which recording held this session, so it can't "
                "be restored. Forget removes the row; if you import or re-read that recording "
                "later, the session comes back on its own.")
    if outcome.reason is RestoreProblem.AMBIGUOUS_CAPTURE:
        return ("Several recordings hold this session, so nothing was guessed at — choose one and "
                "try again.")
    if outcome.reason is RestoreProblem.NOT_IN_CAPTURE:
        return (f"{name} turned out not to hold this session after all. Nothing was changed, the "
                "session is still listed as deleted, and its capture record has been corrected.")
    if outcome.reason is RestoreProblem.INGEST_FAILED:
        detail = f" ({outcome.error})" if outcome.error else ""
        return (f"Reading {name} failed{detail}. Nothing was changed and the session is still "
                "listed as deleted.")
    if outcome.reason is RestoreProblem.NOT_DELETED:
        return "This session isn't deleted — the list was out of date and has been re-read."
    return "The session could not be restored for an unkown reason."
