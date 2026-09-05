"""Tests for weekend slot derivation - telling the Sprint Race apart from the Grand Prix.

Both report ``SessionType.RACE`` (15); only their position in the weekend distinguishes them.
``domain.season.weekend_slots`` resolves that from the game's ``weekend_structure`` (or, for
legacy rows without it, from ``session_link_id`` order).
"""
from __future__ import annotations

import unittest
from datetime import datetime

from f1telemetry.src.domain.models import SessionResult
from f1telemetry.src.domain.season import (
    grand_prix_session,
    slot_for_session,
    weekend_slots,
)
from f1telemetry.src.protocol.enums import Formula, SessionType, Weather

# The running order the game reports for a sprint weekend: Practice, three Sprint Shootouts,
# the Sprint Race (RACE=15), three Qualifying sessions, then the Grand Prix (RACE=15 again).
_SPRINT_STRUCTURE = (1, 10, 11, 12, 15, 5, 6, 7, 15)

_SPRINT_TYPES = (
    SessionType.PRACTICE_1,
    SessionType.SPRINT_SHOOTOUT_1,
    SessionType.SPRINT_SHOOTOUT_2,
    SessionType.SPRINT_SHOOTOUT_3,
    SessionType.RACE,               # Sprint Race
    SessionType.QUALIFYING_1,
    SessionType.QUALIFYING_2,
    SessionType.QUALIFYING_3,
    SessionType.RACE,               # Grand Prix
)
_WEEKEND_LINK = 3_602_001_984       # a real value from f1league.db
# What f1league.db actually stores for its sprint weekend: the Grand Prix reports RACE_2 (16), not
# a second RACE (15). The fixture above uses 15/15, which is the shape invariant #5 describes; both
# occur, and slot derivation must be indifferent because it works by position.
_REAL_SPRINT_STRUCTURE = (1, 10, 11, 12, 15, 5, 6, 7, 16)
_REAL_SPRINT_TYPES = _SPRINT_TYPES[:-1] + (SessionType.RACE_2,)

# A plain (non-sprint) weekend, and the capture times of the one slot in f1league.db that was
# driven twice: weekend 3602002284's Practice 2, stored as 8448489651239998166 (11:59:51) and
# 15062953857885398583 (12:07:47). Both attempts carry session_link_id 3602002294.
_PLAIN_STRUCTURE = (1, 2, 3, 5, 6, 7, 15)
_PRACTICE_2_LINK = _WEEKEND_LINK + 10
_FIRST_ATTEMPT = datetime(2026, 8, 23, 11, 59, 51)
_SECOND_ATTEMPT = datetime(2026, 8, 23, 12, 7, 47)

def make(stype, link, *, structure=_SPRINT_STRUCTURE, uid=None, recorded_at=None):
    """A bare SessionResult - only the fields slot derivation reads are meaningful here."""
    return SessionResult(
        session_uid=uid if uid is not None else link,
        season_link_id=1,
        weekend_link_id=_WEEKEND_LINK,
        session_link_id=link,
        game_format=2026,
        track_id=2,
        session_type=stype,
        formula=Formula.F1_MODERN,
        weather=Weather.CLEAR,
        total_laps=10,
        game_mode=28,
        player_vehicle_index=0,
        weekend_structure=structure,
        recorded_at=recorded_at, 
    )


def sprint_weekend(include_gp: bool, *, structure=_SPRINT_STRUCTURE):
    """Captured sessions for the sprint weekend, in scrambled order to prove sorting.

    Every position except the Grand Prix is captured; the GP is included only when asked.
    ``session_link_id`` increments by 10 per session, matching the game's real pattern.
    """
    positions = list(enumerate(_SPRINT_TYPES))
    if not include_gp:
        positions = positions[:-1]                  # drop the trailing Grand Prix
    sessions = [
        make(stype, _WEEKEND_LINK + 10 * i, structure=structure) for i, stype in positions
    ]
    return list(reversed(sessions))                 # hand them over out of order on purpose


