"""Which rows a Session overview shows, and in what order - Qt-free, so the rules are
unit-testable the way ``race_control``, ``lap_context`` and ``league_names`` are.

Two overviews read this module. The plain one lists every stored session newest first behind a
track/session filter; the weekend-filtered one lists a single weekend in running order. What they
share is not a widget tree but this - the ordering, the label a row carries, and (only the weekend
one) rows for positions holding no session at all. Sharing the *rules* rather than a base class is
what makes them impossible to drift apart and testable without a ``QApplication`` (DECISIONS -> UI).

**A slot row is the one thing a list of stored sessions cannot say.** ``weekend_slots``
reconstructs the whole weekend from the game's ``weekend_structure``, so a position nobody
captured still exists; a filtered list of stored rows simply would not show it, and "Practice 3
was skipped" would degrade to "Practice 3 is absent". Which of the two an empty slot is: a gap
*before* the last captured position was passed over (**Skipped**), one after it is still to come
(**not captured yet**). The rule moved here out of ``seasons/weekend_page._pending_slot_row``.

**Only fixtures reach Pending.** Measured against this database, both weekends holding an
uncaptured slot are entirely skipped - `3602002184`'s Practice 3, and `4046315905`'s Q1/Q2/Q3,
which sit before its stored Race. Pending is real behaviour with no live example, so the unit
tests are the only thing that covers it.

**Every attempt at a slot is a row of its own**, in the order they were driven, and nothing here
numbers them: which attempt counts is a judgement about the session, not a fact in the telemetry
(core invariant #5). Their recorded times are what tell them apart.
 """
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from ...domain.models import SessionResult
from ...domain.season import WeekendSlot, slot_for_session, weekend_slots
from ...protocol.reference import track_name
from ..formatting import slot_label


class SlotState(Enum):
    """How an uncaptured weekend position reads. The value is the words a view shows."""

    SKIPPED = "Skipped"
    PENDING = "not captured yet"


@dataclass(frozen=True)
class SessionRow:
    """One stored session, with the weekend context its card needs to title itself.

    ``slot`` is the *position*, so it carries every attempt at it and not only ``session``;
    a card reads ``is_sprint_race`` off it, which no single session can answer.
    """

    session: SessionResult
    slot: WeekendSlot
    label: str
    track: str


@dataclass(frozen=True)
class SlotRow:
    """A weekend position holding no session - skipped or still to come."""

    slot: WeekendSlot
    label: str
    state: SlotState


Row = SessionRow | SlotRow


def _recorded_key(session: SessionResult) -> tuple[bool, float]:
    """Capture-time sort key tolerating rows without one, mirroring ``season._recorded_order``.

    Stated here rather than imported because it is private there. Unstamped rows sort first, and
    the time is compared as a float because a stored row reads back naive while a freshly saved
    one is aware - comparing the two raises ``TypeError``.
    """
    recorded = session.recorded_at
    return (recorded is not None, recorded.timestamp() if recorded is not None else 0.0)


def _session_row(session: SessionResult, slot: WeekendSlot) -> SessionRow:
    """A session row carrying the label and track its card will show."""
    return SessionRow(
        session=session,
        slot=slot,
        label=slot_label(slot.session_type, slot.is_sprint_race),
        track=track_name(session.track_id),
    )


def overview_rows(all_sessions: Sequence[SessionResult], query: str = "") -> list[SessionRow]:
    """Every stored session, newest first, filtered by track or session label.

    ``all_sessions`` arrives in the store's own order (``recorded_at`` descending) and keeps it:
    the plain overview has no weekend to order by, and "what did I record last" is the question it
    answers. It is *also* the pool each row's slot is resolved against, which is what lets a card
    say "Sprint Race" - the session alone cannot, because both races report RACE (invariant #5).

    ``query`` matches case-insensitively against "<track> <label>"; empty shows everything.
    """
    needle = query.strip().lower()
    rows = [_session_row(session, slot_for_session(session, all_sessions)) 
            for session in all_sessions]
    if not needle:
        return rows
    return [row for row in rows if needle in f"{row.track} {row.label}".lower()]


def weekend_rows(sessions: Sequence[SessionResult]) -> list[Row]:
    """One weekend's rows in running order: every attempt at every slot, plus the gaps between.

    Pass the stored sessions of a single weekend (same ``weekend_link_id``). A slot holding two
    attempts yields two consecutive rows in the order they were driven; an empty slot yields one
    ``SlotRow``, Skipped when it sits before the last captured position and Pending when after it.
    """
    slots = weekend_slots(sessions)
    last_captured = max((slot.order for slot in slots if slot.sessions), default=-1)
    rows: list[Row] = []
    for slot in slots:
        if slot.sessions:
            rows.extend(_session_row(session, slot) for session in slot.sessions)
        else:
            rows.append(SlotRow(
                slot=slot,
                label=slot_label(slot.session_type, slot.is_sprint_race),
                state=SlotState.SKIPPED if slot.order < last_captured else SlotState.PENDING,
            ))
    return rows


def race_rows(rows: Sequence[Row]) -> list[SessionRow]:
    """The weekend's races, whose full classification a view shows beneath the list.

    *Which* sessions a view shows a full classification for is a rule like any other, so it lives
    here rather than in the page. The weekend page renders these below its cards rather than
    inside them: a classification belongs to the weekend's races, and every other session's result
    is already the summary line on its own card, so a table per session was height without an
    answer - a nine-session sprint weekend opened as nine full grids.

    **Both races**, in running order. The Sprint Race scores championship points too, so a sprint
    weekend has two classifications and they sit side by side. Every attempt at each, never one,
    because which attempt counts is a judgement about the session (core invariant #5). Empty while
    a weekend's races are all still to come.
    """
    return [row for row in rows if isinstance(row, SessionRow)
            and (row.slot.is_sprint_race or row.slot.is_grand_prix)]


def weekend_of(sessions: Sequence[SessionResult]) -> int | None:
    """The weekend a round's assigned sessions belong to, or None when it has none.

    A round with nothing assigned has no weekend to filter by, and that is the common case rather
    than an edge one - 88 of this database's 96 rounds. None is the honest answer; guessing from
    the round's track would be worse than silent, because a track is not a weekend (Suzuka has
    three here).

    Normally unanimous - every session of a weekend carries the same ``weekend_link_id``, and each
    of the eight populated rounds is - but nothing enforces it: a user can assign a re-driven
    weekend's Race beside the original weekend's Q1, and ``weekend_slots`` is explicit that mixing
    weekends is not meaningful. So the weekend holding most of the round's sessions wins, ties
    broken by the earliest recorded of the tied ones. Deterministic, and a judgement about
    nothing - the way ``grand_prix_session``'s tie-break is.
    """
    if not sessions:
        return None
    counts = Counter(session.weekend_link_id for session in sessions)
    most = max(counts.values())
    tied = {weekend for weekend, held in counts.items() if held == most}
    if len(tied) == 1:
        return next(iter(tied))
    earliest = min((session for session in sessions if session.weekend_link_id in tied), key=_recorded_key)
    return earliest.weekend_link_id
