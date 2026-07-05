from __future__ import annotations

import unittest
from types import SimpleNamespace
 
from f1telemetry.src.protocol.enums import ResultStatus, SessionType
from f1telemetry.src.protocol.reference import team_display_name
from f1telemetry.src.ui.formatting import (
    format_gap,
    format_grid,
    format_lap_gap,
    format_lap_time,
    format_penalty_badge,
    format_position_change,
    format_race_time,
    is_race,
    non_race_result,
    race_result,
    race_winner_summary,
)


def _entry(position=1, status=ResultStatus.FINISHED, total=0.0, penalties=0, laps=57, best=0,
           num_penalties=0):
    return SimpleNamespace(position=position, result_status=status, total_race_time_s=total,
                           penalties_time_s=penalties, num_laps=laps, best_lap_time_ms=best,
                           num_penalties=num_penalties, driver_name="Driver", team_id=1)
 
 
class FormatTest(unittest.TestCase):
    def test_race_time(self):
        self.assertEqual(format_race_time(5400.0), "1:30:00.000")   # 1h30m
        self.assertEqual(format_race_time(83.456), "1:23.456")
        self.assertEqual(format_race_time(0), "\u2014")
 
    def test_gap(self):
        self.assertEqual(format_gap(5.234), "+5.234")
        self.assertEqual(format_gap(60.5), "+1:00.500")
        self.assertEqual(format_gap(-0.3), "-0.300")
 
    def test_lap_time(self):
        self.assertEqual(format_lap_time(78345), "1:18.345")
        self.assertEqual(format_lap_time(0), "\u2014")
 
 
class RaceResultTest(unittest.TestCase):
    def setUp(self):
        self.winner = _entry(position=1, total=5400.0, laps=57)
 
    def test_winner_shows_absolute_time(self):
        self.assertEqual(race_result(self.winner, self.winner), "1:30:00.000")
 
    def test_lead_lap_shows_gap(self):
        p2 = _entry(position=2, total=5405.234, laps=57)
        self.assertEqual(race_result(p2, self.winner), "+5.234")
 
    def test_gap_includes_penalties(self):
        # on-track 2s behind, +5s penalty -> classified 7s behind
        p2 = _entry(position=2, total=5402.0, penalties=5, laps=57)
        self.assertEqual(race_result(p2, self.winner), "+7.000")
 
    def test_lapped_cars(self):
        self.assertEqual(race_result(_entry(position=12, laps=56), self.winner), "+1 lap")
        self.assertEqual(race_result(_entry(position=13, laps=55), self.winner), "+2 laps")
 
    def test_non_finishers_show_status(self):
        self.assertEqual(race_result(_entry(position=19, status=ResultStatus.DID_NOT_FINISH), self.winner), "DNF")
        self.assertEqual(race_result(_entry(position=20, status=ResultStatus.RETIRED), self.winner), "DNF")
        self.assertEqual(race_result(_entry(status=ResultStatus.DISQUALIFIED), self.winner), "DSQ")
        self.assertEqual(race_result(_entry(status=ResultStatus.NOT_CLASSIFIED), self.winner), "NC")
 
    def test_status_survives_raw_int(self):
        # safe_enum can hand back a raw int; equality/mapping must still work
        self.assertEqual(race_result(_entry(status=4), self.winner), "DNF")
 
 
