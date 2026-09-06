"""Which rows a Sessions overview shows, and in what order (the rules the two overviews share).

Qt-free by design: anything deciding which rows a view shows lives in ``ui/sessions/weekend_view``
precisely so it can be asserted without a ``QApplication`` (DECISIONS -> UI). A rule that needed
one would be in the wrong file.

The weekend fixtures are this database's own shapes. `3602002184` skipped Practice 3 and captured
everything else; `4046315905` holds a single Race with Q1/Q2/Q3 before it, all three **skipped**
rather than pending - which is what the live database says and what DECISIONS said wrongly until
this branch. Pending has no live example at all: those are the only two weekends here with an
uncaptured slot and both are entirely skipped, so the pending cases below are the only cover it
has.
"""
from __future__ import annotations

import unittest
from datetime import datetime

from f1telemetry.src.domain.models import SessionResult
from f1telemetry.src.protocol.enums import Formula, SessionType, Weather
from f1telemetry.src.ui.sessions.weekend_view import (
    SessionRow,
    SlotRow,
    SlotState,
    overview_rows,
    race_rows,
    weekend_of,
    weekend_rows,
)

# A plain weekend and a sprint weekend, as the game reports them. The sprint one is this
# database's real shape: the Sprint is RACE (15) and the Grand Prix RACE_2 (16).
_PLAIN = (1, 2, 3, 5, 6, 7, 15)
_SPRINT = (1, 10, 11, 12, 15, 5, 6, 7, 16)
_PLAIN_TYPES = (SessionType.PRACTICE_1, SessionType.PRACTICE_2, SessionType.PRACTICE_3,
                SessionType.QUALIFYING_1, SessionType.QUALIFYING_2, SessionType.QUALIFYING_3,
                SessionType.RACE)
_WEEKEND = 3_602_002_184        # a real value from f1league.db
_MELBOURNE = 0                  # track_id -> "Melbourne"


def make(stype, link, *, structure=_PLAIN, weekend=_WEEKEND, uid=None, recorded_at=None,
         track_id=_MELBOURNE):
    """A bare SessionResult - only the fields the row rules read are meaningful here."""
    return SessionResult(
        session_uid=uid if uid is not None else link,
        season_link_id=1,
        weekend_link_id=weekend,
        session_link_id=link,
        game_format=2026,
        track_id=track_id,
        session_type=stype,
        formula=Formula.F1_MODERN,
        weather=Weather.CLEAR,
        total_laps=10,
        game_mode=28,
        player_vehicle_index=0,
        weekend_structure=structure,
        recorded_at=recorded_at,
    )


def plain_weekend(*, skip=()):
    """A plain weekend's captured sessions, leaving out the slots named in ``skip`` (by index)."""
    return [make(stype, _WEEKEND + 10 * i)
            for i, stype in enumerate(_PLAIN_TYPES) if i not in skip]


