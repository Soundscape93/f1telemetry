from __future__ import annotations

import unittest
from types import SimpleNamespace

from datetime import datetime, timedelta, timezone
 
from f1telemetry.src.protocol.enums import ResultStatus, SessionType, Weather
from f1telemetry.src.protocol.reference import team_display_name
from f1telemetry.src.ui.formatting import (
    compound_for_lap,
    estimate_points,
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
    recorded_label,
    session_fastest_lap,
    weather_label,
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


class CompoundForLapTest(unittest.TestCase):
    def _stint(self, visual, end_lap):
        return SimpleNamespace(visual_compound=visual, end_lap=end_lap)

    def test_picks_the_stint_covering_the_lap(self):
        stints = (self._stint(16, 5), self._stint(18, 255))   # soft to lap 5, then hard (current)
        self.assertEqual(compound_for_lap(stints, 3), 16)     # lap 3 -> softs
        self.assertEqual(compound_for_lap(stints, 5), 16)     # boundary lap belongs to that stint
        self.assertEqual(compound_for_lap(stints, 40), 18)    # later lap -> hards

    def test_no_lap_or_no_stints_is_none(self):
        self.assertIsNone(compound_for_lap((), 4))
        self.assertIsNone(compound_for_lap((self._stint(16, 5),), 0))

    def test_lap_past_all_end_laps_falls_back_to_last(self):
        stints = (self._stint(16, 3), self._stint(17, 6))     # neither reaches lap 9
        self.assertEqual(compound_for_lap(stints, 9), 17)


class TeamDisplayNameTest(unittest.TestCase):
    def test_year_suffix_stripped(self):
        self.assertEqual(team_display_name(477), "Ferrari")   # "Ferrari '26"
        self.assertEqual(team_display_name(485), "Audi")      # "Audi '26"

    def test_base_team_unchanged(self):
        self.assertEqual(team_display_name(1), "Ferrari")


class EstimatePointsTest(unittest.TestCase):
    """The display-only points estimate for reconstructed race tables."""

    def test_grand_prix_scoring(self):
        self.assertEqual(estimate_points(1, ResultStatus.FINISHED), 25)
        self.assertEqual(estimate_points(2, ResultStatus.FINISHED), 18)
        self.assertEqual(estimate_points(3, ResultStatus.FINISHED), 15)
        self.assertEqual(estimate_points(10, ResultStatus.FINISHED), 1)

    def test_grand_prix_out_of_points_is_zero(self):
        self.assertEqual(estimate_points(11, ResultStatus.FINISHED), 0)
        self.assertEqual(estimate_points(20, ResultStatus.FINISHED), 0)

    def test_sprint_scoring(self):
        self.assertEqual(estimate_points(1, ResultStatus.FINISHED, is_sprint_race=True), 8)
        self.assertEqual(estimate_points(8, ResultStatus.FINISHED, is_sprint_race=True), 1)
        self.assertEqual(estimate_points(9, ResultStatus.FINISHED, is_sprint_race=True), 0)

    def test_non_finishers_return_none(self):
        for status in (ResultStatus.DID_NOT_FINISH, ResultStatus.RETIRED,
                       ResultStatus.DISQUALIFIED, ResultStatus.NOT_CLASSIFIED,
                       ResultStatus.INACTIVE):
            self.assertIsNone(estimate_points(1, status))
            self.assertIsNone(estimate_points(1, status, is_sprint_race=True))


class SessionFastestLapTest(unittest.TestCase):
    """The overview's fastest-lap line - read from the classification, never from LapStore."""

    def _session(self, *times, names=None):
        names = names or [f"D{i}" for i in range(len(times))]
        entries = [SimpleNamespace(driver_name=name, best_lap_time_ms=ms)
                   for name, ms in zip(names, times)]
        return SimpleNamespace(classification=SimpleNamespace(entries=entries))

    def test_picks_the_lowest_non_zero_time(self):
        s = self._session(68000, 67500, 69000, names=["Alonso", "Norris", "Sainz"])
        self.assertEqual(session_fastest_lap(s), "Norris — 1:07.500")

    def test_zero_is_no_time_set_not_the_fastest_lap(self):
        """A plain min would report a driver who never set a lap as fastest of the session."""
        s = self._session(0, 68000, names=["DidNotRun", "Norris"])
        self.assertEqual(session_fastest_lap(s), "Norris — 1:08.000")

    def test_all_zero_is_none(self):
        self.assertIsNone(session_fastest_lap(self._session(0, 0)))

    def test_no_classification_is_none(self):
        self.assertIsNone(session_fastest_lap(SimpleNamespace(classification=None)))

    def test_no_entries_is_none(self):
        self.assertIsNone(session_fastest_lap(self._session()))

    def test_tie_goes_to_the_earlier_entry(self):
        """Entries arrive in finishing order, so a tie resolves to the higher-placed driver."""
        s = self._session(67500, 67500, names=["Leader", "Chaser"])
        self.assertEqual(session_fastest_lap(s), "Leader — 1:07.500")

    def test_name_of_is_injectable(self):
        s = self._session(67500, names=["Player"])
        self.assertEqual(session_fastest_lap(s, name_of=lambda e: "Kevin"), "Kevin — 1:07.500")


class WeatherLabelTest(unittest.TestCase):
    def test_known_members(self):
        self.assertEqual(weather_label(Weather.CLEAR), "Clear")
        self.assertEqual(weather_label(Weather.LIGHT_RAIN), "Light rain")

    def test_unknown_raw_int_still_renders(self):
        """Enums are stored as raw ints (invariant #9); a newer value must not crash a label."""
        self.assertEqual(weather_label(99), "99")


class RecordedLabelTest(unittest.TestCase):
    def test_none_is_an_em_dash(self):
        self.assertEqual(recorded_label(None), "—")

    def test_naive_value_is_shown_as_is(self):
        self.assertEqual(recorded_label(datetime(2026, 8, 9, 21, 2)), "2026-08-09 21:02")

    def test_aware_value_converts_to_local(self):
        """Stored as UTC; a tz-aware value must be shown in the viewer's local time."""
        utc = datetime(2026, 8, 9, 21, 2, tzinfo=timezone.utc)
        self.assertEqual(recorded_label(utc), utc.astimezone().strftime("%Y-%m-%d %H:%M"))


if __name__ == "__main__":
    unittest.main()