class NonRaceResultTest(unittest.TestCase):
    def test_quali_finisher_shows_best_lap(self):
        e = _entry(status=ResultStatus.FINISHED, best=78345)
        self.assertEqual(non_race_result(e, SessionType.QUALIFYING_2), "1:18.345")
 
    def test_quali_non_finisher_shows_status(self):
        e = _entry(status=ResultStatus.DID_NOT_FINISH, best=0)
        self.assertEqual(non_race_result(e, SessionType.QUALIFYING_1), "DNF")
 
    def test_quali_finisher_no_time(self):
        e = _entry(status=ResultStatus.FINISHED, best=0)
        self.assertEqual(non_race_result(e, SessionType.QUALIFYING_3), "\u2014")
 
    def test_practice_never_shows_status(self):
        # a non-finish in practice still shows its lap (or dash), not a status tag
        e = _entry(status=ResultStatus.DID_NOT_FINISH, best=80000)
        self.assertEqual(non_race_result(e, SessionType.PRACTICE_1), "1:20.000")
        blank = _entry(status=ResultStatus.DID_NOT_FINISH, best=0)
        self.assertEqual(non_race_result(blank, SessionType.PRACTICE_1), "\u2014")
 
    def test_is_race(self):
        self.assertTrue(is_race(SessionType.RACE))
        self.assertTrue(is_race(SessionType.RACE_2))
        self.assertFalse(is_race(SessionType.QUALIFYING_1))
        self.assertFalse(is_race(SessionType.PRACTICE_1))


class RaceWinnerSummaryTest(unittest.TestCase):
    def test_race_winner_uses_driver_and_team(self):
        winner = _entry(position=1)
        winner.driver_name = "Charles Leclerc"
        session = SimpleNamespace(
            session_type=SessionType.RACE,
            classification=SimpleNamespace(winner=winner),
        )
        self.assertEqual(race_winner_summary(session), "Charles Leclerc / Ferrari")

    def test_non_race_has_no_winner_summary(self):
        session = SimpleNamespace(
            session_type=SessionType.QUALIFYING_3,
            classification=SimpleNamespace(winner=_entry(position=1)),
        )
        self.assertIsNone(race_winner_summary(session))

    def test_name_of_overrides_shown_name(self):
        # a league caller injects a display resolver; the module itself knows no rosters
        winner = _entry(position=1)
        winner.driver_name = "Player"
        session = SimpleNamespace(
            session_type=SessionType.RACE,
            classification=SimpleNamespace(winner=winner),
        )
        self.assertEqual(
            race_winner_summary(session, name_of=lambda e: "soundscape93"),
            "soundscape93 / Ferrari",
        )
 
 
class PositionChangeTest(unittest.TestCase):
    def test_gain_loss_same(self):
        self.assertEqual(format_position_change(5, 1), ("▲", "gain"))
        self.assertEqual(format_position_change(1, 5), ("▼", "loss"))
        self.assertEqual(format_position_change(3, 3), ("—", "same"))

    def test_unknown_grid_is_neutral(self):
        # a pit-lane / unknown start (grid 0) is a neutral dash, not a huge gain
        self.assertEqual(format_position_change(0, 8), ("—", "none"))


class GridTest(unittest.TestCase):
    def test_grid_and_pit_start(self):
        self.assertEqual(format_grid(7), "7")
        self.assertEqual(format_grid(0), "—")


class LapGapTest(unittest.TestCase):
    def setUp(self):
        self.winner = _entry(position=1, best=78000)

    def test_leader_has_no_gap(self):
        self.assertEqual(format_lap_gap(self.winner, self.winner), "—")

    def test_gap_to_fastest_lap(self):
        p2 = _entry(position=2, best=78345)
        self.assertEqual(format_lap_gap(p2, self.winner), "+0.345")

    def test_no_time_is_dash(self):
        self.assertEqual(format_lap_gap(_entry(position=8, best=0), self.winner), "—")


class PenaltyBadgeTest(unittest.TestCase):
    def test_no_penalty_is_none(self):
        self.assertIsNone(format_penalty_badge(0, 0))

    def test_count_and_time(self):
        self.assertEqual(format_penalty_badge(1, 3), "⚑ ×1 (+3s)")

    def test_count_only(self):
        # a warning-style penalty with no added time still shows the flag and count
        self.assertEqual(format_penalty_badge(2, 0), "⚑ ×2")


class TeamDisplayNameTest(unittest.TestCase):
    def test_year_suffix_stripped(self):
        self.assertEqual(team_display_name(477), "Ferrari")   # "Ferrari '26"
        self.assertEqual(team_display_name(485), "Audi")      # "Audi '26"

    def test_base_team_unchanged(self):
        self.assertEqual(team_display_name(1), "Ferrari")


if __name__ == "__main__":
    unittest.main()
