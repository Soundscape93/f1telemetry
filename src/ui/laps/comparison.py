"""Candidate comparison laps for the overlay - which other laps the detail page can overlay.

Given the lap being viewed, enumerates the laps it makes sense to compare against, grouped by
scope: the session's best lap, the other laps of the same session, and the laps of the same race
weekend (other sessions sharing this one's ``weekend_link_id`` - same track, so the shared distance
grid stays meaningful). Pure query logic over the stores (Qt-free, unit-testable); the detail page
turns the chosen refs into overlaid traces via ``LapStore.load`` + ``analysis.traces``.
"""
from __future__ import annotations

from dataclasses import dataclass

from ...domain.season import slot_for_session
from ..formatting import format_lap_time, slot_label

SCOPE_BEST = "Best Lap"
SCOPE_SESSION = "Same session"
SCOPE_WEEKEND = "Same weekend"


@dataclass(frozen=True)
class LapRef:
    """A pickable comparison lap: where it is, how to load it, and how to label it in the legend."""

    session_uid: str
    lap_number: int
    label: str
    lap_time_ms: int | None


def _session_slot_label(session, all_sessions) -> str:
    """The short session label (e.g. 'Q3', 'Race') for a session within its weekend."""
    slot = slot_for_session(session, all_sessions)
    return slot_label(slot.session_type, slot.is_sprint_race) if slot else "Session"


def _lap_ref(uid: str, slot: str, lap, suffix: str = "") -> LapRef:
    """A LapRef labelled 'Lap N - Slot' (session context in the legend), plus an optional suffix."""
    name = f"Lap {lap.lap_number} - {slot}" if slot else f"Lap {lap.lap_number}"
    return LapRef(uid, lap.lap_number, name + suffix, lap.lap_time_ms)


def candidate_laps(session_store, lap_store, base_uid, base_lap_number) -> dict[str, list[LapRef]]:
    """Return ``{scope: [LapRef, ...]}`` for the laps ``(base_uid, base_lap_number)`` can compare to.
    
    Empty scopes are omitted and the base lap itself is never a candidate. Every candidate is
    labbeled with its session slot (e.g. 'Q3') so laps stay distinct in the legend. The best/fastest
    scope pans the whole weekend (all sessions sharing the ``weekend_link_id`` - same track),
    considers the lap being viewed too, and is omitted when the lap is itself the fastest (there's
    nothing to overlay). Only ``list_sessions``/ ``list``are read (no Parquet traces).
    """
    base_uid = str(base_uid)
    all_sessions = session_store.list_sessions()
    by_uid = {str(s.session_uid): s for s in all_sessions}
    base_session = next((s for s in all_sessions if str(s.session_uid) == base_uid), None)

    # every lap of this race weekend, each tagged with its session slot
    if base_session is not None:
        weekend_uids = [uid for uid, s in by_uid.items()
                        if s.weekend_link_id == base_session.weekend_link_id]
    else:
        weekend_uids = [base_uid]   # no session? just the base lap's session
    base_slot = _session_slot_label(base_session, all_sessions) if base_session else ""
    entries: list[tuple[str, str, object]] = []     # (uid, slot, lap)
    for uid in weekend_uids:
        slot = base_slot if uid == base_uid else _session_slot_label(by_uid[uid], all_sessions)
        for lap in lap_store.list(uid):
            entries.append((uid, slot, lap))

    groups: dict[str, list[LapRef]] = {}

    # best lap of the session: the fastest timed lap that isn't the base
    timed = [(uid, slot, lap) for (uid, slot, lap) in entries if lap.lap_time_ms]
    if timed:
        b_uid, b_slot, b_lap = min(timed, key=lambda e: e[2].lap_time_ms)
        if not (b_uid == base_uid and b_lap.lap_number == base_lap_number):
            groups[SCOPE_BEST] = [
                _lap_ref(b_uid, b_slot, b_lap, f" · best {format_lap_time(b_lap.lap_time_ms)}")]
    
    # every other lap of this session
    same = [_lap_ref(uid, slot, lap) for (uid, slot, lap) in entries
            if uid == base_uid and lap.lap_number != base_lap_number]
    if same:
        groups[SCOPE_SESSION] = same
    
    # laps of the other sessions in the weekend
    weekend = [_lap_ref(uid, slot, lap) for (uid, slot, lap) in entries
               if uid != base_uid]
    if weekend:
        groups[SCOPE_WEEKEND] = weekend

    return groups


def best_lap_label(session_store, base_uid, base_lap_number) -> str:
    """Legend label for the lap being viewed: 'Lap N - Slot (this)' or 'Lap N (this)' if no slot."""
    all_sessions = session_store.list_sessions()
    session = next((s for s in all_sessions if str(s.session_uid) == str(base_uid)), None)
    slot = _session_slot_label(session, all_sessions) if session else ""
    stem = f"Lap {base_lap_number} - {slot} (this)" if slot else f"Lap {base_lap_number}"
    return stem