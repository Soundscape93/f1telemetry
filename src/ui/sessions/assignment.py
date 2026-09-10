"""What an assignment proposes - Qt-free, so the rules are unit-testable the way
``weekend_view``, ``race_control`` and ``league_names`` are.

The weekend-filtered overview writes ``season_assignments``, and this module holds everything
that decides *what to offer* - never what to write. Both rules end in a confirmation the user can
decline (DECISIONS -> Storage), so nothing here touches a store and nothing here needs a
``QApplication``: a rule that did would be in the wrong file.

**Weekend propagation - every mode.** Assigning one session to a round offers every other stored
session recorded in the same weekend. Licensed by the data rather than assumed: all 13 weekends
in this database hold exactly one ``track_id``, and every round assigned by hand holds exactly one
``weekend_link_id`` (TELEMETRY_NOTES -> *The three link identifiers*). It also adds no new trust -
``domain/season.slot_for_session`` and the laps surface's track-map cache already group on this id.

**A slot with several attempts is never propagated.** Two attempts at one slot are
indistinguishable in the telemetry, so offering both would fill a slot twice and offering one
would be the silent choice this design refuses. Such a slot is left *to* the user, not withheld
from them: ``picker_rows`` lists every attempt and each is assignable by hand. Only the automatic
offer stands back, and ``WeekendProposal.held_back`` names the slot so the dialog can say why.

**Season inference - career modes only.** ``season_link_id`` names a season only where it *differs*
from ``weekend_link_id``; in Online Custom / League Racing and in ``game_mode`` 4 the game reports
the weekend's own id there, so grouping by it is grouping by weekend. Where a career id does exist
it names the **season**, never the **round** - no identifier carries a round number - so the round
comes from a track match against that season's calendar.

**A track appearing several times in one calendar is answered, not refused**. The matching rounds
are taken in calendar order and the first one that does not already hold a *different* weekend wins:
Monza at rounds 2, 8 and 16 suggests 2, then 8 once 2 is taken, then 16, and nothing once all three
are. A round already holding **this session's own** weekend is the answer rather than an obstacle -
the weekend is the stronger evidence, and a round holds exactly one weekend. This is a suggestion
the user still has to act on, so a calendar that repeats a track gets a starting point instead of a shrug.

**Season inference has one live check, and marks nothing at rest.** Measured 2026-09-07 against
``f1league.db``: only the four career weekends carry a season id at all, and the rule answers for
their 28 sessions - but **every answer names the round that session is already assigned to**, so
with everything assigned no picker row is marked, across all 96 rounds and both filter states.
Checked live 2026-09-10: with the Jeddah weekend (season 2, round 5) unassigned by hand, the picker
marked its sessions suggested for round 5 and left both Practice 2 attempts unmarked, as the rule
above requires. The repeated-track rule has no live example - no calendar here repeats a track -
and its unit tests are the only cover it has.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Sequence

from ...domain.models import SessionResult
from ...domain.season import Season, weekend_slots
from ...protocol.reference import track_name
from ..formatting import recorded_label, slot_label

Placement = tuple[int, int]     # (season_id, round_number)


@dataclass(frozen=True)
class ProposedSession:
    """One session the automatic offer would assign, with what assigning it would undo."""

    session: SessionResult
    label: str
    placement: Placement | None     # where it sits now; not None means accepting *moves* it.


@dataclass(frozen=True)
class WeekendProposal:
    """What assigning one session offers to do with the rest of its weekend.

    ``held_back`` names the slots the multi-attempt rule refused, so the confirmation can say why
    a session the user can see is not in the list. Silence there would be close to the silent
    choice the whole design refuses.
    """

    sessions: tuple[ProposedSession, ...] = ()
    held_back: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssignRow:
    """One session the picker offers for a round, with everything a row has to say about it."""

    session: SessionResult
    label: str
    track: str
    weekend: str                    # when the weekend was recorded, and how big it is
    placement: Placement | None     # None = unassigned; otherwise picking it moves it
    suggested: bool                 # its own identifiers point at the round being filled
    attempts: int                   # how many attemts share its slot; > 1 is never suggested


def _recorded_key(session: SessionResult) -> tuple[bool, float]:
    """Capture-time sort key tolerating rows without one.

    Restated rather than imported, exactly as ``weekend_view._recorded_key`` restates
    ``season._recorded_order``: both are private to their module. Unstamped rows sort first, and
    the time is compared as a float because a stored row reads back naive while a freshly saved
    one is aware - comparing the two raises ``TypeError``.
    """
    recorded = session.recorded_at
    return (recorded is not None, recorded.timestamp() if recorded is not None else 0.0)


def _attempt_count(sessions: Sequence[SessionResult]) -> Counter[int]:
    """How many attempts share each ``session_link_id`` in one weekend.

    The link id rather than the ``WeekendSlot``, deliberately. A retry keeps the whole identifier
    and changes only ``session_uid`` / ``recorded_at`` (TELEMETRY_NOTES), so this is exact in all
    72 measured sessions - while ``weekend_slots`` falls back to one slot per session on a row with
    no stored ``weekend_structure``, which would split a repeat attempt into two single-session
    slots and silently defeat the rule that exists to catch it.
    """
    return Counter(session.session_link_id for session in sessions)


def _repeated_links(sessions: Sequence[SessionResult]) -> set[int]:
    """The ``session_link_id``s this weekend holds more than one attempt at."""
    return {link for link, held in _attempt_count(sessions).items() if held > 1}


def _weekend_mates(session: SessionResult, all_sessions: Sequence[SessionResult]) -> list[SessionResult]:
    """Every stored session recorded in the same weekend, the session itself included."""
    return [s for s in all_sessions if s.weekend_link_id == session.weekend_link_id]


def _running_order(sessions: Sequence[SessionResult]) -> list[tuple[SessionResult, object]]:
    """One weekend's sessions paired with their slots, in the order the weekend ran.

    Flattens ``weekend_slots``, so a slot holding two attempts yields both in the order they were
    driven and an uncaptured slot yields nothing. The slot is carried alongside because a label
    needs ``is_sprint_race``, which no single session can answer (core invariant #5).
    """
    return [(session, slot) for slot in weekend_slots(sessions) for session in slot.sessions]


def _weekend_summary(sessions: Sequence[SessionResult]) -> str:
    """When the weekend was recorded, and how many sessions it holds - the picker's Weekend cell."""
    count = len(sessions)
    earliest = min(sessions, key=_recorded_key)
    return f"{recorded_label(earliest.recorded_at)}  ·  {count} session{'' if count == 1 else 's'}"


def weekend_proposal(anchor: SessionResult, all_sessions: Sequence[SessionResult],
                     placements: dict[int, Placement], target: Placement) -> WeekendProposal:
    """The rest of ``anchor``'s weekend, offered for the round ``anchor`` was just assigned to.

    Returned in the weekend's running order, which is the order the page lists them in. Two things
    are left out and nothing else is:

    * **a session already in ``target``** - there is nothing to do to it;
    * **every attempt at a slot holding more than one** - see the module docstring. The slot's
      label goes to ``held_back`` instead, but only while at least one of its attempts is still
      outside the round: a slot wholly inside it is not being held back from anything.

    A session assigned to a *different* round **is** offered, and its ``placement`` says so. That
    is what makes "this weekend was filed under the wrong round" one pick and one confirmation
    rather than a session at a time; the confirmation names the moves, and the user can decline.
    """
    weekend = _weekend_mates(anchor, all_sessions)
    repeated = _repeated_links(weekend)
    offered: list[ProposedSession] = []
    held_back: list[str] = []
    for slot in weekend_slots(weekend):
        label = slot_label(slot.session_type, slot.is_sprint_race)
        outside = [s for s in slot.sessions
                   if s.session_uid != anchor.session_uid
                   and placements.get(s.session_uid) != target]
        if any(s.session_link_id in repeated for s in slot.sessions):
            if outside:
                held_back.append(label)
            continue
        offered.extend(
            ProposedSession(session=session, label=label,
                            placement=placements.get(session.session_uid))
            for session in outside)
    return WeekendProposal(sessions=tuple(offered), held_back=tuple(held_back))


def _career_season(session: SessionResult, all_sessions: Sequence[SessionResult],
                   placements: dict[int, Placement]) -> int | None:
    """The season this session's career identifier already names, or None if it names none.

    Seasons are user-authored and carry no link id, so the only bridge from a career identifier to
    a season is a session already placed in one. Two seasons sharing the identifier is ambiguous
    and answers None - ask rather than guess.
    """
    named = {placements[s.session_uid][0] for s in all_sessions
             if s.season_link_id == session.season_link_id and s.session_uid in placements}
    return next(iter(named)) if len(named) == 1 else None


def _weekends_by_round(season_id: int, all_sessions: Sequence[SessionResult],
                       placements: dict[int, Placement]) -> dict[int, set[int]]:
    """Which weekends each round of one season already holds."""
    weekend_of_uid = {s.session_uid: s.weekend_link_id for s in all_sessions}
    holders: dict[int, set[int]] = {}
    for uid, (placed_season, round_number) in placements.items():
        if placed_season != season_id or uid not in weekend_of_uid:
            continue
        holders.setdefault(round_number, set()).add(weekend_of_uid[uid])
    return holders


def suggested_placement(session: SessionResult, all_sessions: Sequence[SessionResult],
                        seasons: Sequence[Season], placements: dict[int, Placement]) -> Placement | None:
    """Where this session's own identifiers say it belongs, or None where they say nothing.

    A suggestion and never a write: the picker marks the row and sorts it first, and the user
    still has to select it and press Assign. Four things each answer None on their own - the
    season id is really the weekend id (every online mode), the slot holds several attempts, no
    single season is named by the career id, and no matching round is free.

    The round comes from the calendar, because no identifier carries a round number. Matching
    rounds are taken in calendar order and the first that holds no *other* weekend wins; a round
    already holding this session's own weekend is the answer rather than an obstacle, since a
    round holds exactly one weekend and the weekend is the stronger evidence.
    """
    if session.season_link_id == session.weekend_link_id:
        return None
    weekend = _weekend_mates(session, all_sessions)
    if session.session_link_id in _repeated_links(weekend):
        return None
    season_id = _career_season(session, all_sessions, placements)
    season = next((s for s in seasons if s.season_id == season_id), None)
    if season is None:
        return None
    holders = _weekends_by_round(season_id, all_sessions, placements)
    matching = [round for round in sorted(season.rounds, key=lambda r: r.round_number)
                if round.track_id == session.track_id]
    for round in matching:
        if session.weekend_link_id in holders.get(round.round_number, set()):
            return (season_id, round.round_number)
    for round in matching:
        if not holders.get(round.round_number):
            return (season_id, round.round_number)
    return None


def picker_rows(all_sessions: Sequence[SessionResult], seasons: Sequence[Season],
                placements: dict[int, Placement], target: Placement,
                track_id: int | None = None) -> list[AssignRow]:
    """The sessions the picker offers for one round, suggestions first then weekend by weekend.

    ``track_id`` filters to one track - the round's, which is the picker's default - and None
    shows every stored session. A session already in ``target`` is left out: it is a card on the
    page behind the dialog. A session in *another* round stays, marked, because assigning it
    **moves** it, which is the repair for a misfiled weekend and hiding it would make that session
    unfindable.

    Ordering is suggestions first, then the unassigned, then whole weekends newest first with
    each weekend in its own running order. The user is really choosing a *weekend* - the proposal
    that follows offers the rest of it - so keeping a weekend's sessions together is what makes
    the list readable. Unassigned before assigned because picking an assigned session *moves* it:
    the uncomplicated answer to "fill this round" belongs above the one with a consequence.

    Both attempts at a multi-attempt slot appear here, neither suggested. The rule that refuses to
    *propagate* them does not take the choice away from the user; it declines to make it for them.
    """
    by_weekend: dict[int, list[SessionResult]] = {}
    for session in all_sessions:
        by_weekend.setdefault(session.weekend_link_id, []).append(session)

    keyed: list[tuple[tuple[bool, bool, float, int], AssignRow]] = []
    for sessions in by_weekend.values():
        attempts = _attempt_count(sessions)
        summary = _weekend_summary(sessions)
        start = _recorded_key(min(sessions, key=_recorded_key))[1]
        for order, (session, slot) in enumerate(_running_order(sessions)):
            if placements.get(session.session_uid) == target:
                continue
            if track_id is not None and session.track_id != track_id:
                continue
            suggested = suggested_placement(
                session, all_sessions, seasons, placements) == target
            placement = placements.get(session.session_uid)
            keyed.append(((not suggested, placement is not None, -start, order), AssignRow(
                session=session,
                label=slot_label(slot.session_type, slot.is_sprint_race),
                track=track_name(session.track_id),
                weekend=summary,
                placement=placement,
                suggested=suggested,
                attempts=attempts[session.session_link_id],
            )))
    keyed.sort(key=lambda pair: pair[0])
    return [row for _key, row in keyed]