class WeekendRowsTest(unittest.TestCase):
    """``weekend_rows`` - one weekend, in running order, gaps included."""

    def test_every_slot_captured_is_all_session_rows(self):
        rows = weekend_rows(plain_weekend())
        self.assertEqual(7, len(rows))
        self.assertTrue(all(isinstance(row, SessionRow) for row in rows))
        self.assertEqual(
            ["Practice 1", "Practice 2", "Practice 3", "Qualifying 1", "Qualifying 2",
             "Qualifying 3", "Race"],
            [row.label for row in rows])

    def test_a_gap_before_the_last_captured_session_is_skipped(self):
        """Weekend 3602002184: Practice 3 was never driven, the Race was."""
        rows = weekend_rows(plain_weekend(skip=(2,)))
        self.assertEqual(7, len(rows))
        gap = rows[2]
        self.assertIsInstance(gap, SlotRow)
        self.assertEqual("Practice 3", gap.label)
        self.assertEqual(SlotState.SKIPPED, gap.state)
        self.assertEqual("Skipped", gap.state.value)

    def test_only_a_stored_race_leaves_every_earlier_slot_skipped(self):
        """Weekend 4046315905: a Race at index 3 of [Q1, Q2, Q3, Race], and it is the last
        captured - so the three qualifying slots before it are Skipped, not pending. DECISIONS
        said pending here until this branch; the database says otherwise."""
        race = make(SessionType.RACE, _WEEKEND + 30, structure=(5, 6, 7, 15))
        rows = weekend_rows([race])
        self.assertEqual(
            [(SlotState.SKIPPED, "Qualifying 1"), (SlotState.SKIPPED, "Qualifying 2"),
             (SlotState.SKIPPED, "Qualifying 3")],
            [(row.state, row.label) for row in rows if isinstance(row, SlotRow)])
        self.assertEqual(["Race"], [row.label for row in rows if isinstance(row, SessionRow)])

    def test_a_gap_after_the_last_captured_session_is_still_to_come(self):
        """No live example: this database has no pending slot anywhere (see the module docstring)."""
        rows = weekend_rows(plain_weekend(skip=(5, 6)))
        pending = [row for row in rows if isinstance(row, SlotRow)]
        self.assertEqual([SlotState.PENDING, SlotState.PENDING], [row.state for row in pending])
        self.assertEqual(["Qualifying 3", "Race"], [row.label for row in pending])
        self.assertEqual("not captured yet", pending[0].state.value)

    def test_gaps_on_both_sides_of_the_last_captured_session(self):
        rows = weekend_rows(plain_weekend(skip=(2, 6)))
        self.assertEqual(
            [("Practice 3", SlotState.SKIPPED), ("Race", SlotState.PENDING)],
            [(row.label, row.state) for row in rows if isinstance(row, SlotRow)])

    def test_two_attempts_at_one_slot_are_two_rows_in_recorded_order(self):
        """Weekend 3602002284's Practice 2, driven twice. Both rows, both labelled the same, and
        nothing numbers them - the recorded time is what tells them apart (invariant #5)."""
        first = make(SessionType.PRACTICE_2, _WEEKEND + 10, uid=8448489651239998166,
                     recorded_at=datetime(2026, 8, 23, 11, 59, 51))
        second = make(SessionType.PRACTICE_2, _WEEKEND + 10, uid=15062953857885398583,
                      recorded_at=datetime(2026, 8, 23, 12, 7, 47))
        others = [s for s in plain_weekend(skip=(1,))]
        rows = weekend_rows(others + [second, first])
        self.assertEqual(8, len(rows))
        self.assertEqual(["Practice 2", "Practice 2"], [rows[1].label, rows[2].label])
        self.assertEqual([8448489651239998166, 15062953857885398583],
                         [rows[1].session.session_uid, rows[2].session.session_uid])

    def test_a_sprint_weekend_names_both_races_by_position(self):
        sessions = [make(stype, _WEEKEND + 10 * i, structure=_SPRINT) for i, stype in enumerate((
            SessionType.PRACTICE_1, SessionType.SPRINT_SHOOTOUT_1, SessionType.SPRINT_SHOOTOUT_2,
            SessionType.SPRINT_SHOOTOUT_3, SessionType.RACE, SessionType.QUALIFYING_1,
            SessionType.QUALIFYING_2, SessionType.QUALIFYING_3, SessionType.RACE_2))]
        rows = weekend_rows(sessions)
        self.assertEqual("Sprint Race", rows[4].label)
        self.assertEqual("Race", rows[8].label)
        self.assertTrue(rows[4].slot.is_sprint_race)
        self.assertTrue(rows[8].slot.is_grand_prix)

    def test_no_sessions_is_no_rows(self):
        self.assertEqual([], weekend_rows([]))

    def test_a_session_row_carries_its_track(self):
        rows = weekend_rows(plain_weekend())
        self.assertEqual("Melbourne", rows[0].track)


class RaceRowsTest(unittest.TestCase):
    """``race_rows`` - which sessions the weekend page shows a full classification for."""

    def _sprint_weekend(self, *, skip=()):
        types = (SessionType.PRACTICE_1, SessionType.SPRINT_SHOOTOUT_1,
                 SessionType.SPRINT_SHOOTOUT_2, SessionType.SPRINT_SHOOTOUT_3,
                 SessionType.RACE, SessionType.QUALIFYING_1, SessionType.QUALIFYING_2,
                 SessionType.QUALIFYING_3, SessionType.RACE_2)
        return [make(stype, _WEEKEND + 10 * i, structure=_SPRINT)
                for i, stype in enumerate(types) if i not in skip]

    def test_a_plain_weekend_offers_its_one_race(self):
        races = race_rows(weekend_rows(plain_weekend()))
        self.assertEqual(["Race"], [row.label for row in races])
        self.assertTrue(races[0].slot.is_grand_prix)

    def test_a_sprint_weekend_offers_both_races_in_running_order(self):
        """The Sprint Race scores points too, so it earns a classification of its own - and it
        comes first, because that is when it was driven (invariant #5 decides which is which)."""
        races = race_rows(weekend_rows(self._sprint_weekend()))
        self.assertEqual(["Sprint Race", "Race"], [row.label for row in races])
        self.assertTrue(races[0].slot.is_sprint_race)
        self.assertTrue(races[1].slot.is_grand_prix)

    def test_no_practice_or_qualifying_session_ever_earns_one(self):
        races = race_rows(weekend_rows(self._sprint_weekend()))
        self.assertTrue(all(row.slot.is_sprint_race or row.slot.is_grand_prix for row in races))
        self.assertEqual(2, len(races))

    def test_a_weekend_whose_race_is_not_captured_offers_nothing(self):
        """Still being driven: the row simply is not there yet."""
        self.assertEqual([], race_rows(weekend_rows(plain_weekend(skip=(6,)))))

    def test_a_sprint_weekend_missing_its_grand_prix_still_offers_the_sprint(self):
        races = race_rows(weekend_rows(self._sprint_weekend(skip=(8,))))
        self.assertEqual(["Sprint Race"], [row.label for row in races])

    def test_an_uncaptured_grand_prix_is_pending_and_never_skipped(self):
        """Nothing in a weekend comes after the Grand Prix, so its slot can never be a gap the
        weekend moved past - the state that leaves it out of the row is always Pending."""
        rows = weekend_rows(self._sprint_weekend(skip=(8,)))
        self.assertEqual(SlotState.PENDING, rows[-1].state)

    def test_a_race_driven_twice_offers_both_in_recorded_order(self):
        """The app never picks which attempt counts, here no more than anywhere else."""
        first = make(SessionType.RACE, _WEEKEND + 60, uid=11,
                     recorded_at=datetime(2026, 8, 19, 14, 58))
        second = make(SessionType.RACE, _WEEKEND + 60, uid=22,
                      recorded_at=datetime(2026, 8, 19, 16, 12))
        races = race_rows(weekend_rows(plain_weekend(skip=(6,)) + [second, first]))
        self.assertEqual([11, 22], [row.session.session_uid for row in races])
        self.assertEqual(["Race", "Race"], [row.label for row in races])

    def test_no_rows_at_all_offers_nothing(self):
        self.assertEqual([], race_rows([]))


