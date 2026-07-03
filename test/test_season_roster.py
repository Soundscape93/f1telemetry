"""Tests for the per-season roster file convention (ui/season_roster.py).

The module is Qt-free, so it's unit-testable without a display: it owns where roster files live
and the load/seed/persist split. The capture side is duck-typed (rounds → sessions →
classification → entries), so lightweight SimpleNamespace stand-ins are enough; seasons are real
``Season`` objects because the previous-season lookup reads mode/number/season_id.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from f1telemetry.src.domain.roster import LeagueMember, LeagueRoster, load_roster, save_roster
from f1telemetry.src.domain.season import Season, SeasonMode
from f1telemetry.src.ui.season_roster import SeasonRosterFiles


def _entry(name, number):
    return SimpleNamespace(driver_name=name, race_number=number)


def _round(*entries):
    session = SimpleNamespace(classification=SimpleNamespace(entries=tuple(entries)))
    return SimpleNamespace(sessions=(session,))


def _season(season_id, number, mode=SeasonMode.LEAGUE):
    return Season(mode=mode, number=number, game_format=2025, season_id=season_id)


class SeasonRosterFilesTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.files = SeasonRosterFiles(root=self._dir.name)

    def test_roster_for_seeds_in_memory_without_writing(self):
        season = _season(1, 1)
        rounds = [_round(_entry("SammySpeed", 7), _entry("Player", 50))]

        roster = self.files.roster_for(season, rounds, lambda: [season])

        self.assertEqual(
            [(m.name, m.race_number) for m in roster.members],
            [("SammySpeed", 7), ("Driver 50", 50)],
        )
        self.assertFalse(self.files.has_roster(1), "viewing must not write a roster file")

    def test_create_from_captures_writes_editable_file(self):
        season = _season(1, 1)
        rounds = [_round(_entry("SammySpeed", 7))]

        roster = self.files.create_from_captures(season, rounds, lambda: [season])

        self.assertTrue(self.files.has_roster(1))
        self.assertEqual(load_roster(self.files.path_for(1)), roster)

    def test_roster_for_loads_saved_file_and_ignores_captures(self):
        season = _season(1, 1)
        saved = LeagueRoster((LeagueMember("Kevin", 50, ("soundscape93",)),))
        save_roster(self.files.path_for(1), saved)

        # captures name a different driver; the saved file must win, unchanged.
        roster = self.files.roster_for(season, [_round(_entry("Stranger", 99))], lambda: [season])

        self.assertEqual(roster, saved)

    def test_seed_merges_previous_league_season(self):
        previous, current = _season(1, 1), _season(2, 2)
        save_roster(
            self.files.path_for(previous.season_id),
            LeagueRoster((LeagueMember("Kevin", 50, ("soundscape93",)),)),
        )
        rounds = [_round(_entry("kevin123", 50), _entry("Sam", 7))]

        roster = self.files.seed(current, rounds, lambda: [previous, current])

        self.assertEqual(
            [(m.name, m.race_number, m.online_names) for m in roster.members],
            [("Sam", 7, ("Sam",)), ("Kevin", 50, ("soundscape93", "kevin123"))],
        )

    def test_previous_roster_ignores_non_league_and_later_seasons(self):
        current = _season(3, 2)
        non_league = _season(1, 1, mode=SeasonMode.MY_TEAM)
        later = _season(2, 5)
        for s in (non_league, later):
            save_roster(self.files.path_for(s.season_id), LeagueRoster((LeagueMember("Ghost", 1, ()),)))

        roster = self.files.seed(current, [_round(_entry("Sam", 7))], lambda: [non_league, later, current])

        self.assertEqual([(m.name, m.race_number) for m in roster.members], [("Sam", 7)])

    def test_import_csv_writes_canonical_json(self):
        csv_path = Path(self._dir.name) / "in.csv"
        csv_path.write_text(
            "name,race_number,online_names\nKevin,50,soundscape93\n", encoding="utf-8"
        )

        roster = self.files.import_csv(1, csv_path)

        self.assertTrue(self.files.has_roster(1))
        self.assertEqual(load_roster(self.files.path_for(1)), roster)
        self.assertEqual(roster.members[0], LeagueMember("Kevin", 50, ("soundscape93",)))


if __name__ == "__main__":
    unittest.main()
