"""Tests for weekend slot derivation - telling the Sprint Race apart from the Grand Prix.

Both report ``SessionType.RACE`` (15); only their position in the weekend distinguishes them.
``domain.season.weekend_slots`` resolves that from the game's ``weekend_structure`` (or, for
legacy rows without it, from ``session_link_id`` order).
"""
from __future__ import annotations

import unittest

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


def make(stype, link, *, structure=_SPRINT_STRUCTURE, uid=None):
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
        self.assertIsNotNone(slots[4].session)      # the sprint is captured
        self.assertTrue(slots[8].is_grand_prix)
        self.assertIsNone(slots[8].session)         # ...but the GP isn't
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


if __name__ == "__main__":
    unittest.main()