class SprintWeekendTest(unittest.TestCase):
    def test_orders_the_whole_weekend(self):
        """Slots come back in true running order, not by ascending session-type value."""
        slots = weekend_slots(sprint_weekend(include_gp=True))
        self.assertEqual([int(s.session_type) for s in slots], list(_SPRINT_STRUCTURE))

    def test_sprint_and_grand_prix_are_distinguished(self):
        """The first RACE is the Sprint; the last RACE is the Grand Prix."""
        slots = weekend_slots(sprint_weekend(include_gp=True))
        sprint, grand_prix = slots[4], slots[8]

        self.assertTrue(sprint.is_sprint_race)
        self.assertFalse(sprint.is_grand_prix)
        self.assertFalse(grand_prix.is_sprint_race)
        self.assertTrue(grand_prix.is_grand_prix)

    def test_grand_prix_pending_when_only_sprint_is_captured(self):
        """A captured Sprint with the GP still to come reports the GP slot as pending."""
        sessions = sprint_weekend(include_gp=False)
        slots = weekend_slots(sessions)

        self.assertTrue(slots[4].is_sprint_race)
        self.assertTrue(slots[4].sessions)          # the sprint is captured
        self.assertTrue(slots[8].is_grand_prix)
        self.assertEqual(slots[8].sessions, ())     # ...but the GP isn't
        self.assertIsNone(grand_prix_session(sessions))

    def test_grand_prix_session_returns_the_final_race(self):
        """grand_prix_session picks the last race, never the Sprint."""
        sessions = sprint_weekend(include_gp=True)
        gp = grand_prix_session(sessions)
        self.assertIsNotNone(gp)
        self.assertEqual(gp.session_link_id, _WEEKEND_LINK + 10 * 8)

    def test_slot_for_session_labels_the_sprint_in_isolation(self):
        """The capture picker resolves a lone sprint capture via its weekend-mates."""
        sessions = sprint_weekend(include_gp=True)
        sprint = next(s for s in sessions if s.session_link_id == _WEEKEND_LINK + 10 * 4)
        slot = slot_for_session(sprint, sessions)
        self.assertTrue(slot.is_sprint_race)
        self.assertFalse(slot.is_grand_prix)


class LegacyFallbackTest(unittest.TestCase):
    """Rows saved before weekend_structure existed fall back to session_link_id order."""

    def test_sprint_is_a_sprint_when_a_later_session_exists(self):
        """Without a structure, a race that isn't the weekend's final session is a Sprint."""
        sessions = sprint_weekend(include_gp=False, structure=())
        slots = weekend_slots(sessions)
        race_slot = next(s for s in slots if int(s.session_type) == 15)

        self.assertTrue(race_slot.is_sprint_race)
        self.assertFalse(race_slot.is_grand_prix)
        self.assertIsNone(grand_prix_session(sessions))

    def test_final_race_is_the_grand_prix(self):
        """The last session by link id, when it's a race, is the Grand Prix."""
        sessions = sprint_weekend(include_gp=True, structure=())
        gp = grand_prix_session(sessions)
        self.assertIsNotNone(gp)
        self.assertEqual(gp.session_link_id, _WEEKEND_LINK + 10 * 8)


class NonSprintWeekendTest(unittest.TestCase):
    def test_lone_race_is_the_grand_prix(self):
        """A plain weekend's single race is the Grand Prix, labelled 'Race'."""
        structure = (1, 5, 6, 7, 15)
        race = make(SessionType.RACE, _WEEKEND_LINK + 40, structure=structure)
        slots = weekend_slots([race])
        race_slot = slots[-1]
        self.assertTrue(race_slot.is_grand_prix)
        self.assertFalse(race_slot.is_sprint_race)
        self.assertIs(grand_prix_session([race]), race)


class RaceTwoGrandPrixTest(unittest.TestCase):
    """A sprint weekend whose Grand Prix is RACE_2 - resolved by position, exactly as 15/15 is.

    Pinned because ``ui.formatting.slot_label`` leans on it: it renders every non-sprint race type
    as "Race", which is only honest while the weekend's *final* race is the Grand Prix whatever
    number the game put on it.
    """

    def _weekend(self):
        return [make(stype, _WEEKEND_LINK + 10 * i, structure=_REAL_SPRINT_STRUCTURE)
                for i, stype in enumerate(_REAL_SPRINT_TYPES)]

    def test_the_sprint_and_the_grand_prix_are_still_told_apart(self):
        slots = weekend_slots(self._weekend())
        self.assertTrue(slots[4].is_sprint_race, "the RACE (15) at position 4 is the Sprint")
        self.assertFalse(slots[4].is_grand_prix)
        self.assertTrue(slots[8].is_grand_prix, "the RACE_2 (16) at position 8 is the Grand Prix")
        self.assertFalse(slots[8].is_sprint_race)

    def test_the_grand_prix_session_is_the_race_2_one(self):
        weekend = self._weekend()
        self.assertIs(grand_prix_session(weekend), weekend[8])

    def test_slot_for_session_agrees_from_a_single_session(self):
        weekend = self._weekend()
        self.assertTrue(slot_for_session(weekend[4], weekend).is_sprint_race)
        self.assertTrue(slot_for_session(weekend[8], weekend).is_grand_prix)


