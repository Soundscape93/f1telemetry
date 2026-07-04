from __future__ import annotations

import unittest

from f1telemetry.src.domain.calendars import (
    CalendarStyle,
    calendar_from_track_ids,
    calendar_rules,
    official_calendar,
    selectable_tracks,
)
from f1telemetry.src.domain.season import SeasonMode
from f1telemetry.src.protocol.reference import TRACK_NAMES, track_name

_CAREER_MODES = (SeasonMode.MY_TEAM, SeasonMode.DRIVER_CAREER)
_SANDBOX_MODES = (SeasonMode.GRAND_PRIX, SeasonMode.LEAGUE)
_MADRID = 42
_IMOLA = 27
_REVERSE = (39, 40, 41)


class CalendarPresetTest(unittest.TestCase):
    def test_2025_and_2026_presets(self):
        c25 = official_calendar(2025)
        c26 = official_calendar(2026)
        self.assertEqual(len(c25), 24, "2025 preset should have 24 rounds")
        self.assertEqual(len(c26), 24, "2026 preset should have 24 rounds")
        self.assertEqual(c25[0].track_id, 0, "2025 round 1 should be Melbourne")
        self.assertEqual(c25[-1].track_id, 14, "2025 round 24 should be Abu Dhabi (last race)")
        self.assertEqual(c25[6].track_id, 27, "2025 round 7 should be Imola")
        self.assertEqual(c26[15].track_id, 42, "2026 round 16 should be Madrid")
        self.assertNotIn(27, [r.track_id for r in c26], "2026 preset should not have Imola (27)")
        self.assertEqual([r.round_number for r in c25], list(range(1, 25)),
                         "2025 rounds should be numbered 1-24")

    def test_unknown_format_rejected(self):
        with self.assertRaises(ValueError):
            official_calendar(2024)


class CalendarFromTrackIdsTest(unittest.TestCase):
    def test_numbers_from_one_and_preserves_order_and_duplicates(self):
        rounds = calendar_from_track_ids([5, 11, 5])
        self.assertEqual([(r.round_number, r.track_id) for r in rounds],
                         [(1, 5), (2, 11), (3, 5)],
                         "should number 1..N in order, keeping duplicates")

    def test_empty(self):
        self.assertEqual(calendar_from_track_ids([]), ())


class SelectableTracksTest(unittest.TestCase):
    def test_madrid_gated_by_format(self):
        self.assertNotIn(_MADRID, selectable_tracks(2025), "Madrid is 2026-only")
        self.assertIn(_MADRID, selectable_tracks(2026), "Madrid is available in 2026")

    def test_imola_and_reverse_layouts_present_both_formats(self):
        for fmt in (2025, 2026):
            with self.subTest(fmt=fmt):
                pool = selectable_tracks(fmt)
                self.assertIn(_IMOLA, pool, "Imola stays selectable in the sandbox")
                for rid in _REVERSE:
                    self.assertIn(rid, pool, f"reverse layout {rid} should be in the pool")

    def test_sizes(self):
        self.assertEqual(len(selectable_tracks(2025)), len(TRACK_NAMES) - 1,
                         "2025 pool = every known track except Madrid")
        self.assertEqual(len(selectable_tracks(2026)), len(TRACK_NAMES),
                         "2026 pool = every known track")

    def test_sorted_by_name(self):
        pool = selectable_tracks(2026)
        self.assertEqual(list(pool), sorted(pool, key=track_name),
                         "pool should be ordered by track name")

    def test_unknown_format_rejected(self):
        with self.assertRaises(ValueError):
            selectable_tracks(2024)


class CalendarRulesTest(unittest.TestCase):
    def test_career_modes_are_preset_subsets(self):
        for mode in _CAREER_MODES:
            for fmt in (2025, 2026):
                with self.subTest(mode=mode, fmt=fmt):
                    r = calendar_rules(mode, fmt)
                    self.assertIs(r.style, CalendarStyle.PRESET_SUBSET)
                    self.assertEqual(r.allowed_lengths, (10, 16, 24))
                    self.assertEqual(r.min_rounds, 10)
                    self.assertEqual(r.max_rounds, 24)
                    self.assertFalse(r.reorderable)
                    self.assertFalse(r.allow_duplicates)
                    self.assertEqual(r.pool, tuple(x.track_id for x in official_calendar(fmt)),
                                     "career pool is the official calendar, in order")

    def test_grand_prix_is_capped_sandbox(self):
        r = calendar_rules(SeasonMode.GRAND_PRIX, 2025)
        self.assertIs(r.style, CalendarStyle.SANDBOX)
        self.assertIsNone(r.allowed_lengths)
        self.assertEqual(r.min_rounds, 1)
        self.assertEqual(r.max_rounds, 28)
        self.assertTrue(r.reorderable)
        self.assertTrue(r.allow_duplicates)
        self.assertEqual(r.pool, selectable_tracks(2025))

    def test_league_is_open_ended_sandbox(self):
        r = calendar_rules(SeasonMode.LEAGUE, 2026)
        self.assertIs(r.style, CalendarStyle.SANDBOX)
        self.assertIsNone(r.max_rounds, "League has no confirmed cap")
        self.assertTrue(r.allow_duplicates)
        self.assertEqual(r.pool, selectable_tracks(2026))

    def test_unknown_format_rejected(self):
        for mode in (*_CAREER_MODES, *_SANDBOX_MODES):
            with self.subTest(mode=mode):
                with self.assertRaises(ValueError):
                    calendar_rules(mode, 2024)


if __name__ == "__main__":
    unittest.main()
