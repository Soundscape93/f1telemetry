from __future__ import annotations

import unittest
from types import SimpleNamespace
 
from f1telemetry.src.protocol.enums import ResultStatus, SessionType
from f1telemetry.src.ui.formatting import (
    format_gap,
    format_lap_time,
    format_race_time,
    is_race,
    non_race_result,
    race_result,
)
 
 
def _entry(position=1, status=ResultStatus.FINISHED, total=0.0, penalties=0, laps=57, best=0):
    return SimpleNamespace(position=position, result_status=status, total_race_time_s=total,
                           penalties_time_s=penalties, num_laps=laps, best_lap_time_ms=best)
 
 
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
 
 
if __name__ == "__main__":
    unittest.main()