class MultiAttemptSlotTest(unittest.TestCase):
    """A slot keeps every attempt at it, in the order they were driven.

    A restarted or re-driven session keeps the same season, weekend and session link ids, the same
    ``session_type`` and the same track - only ``session_uid`` and ``recorded_at`` differ - so
    keying sessions by type silently overwrote the earlier attempt, and which one survived was an
    accident of the order the store returned. The shape here is f1league.db's weekend
    ``3602002284``: eight stored sessions with Practice 2 driven twice, which rendered as seven.
    See DECISIONS -> UI.
    """

    def _weekend(self):
        """One session per structure position, with Practice 2 driven twice."""
        return [
            make(SessionType.PRACTICE_1, _WEEKEND_LINK, uid=1,
                 structure=_PLAIN_STRUCTURE, recorded_at=datetime(2026, 8, 23, 11, 21)),
            make(SessionType.PRACTICE_2, _PRACTICE_2_LINK, uid=2,
                 structure=_PLAIN_STRUCTURE, recorded_at=_FIRST_ATTEMPT),
            make(SessionType.PRACTICE_2, _PRACTICE_2_LINK, uid=3,
                 structure=_PLAIN_STRUCTURE, recorded_at=_SECOND_ATTEMPT),
            make(SessionType.PRACTICE_3, _WEEKEND_LINK + 20, uid=4,
                 structure=_PLAIN_STRUCTURE, recorded_at=datetime(2026, 8, 23, 15, 27)),
            make(SessionType.QUALIFYING_1, _WEEKEND_LINK + 30, uid=5,
                 structure=_PLAIN_STRUCTURE, recorded_at=datetime(2026, 8, 23, 15, 59)),
            make(SessionType.QUALIFYING_2, _WEEKEND_LINK + 40, uid=6,
                 structure=_PLAIN_STRUCTURE, recorded_at=datetime(2026, 8, 23, 16, 8)),
            make(SessionType.QUALIFYING_3, _WEEKEND_LINK + 50, uid=7,
                 structure=_PLAIN_STRUCTURE, recorded_at=datetime(2026, 8, 23, 16, 18)),
            make(SessionType.RACE, _WEEKEND_LINK + 60, uid=8,
                 structure=_PLAIN_STRUCTURE, recorded_at=datetime(2026, 8, 23, 16, 55)),
        ]

    def test_both_attempts_survive(self):
        """Eight sessions in, eight sessions out - the second Practice 2 used to vanish."""
        slots = weekend_slots(self._weekend())
        self.assertEqual(len(slots), len(_PLAIN_STRUCTURE))
        self.assertEqual([len(s.sessions) for s in slots], [1, 2, 1, 1, 1, 1, 1])
        self.assertEqual(sum(len(s.sessions) for s in slots), 8)

    def test_attempts_are_in_recorded_order(self):
        """Both attempts share a session_link_id, so only recorded_at can order them."""
        slots = weekend_slots(list(reversed(self._weekend())))   # handed over newest-first
        self.assertEqual([s.session_uid for s in slots[1].sessions], [2, 3])
        self.assertEqual([s.recorded_at for s in slots[1].sessions],
                         [_FIRST_ATTEMPT, _SECOND_ATTEMPT])

    def test_the_rest_of_the_weekend_is_untouched(self):
        """A repeat at one slot changes nothing about the positions around it."""
        slots = weekend_slots(self._weekend())
        self.assertEqual([int(s.session_type) for s in slots], list(_PLAIN_STRUCTURE))
        self.assertTrue(slots[6].is_grand_prix)
        self.assertFalse(any(s.is_sprint_race for s in slots))

    def test_slot_for_session_resolves_the_later_attempt(self):
        """The dropped attempt used to fall back to a bare order=0 slot with no weekend context."""
        weekend = self._weekend()
        second = next(s for s in weekend if s.session_uid == 3)
        slot = slot_for_session(second, weekend)

        self.assertEqual(slot.order, 1)
        self.assertEqual(int(slot.session_type), int(SessionType.PRACTICE_2))
        self.assertIn(second, slot.sessions)


