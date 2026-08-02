"""The assigned-round invariant behind the calendar editor (PRIORITIES -> E6). Qt-free."""
from __future__ import annotations

import unittest

from f1telemetry.src.domain.calendars import (
    CONFLICT_REMOVED,
    CONFLICT_RETRACKED,
    calendar_conflicts,
    calendar_from_track_ids,
    describe_conflicts,
    locked_rounds,
)
from f1telemetry.src.domain.season import SeasonRound


class LockedRoundsTest(unittest.TestCase):
    def setUp(self):
        self.calendar = calendar_from_track_ids([0, 2, 13, 3, 29])   # rounds 1..5

    def test_selects_only_assigned_rounds_in_order(self):
        locked = locked_rounds(self.calendar, {5, 2})
        self.assertEqual([(r.round_number, r.track_id) for r in locked], [(2, 2), (5, 29)])

    def test_no_assignments_locks_nothing(self):
        self.assertEqual(locked_rounds(self.calendar, set()), ())

    def test_an_assignment_beyond_the_calendar_is_ignored(self):
        """A stale orphan from before the invariant existed must not crash the editor."""
        self.assertEqual(locked_rounds(self.calendar, {99}), ())


class CalendarConflictsTest(unittest.TestCase):
    def setUp(self):
        self.calendar = calendar_from_track_ids([0, 2, 13, 3, 29])   # rounds 1..5
        self.locked = locked_rounds(self.calendar, {2})              # round 2 = Shanghai (2)

    def test_unchanged_calendar_is_safe(self):
        self.assertEqual(calendar_conflicts(self.calendar, self.locked), ())

    def test_appending_after_the_locked_round_is_safe(self):
        proposed = calendar_from_track_ids([0, 2, 13, 3, 29, 11])
        self.assertEqual(calendar_conflicts(proposed, self.locked), ())

    def test_reordering_unassigned_rounds_around_a_locked_one_is_safe(self):
        proposed = calendar_from_track_ids([0, 2, 3, 29, 13])        # 3/4/5 shuffled, 2 untouched
        self.assertEqual(calendar_conflicts(proposed, self.locked), ())

    def test_moving_the_locked_round_conflicts(self):
        proposed = calendar_from_track_ids([2, 0, 13, 3, 29])        # swap rounds 1 and 2
        conflicts = calendar_conflicts(proposed, self.locked)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].round_number, 2)
        self.assertEqual(conflicts[0].reason, CONFLICT_RETRACKED)
        self.assertEqual(conflicts[0].proposed_track_id, 0)

    def test_inserting_before_the_locked_round_conflicts(self):
        """The case a plain "no reordering" rule would miss: nothing is dragged, but round 2 moves."""
        proposed = calendar_from_track_ids([11, 0, 2, 13, 3, 29])
        conflicts = calendar_conflicts(proposed, self.locked)
        self.assertEqual([(c.round_number, c.reason) for c in conflicts],
                         [(2, CONFLICT_RETRACKED)])

    def test_deleting_before_the_locked_round_conflicts(self):
        proposed = calendar_from_track_ids([2, 13, 3, 29])           # round 1 removed
        self.assertEqual([c.reason for c in calendar_conflicts(proposed, self.locked)],
                         [CONFLICT_RETRACKED])

    def test_truncating_past_the_locked_round_conflicts_as_removed(self):
        locked = locked_rounds(self.calendar, {5})
        proposed = calendar_from_track_ids([0, 2, 13])
        conflicts = calendar_conflicts(proposed, locked)
        self.assertEqual([(c.round_number, c.reason) for c in conflicts], [(5, CONFLICT_REMOVED)])

    def test_a_duplicate_track_keeping_its_position_is_safe(self):
        """Sandbox modes allow repeats, so identity is positional - round 2 is still Shanghai."""
        proposed = calendar_from_track_ids([0, 2, 2, 13, 3, 29])
        self.assertEqual(calendar_conflicts(proposed, self.locked), ())

    def test_every_broken_round_is_reported_not_just_the_first(self):
        locked = locked_rounds(self.calendar, {2, 4, 5})
        proposed = calendar_from_track_ids([0])
        self.assertEqual([c.round_number for c in calendar_conflicts(proposed, locked)], [2, 4, 5])


class DescribeConflictsTest(unittest.TestCase):
    def test_names_the_round_and_both_tracks(self):
        calendar = calendar_from_track_ids([0, 2])
        text = describe_conflicts(
            calendar_conflicts(calendar_from_track_ids([2, 0]), locked_rounds(calendar, {1}))
        )
        self.assertIn("Round 1", text)
        self.assertIn("Melbourne", text)        # what it is now
        self.assertIn("Shanghai", text)         # what the edit would make it

    def test_removal_says_removed(self):
        calendar = calendar_from_track_ids([0, 2])
        text = describe_conflicts(
            calendar_conflicts(calendar_from_track_ids([0]), locked_rounds(calendar, {2}))
        )
        self.assertIn("Round 2", text)
        self.assertIn("removed", text)


if __name__ == "__main__":
    unittest.main()