class OverviewRowsTest(unittest.TestCase):
    """``overview_rows`` - every stored session, the store's order, one filter."""

    def setUp(self):
        # Two weekends at different tracks, handed over newest-first the way the store returns.
        self.sprint = [make(stype, 100 + 10 * i, structure=_SPRINT, weekend=100, uid=100 + i,
                            track_id=1) for i, stype in enumerate((
                                SessionType.RACE, SessionType.QUALIFYING_3, SessionType.RACE_2))]
        self.plain = [make(stype, 200 + 10 * i, weekend=200, uid=200 + i, track_id=_MELBOURNE)
                      for i, stype in enumerate((SessionType.PRACTICE_1, SessionType.RACE))]

    def test_store_order_is_kept_and_every_session_gets_a_row(self):
        sessions = self.plain + self.sprint
        rows = overview_rows(sessions)
        self.assertEqual([s.session_uid for s in sessions],
                         [row.session.session_uid for row in rows])

    def test_a_row_is_labelled_from_its_own_weekend_not_its_type(self):
        """The pool is the whole store, which is what lets a Sprint Race be named one: on its own
        a session cannot say, because both races report RACE (invariant #5)."""
        rows = overview_rows(self.plain + self.sprint)
        by_uid = {row.session.session_uid: row.label for row in rows}
        self.assertEqual("Sprint Race", by_uid[100])
        self.assertEqual("Race", by_uid[102])
        self.assertEqual("Race", by_uid[201])

    def test_the_filter_matches_the_track(self):
        rows = overview_rows(self.plain + self.sprint, "melbourne")
        self.assertEqual({200, 201}, {row.session.session_uid for row in rows})

    def test_the_filter_matches_the_label_and_ignores_case_and_padding(self):
        rows = overview_rows(self.plain + self.sprint, "  SPRINT ")
        self.assertEqual({100}, {row.session.session_uid for row in rows})

    def test_an_empty_filter_shows_everything(self):
        self.assertEqual(5, len(overview_rows(self.plain + self.sprint, "   ")))

    def test_a_filter_matching_nothing_shows_nothing(self):
        self.assertEqual([], overview_rows(self.plain + self.sprint, "monaco"))


class WeekendOfTest(unittest.TestCase):
    """``weekend_of`` - which weekend a round's assigned sessions belong to."""

    def test_a_round_with_nothing_assigned_has_no_weekend(self):
        """88 of this database's 96 rounds. None is the answer, not a guess from the track."""
        self.assertIsNone(weekend_of([]))

    def test_the_unanimous_case(self):
        self.assertEqual(_WEEKEND, weekend_of(plain_weekend()))

    def test_a_mixed_round_takes_the_weekend_holding_most_of_it(self):
        sessions = plain_weekend()[:3] + [make(SessionType.RACE, 999, weekend=999)]
        self.assertEqual(_WEEKEND, weekend_of(sessions))

    def test_a_tie_is_broken_by_the_earliest_recorded(self):
        early = make(SessionType.RACE, 10, weekend=10, uid=1,
                     recorded_at=datetime(2026, 8, 23, 9, 0))
        late = make(SessionType.RACE, 20, weekend=20, uid=2,
                    recorded_at=datetime(2026, 8, 23, 17, 0))
        self.assertEqual(10, weekend_of([late, early]))
        self.assertEqual(10, weekend_of([early, late]))

    def test_a_tie_between_unstamped_sessions_still_answers(self):
        """``recorded_at`` is optional, and comparing a naive time to an aware one raises - so the
        key sorts unstamped rows first rather than letting the tie-break throw."""
        one = make(SessionType.RACE, 10, weekend=10, uid=1)
        two = make(SessionType.RACE, 20, weekend=20, uid=2,
                   recorded_at=datetime(2026, 8, 23, 17, 0))
        self.assertEqual(10, weekend_of([two, one]))


if __name__ == "__main__":
    unittest.main()
    