class ReDrivenRaceTest(unittest.TestCase):
    """A repeat race attempt must not take the *next* race position.

    Race-type sessions are laid onto the weekend's race positions, and pairing sessions with
    positions handed a re-driven Sprint the Grand Prix's slot - so the real Grand Prix disappeared
    and ``grand_prix_session`` returned a Sprint, which would have scored the wrong session
    (invariant #5). Attempts at one slot share a ``session_link_id``, which is what groups them
    before they are placed.
    """

    def _weekend(self, *, extra_sprints=0, extra_gps=0):
        """The sprint weekend, optionally re-driving the Sprint or the Grand Prix."""
        sessions = [
            make(stype, _WEEKEND_LINK + 10 * i, uid=100 + i,
                 recorded_at=datetime(2026, 8, 23, 9 + i, 0))
            for i, stype in enumerate(_SPRINT_TYPES)
        ]
        sessions += [
            make(SessionType.RACE, _WEEKEND_LINK + 10 * 4, uid=800 + i,
                 recorded_at=datetime(2026, 8, 23, 13, 30 + 15 * i))
            for i in range(extra_sprints)
        ]
        sessions += [
            make(SessionType.RACE, _WEEKEND_LINK + 10 * 8, uid=900 + i,
                 recorded_at=datetime(2026, 8, 23, 17, 30 + 15 * i))
            for i in range(extra_gps)
        ]
        return sessions

    def test_a_re_driven_sprint_stays_in_the_sprint_slot(self):
        slots = weekend_slots(self._weekend(extra_sprints=1))

        self.assertEqual(len(slots[4].sessions), 2, "both Sprint attempts sit at the Sprint")
        self.assertTrue(slots[4].is_sprint_race)
        self.assertEqual(len(slots[8].sessions), 1, "the Grand Prix keeps its own position")
        self.assertTrue(slots[8].is_grand_prix)

    def test_the_grand_prix_is_still_the_grand_prix(self):
        """This returned the re-driven Sprint, so a Sprint's result would have scored as the GP."""
        weekend = self._weekend(extra_sprints=1)
        self.assertIs(grand_prix_session(weekend), weekend[8])

    def test_a_third_attempt_is_not_truncated(self):
        """Pairing sessions with positions dropped every attempt past the number of race slots."""
        weekend = self._weekend(extra_gps=2)
        slots = weekend_slots(weekend)

        self.assertEqual(len(slots[8].sessions), 3)
        self.assertEqual(sum(len(s.sessions) for s in slots), len(weekend))

    def test_grand_prix_session_returns_the_earliest_attempt(self):
        """A deterministic tie-break, not a judgement - assignment resolves this upstream."""
        weekend = self._weekend(extra_gps=1)
        self.assertIs(grand_prix_session(weekend), weekend[8])


class StructureCannotPlaceEverythingTest(unittest.TestCase):
    """A structure that can't account for every captured session isn't this weekend's structure.

    ``_weekend_structure`` takes the longest structure any session in the weekend carries, so a
    short or stale row can leave a captured type with no position at all - and dropping it is the
    very thing this branch exists to stop. The link-order fallback emits one slot per session, so
    the pending slots are what's given up, on a weekend whose structure already disagrees with
    what was captured.
    """

    def test_a_session_missing_from_the_structure_is_still_shown(self):
        structure = (1, 5, 6, 7, 15)                     # no Practice 2 position
        sessions = [
            make(SessionType.PRACTICE_1, _WEEKEND_LINK, structure=structure),
            make(SessionType.PRACTICE_2, _WEEKEND_LINK + 10, structure=structure),
            make(SessionType.RACE, _WEEKEND_LINK + 40, structure=structure),
        ]
        slots = weekend_slots(sessions)

        self.assertEqual(sum(len(s.sessions) for s in slots), len(sessions))
        self.assertEqual([int(s.session_type) for s in slots], [1, 2, 15])
        self.assertTrue(slots[-1].is_grand_prix, "the final race is still the Grand Prix")


class NoSessionIsEverDroppedTest(unittest.TestCase):
    """``weekend_slots`` is total: every session handed in comes back in exactly one slot.

    Stated once over every shape the other tests cover individually, because "a slot keeps every
    attempt" is the whole of A8 and each way of losing one hit a different shape.
    """

    def _cases(self):
        yield "sprint weekend", sprint_weekend(include_gp=True)
        yield "sprint weekend, GP pending", sprint_weekend(include_gp=False)
        yield "legacy rows, no structure", sprint_weekend(include_gp=True, structure=())
        yield "RACE_2 grand prix", [
            make(stype, _WEEKEND_LINK + 10 * i, structure=_REAL_SPRINT_STRUCTURE)
            for i, stype in enumerate(_REAL_SPRINT_TYPES)
        ]
        yield "a slot driven twice", MultiAttemptSlotTest()._weekend()
        yield "a re-driven sprint", ReDrivenRaceTest()._weekend(extra_sprints=1)
        yield "one lone race", [make(SessionType.RACE, _WEEKEND_LINK + 60,
                                     structure=_PLAIN_STRUCTURE)]

    def test_every_session_lands_in_a_slot(self):
        for name, sessions in self._cases():
            with self.subTest(name):
                slots = weekend_slots(sessions)
                placed = [s.session_uid for slot in slots for s in slot.sessions]
                self.assertCountEqual(placed, [s.session_uid for s in sessions])

    def test_an_empty_weekend_has_no_slots(self):
        self.assertEqual(weekend_slots([]), [])


if __name__ == "__main__":
    unittest.main()
