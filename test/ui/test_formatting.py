from __future__ import annotations

import unittest
from types import SimpleNamespace

from datetime import datetime, timedelta, timezone

from f1telemetry.src.domain.models import SessionOvertake
from f1telemetry.src.pipeline import RestoreOutcome, RestoreProblem
from f1telemetry.src.protocol.enums import ResultStatus, SessionType, Weather
from f1telemetry.src.protocol.reference import team_display_name, track_name
from f1telemetry.src.ui.formatting import (
    NOT_CAPTURED,
    capture_choice_label,
    compound_for_lap,
    deleted_capture_label,
    deleted_session_cells,
    estimate_points,
    format_gap,
    format_grid,
    format_grid_penalty,
    format_lap_gap,
    format_lap_time,
    format_penalty_badge,
    format_position_change,
    format_race_time,
    format_size,
    is_race,
    lap_gap_label,
    laps_completed_label,
    non_race_result,
    overtakes_label,
    overtakes_tooltip,
    player_best_lap_ms,
    player_points_label,
    race_result,
    race_winner_summary,
    recorded_label,
    restore_message,
    slot_label,
    session_best_lap_ms,
    session_context_label,
    session_fastest_lap,
    session_leader,
    time_of_day_label,
    track_air_temp_label,
    weather_label,
)
from f1telemetry.test.domain.test_seasons import make_session


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


class GridPenaltyBadgeTest(unittest.TestCase):
    def test_no_places_is_none(self):
        self.assertIsNone(format_grid_penalty(0))

    def test_places_read_as_a_grid_drop(self):
        # 972807263... (league Q1): two 5-place penalties on one car read as the ten places it
        # actually starts back, which the classification's own count never says.
        self.assertEqual(format_grid_penalty(10), "⚑ 10-place grid")

    def test_a_single_penalty_reads_the_same_way(self):
        self.assertEqual(format_grid_penalty(5), "⚑ 5-place grid")


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

class SessionLeaderTest(unittest.TestCase):
    """Every session has a 'winner' - a practice or quali session's is whoever ended up P1."""

    def _session(self, name="Leclerc"):
        leader = _entry(position=1)
        leader.driver_name = name
        return SimpleNamespace(classification=SimpleNamespace(winner=leader))

    def test_returns_the_leader(self):
        self.assertEqual(session_leader(self._session("Leclerc")), "Leclerc")

    def test_no_classification_is_none(self):
        self.assertIsNone(session_leader(SimpleNamespace(classification=None)))

    def test_empty_classification_is_none(self):
        empty = SimpleNamespace(classification=SimpleNamespace(winner=None))
        self.assertIsNone(session_leader(empty))

    def test_name_of_is_injectable(self):
        self.assertEqual(session_leader(self._session("Player"), name_of=lambda e: "Kevin"),
                         "Kevin")

    def test_works_on_a_real_non_race_classification(self):
        """Against the real dataclass rather than a stand-in.

        ``Classification.winner`` is ``entries[0]``, and nothing in ``session_leader`` branches
        on session type - which is the whole point of the helper. This is also the test that
        would have caught the stand-in drifting from the real object's interface.
        """
        quali = make_session(1, SessionType.QUALIFYING_3, winner="Pole")
        self.assertEqual(session_leader(quali), "Pole")

def _player(position=1, points=25, num_laps=29, team_id=1, num_penalties=0, penalties=0,
            best=0, status=ResultStatus.FINISHED):
        return SimpleNamespace(position=position, points=points, num_laps=num_laps, team_id=team_id,
                           is_player=True, is_ai=False, num_penalties=num_penalties,
                           penalties_time_s=penalties, best_lap_time_ms=best,
                           result_status=status, driver_name="Me")


def _rival(best=0, is_player=False):
    return SimpleNamespace(best_lap_time_ms=best, is_player=is_player, is_ai=True,
                           driver_name="Rival")


def _sess(session_type=SessionType.RACE, entries=(), total_laps=29, game_mode=78,
          reconstructed=False, player_vehicle_index=0,
          track_temperature=None, air_temperature=None, time_of_day=None):
    classification = SimpleNamespace(entries=tuple(entries), is_reconstructed=reconstructed)
    return SimpleNamespace(session_type=session_type, total_laps=total_laps,
                           game_mode=game_mode, classification=classification,
                           player_vehicle_index=player_vehicle_index,
                           track_temperature=track_temperature,
                           air_temperature=air_temperature, time_of_day=time_of_day)


def _pass(overtaking, overtaken, lap=1):
    """One stored OVTK row, already filtered to two racing cars."""
    return SessionOvertake(overtaking_vehicle_index=overtaking,
                           overtaken_vehicle_index=overtaken, lap_number=lap)


class OvertakesLabelTest(unittest.TestCase):
    """The details grid's overtakes cell, against the shapes the real captures produced.

    Player index 0 throughout, and every fixture is a shape measured in this database - see
    TELEMETRY_NOTES -> "Event packets" and the branch-3 note in DECISIONS -> UI.
    """

    def test_a_race_counts_the_player_s_own_passes_both_ways(self):
        """14435457337826486933 (a league race): 13 made, 29 suffered - the worst race here, and
        the one that decided the passes are a count and not a list."""
        rows = [_pass(0, 12)] * 13 + [_pass(12, 0)] * 29
        self.assertEqual(overtakes_label(_sess(), rows), "+13 / \u221229")

    def test_other_cars_passes_are_not_counted(self):
        """93% of OVTK events are AI-on-AI; only the player's own belong in this cell."""
        rows = [_pass(0, 5), _pass(7, 9), _pass(9, 7), _pass(4, 0)]
        self.assertEqual(overtakes_label(_sess(), rows), "+1 / \u22121")

    def test_a_lights_to_flag_win_reads_as_a_real_zero(self):
        """Six of the 20 races here: grid P1 to P1, 146-562 field-wide passes, none the player's.
        The rows being present is what makes this a fact rather than a gap."""
        rows = [_pass(7, 9), _pass(9, 7), _pass(3, 4)]
        self.assertEqual(overtakes_label(_sess(player_vehicle_index=21), rows), "+0 / \u22120")

    def test_no_rows_at_all_is_not_captured(self):
        """A session ingested before PIPELINE_VERSION 5 holds none, and a race that ran holds 52 to
        562 - so an empty read is the store speaking, not the race. The only three races here with
        no rows are reconstructed fragments, where "not captured" is the literal truth."""
        self.assertIsNone(overtakes_label(_sess(), ()))

    def test_practice_and_qualifying_are_an_em_dash(self):
        """16.7% of filtered passes there have the two cars on different laps - traffic, not
        racing - and the 892 practice / 994 qualifying "passes" are almost all out-lap traffic."""
        rows = [_pass(0, 5), _pass(5, 0)]
        self.assertEqual(overtakes_label(_sess(SessionType.PRACTICE_1), rows), "\u2014")
        self.assertEqual(overtakes_label(_sess(SessionType.QUALIFYING_3), rows), "\u2014")

    def test_a_sprint_race_counts_like_a_race(self):
        """The Sprint Race shares session_type 15 with the Grand Prix (core invariant #5)."""
        self.assertEqual(overtakes_label(_sess(SessionType.RACE), [_pass(0, 5)]), "+1 / \u22120")

    def test_the_minus_is_a_minus_sign_not_a_hyphen(self):
        """It sets beside the "+" at the same weight and width; a hyphen does not."""
        self.assertIn("\u2212", overtakes_label(_sess(), [_pass(3, 0)]))
        self.assertNotIn("-", overtakes_label(_sess(), [_pass(3, 0)]))

    def test_the_tooltip_spells_out_what_was_counted(self):
        rows = [_pass(0, 5), _pass(0, 6), _pass(7, 0)]
        tooltip = overtakes_tooltip(_sess(), rows)
        self.assertIn("2 passes made, 1 suffered", tooltip)
        self.assertIn("pit lane", tooltip)

    def test_there_is_no_tooltip_where_there_is_no_number(self):
        self.assertEqual(overtakes_tooltip(_sess(), ()), "")
        self.assertEqual(overtakes_tooltip(_sess(SessionType.PRACTICE_1), [_pass(0, 5)]), "")


class TrackAirTempLabelTest(unittest.TestCase):
    def test_both_temperatures_in_the_label_s_order(self):
        self.assertEqual(track_air_temp_label(_sess(track_temperature=31, air_temperature=21)),
                         "31 °C / 21 °C")

    def test_a_row_ingested_before_the_columns_existed_is_not_captured(self):
        self.assertIsNone(track_air_temp_label(_sess()))

    def test_a_negative_temperature_is_a_real_reading(self):
        """The wire field is a signed int8; nothing here may treat cold as missing."""
        self.assertEqual(track_air_temp_label(_sess(track_temperature=-2, air_temperature=-5)),
                         "-2 °C / -5 °C")


class TimeOfDayLabelTest(unittest.TestCase):
    def test_minutes_since_midnight_read_as_a_clock(self):
        self.assertEqual(time_of_day_label(_sess(time_of_day=900)), "15:00")
        self.assertEqual(time_of_day_label(_sess(time_of_day=983)), "16:23")
        self.assertEqual(time_of_day_label(_sess(time_of_day=1439)), "23:59")

    def test_midnight_is_a_value_and_not_an_absence(self):
        """0 is a legitimate time_of_day and the reason the test is `is None`, not falsiness."""
        self.assertEqual(time_of_day_label(_sess(time_of_day=0)), "00:00")

    def test_a_row_ingested_before_the_column_existed_is_not_captured(self):
        self.assertIsNone(time_of_day_label(_sess()))


class NotCapturedTest(unittest.TestCase):
    def test_the_phrase_is_shared_by_all_three_cells(self):
        """One string, so the three cells cannot word the same absence differently."""
        self.assertEqual(NOT_CAPTURED, "Not captured")


class PlayerPointsLabelTest(unittest.TestCase):
    """Points are gated to races because the stored value is wrong everywhere else."""

    def test_race_shows_the_stored_points(self):
        self.assertEqual(player_points_label(_sess(entries=[_player(points=25)])), "25")

    def test_practice_is_an_em_dash_even_though_points_are_stored(self):
        """Real captures carry points 25 on a Practice 1 row - a carried-over championship
        figure. Rendering it would state a number that is simply untrue."""
        session = _sess(SessionType.PRACTICE_1, entries=[_player(points=25)])
        self.assertEqual(player_points_label(session), "\u2014")

    def test_qualifying_is_an_em_dash(self):
        session = _sess(SessionType.QUALIFYING_1, entries=[_player(points=8)])
        self.assertEqual(player_points_label(session), "\u2014")

    def test_reconstructed_race_shows_the_estimate_like_the_table_does(self):
        session = _sess(entries=[_player(position=1, points=0)], reconstructed=True)
        self.assertEqual(player_points_label(session), "~25")

    def test_reconstructed_sprint_uses_the_sprint_table(self):
        session = _sess(entries=[_player(position=1, points=0)], reconstructed=True)
        self.assertEqual(player_points_label(session, is_sprint_race=True), "~8")

    def test_no_player_entry_is_an_em_dash(self):
        self.assertEqual(player_points_label(_sess(entries=[_rival()])), "\u2014")


class LapsCompletedLabelTest(unittest.TestCase):
    def test_race_shows_completed_over_total(self):
        self.assertEqual(laps_completed_label(_sess(entries=[_player(num_laps=29)])), "29 / 29")

    def test_race_count_comes_from_the_classification_not_the_stored_rows(self):
        """A recording that started late stores fewer laps than were driven (27 vs 29 in real
        captures); the classification is the truth of what happened."""
        session = _sess(entries=[_player(num_laps=29)])
        self.assertEqual(laps_completed_label(session, stored_laps=27), "29 / 29")

    def test_practice_shows_a_bare_count_because_total_laps_is_meaningless(self):
        """Real practice rows carry total_laps 1 against 7 laps actually run."""
        session = _sess(SessionType.PRACTICE_1, entries=[_player(num_laps=7)], total_laps=1)
        self.assertEqual(laps_completed_label(session), "7")

    def test_falls_back_to_the_stored_count_when_the_game_reported_none(self):
        session = _sess(entries=[_player(num_laps=0)])
        self.assertEqual(laps_completed_label(session, stored_laps=4), "4 / 29")


class LapGapLabelTest(unittest.TestCase):
    def test_gap_to_my_own_best(self):
        self.assertEqual(lap_gap_label(82249, 81046), "+1.203")

    def test_the_reference_lap_itself_is_an_em_dash(self):
        self.assertEqual(lap_gap_label(81046, 81046), "\u2014")

    def test_an_untimed_lap_is_an_em_dash(self):
        self.assertEqual(lap_gap_label(None, 81046), "\u2014")
        self.assertEqual(lap_gap_label(0, 81046), "\u2014")

    def test_no_reference_is_an_em_dash(self):
        self.assertEqual(lap_gap_label(82249, None), "\u2014")


class PlayerBestLapTest(unittest.TestCase):
    def _laps(self, *times):
        return [SimpleNamespace(lap_time_ms=t) for t in times]

    def test_picks_the_lowest(self):
        self.assertEqual(player_best_lap_ms(self._laps(82249, 81046, 81458)), 81046)

    def test_ignores_untimed_laps(self):
        self.assertEqual(player_best_lap_ms(self._laps(None, 0, 81046)), 81046)

    def test_no_timed_laps_is_none(self):
        self.assertIsNone(player_best_lap_ms(self._laps(None, 0)))
        self.assertIsNone(player_best_lap_ms([]))


class SessionBestLapMsTest(unittest.TestCase):
    def test_lowest_non_zero_across_the_field(self):
        session = _sess(entries=[_player(best=81500), _rival(best=81046)])
        self.assertEqual(session_best_lap_ms(session), 81046)

    def test_zero_is_no_time_set(self):
        session = _sess(entries=[_rival(best=0), _player(best=81500)])
        self.assertEqual(session_best_lap_ms(session), 81500)

    def test_nobody_set_a_time_is_none(self):
        self.assertIsNone(session_best_lap_ms(_sess(entries=[_rival(best=0)])))

    def test_no_classification_is_none(self):
        self.assertIsNone(session_best_lap_ms(SimpleNamespace(classification=None)))


class SessionContextLabelTest(unittest.TestCase):
    def test_team_mode_and_slot(self):
        session = _sess(entries=[_player(team_id=1)], game_mode=78)
        label = session_context_label(session, "Race")
        self.assertIn(team_display_name(1), label)
        self.assertIn("Driver Career '26", label)
        self.assertTrue(label.endswith("Race"))

    def test_no_player_entry_still_renders(self):
        session = _sess(entries=[_rival()], game_mode=7)
        self.assertEqual(session_context_label(session, "Qualifying 3"),
                         "Online Custom  ·  Qualifying 3")

def _tomb(uid=123, session_type=SessionType.RACE, track_id=2,
            recorded_at=datetime(2026, 8, 9, 21, 2), deleted_at=datetime(2026, 8, 10, 9, 14)):
    """One ``storage.sessions.DeletedSession``, shaped - every field but the uid is nullable."""
    return SimpleNamespace(session_uid=uid, session_type=session_type, track_id=track_id,
                            recorded_at=recorded_at, deleted_at=deleted_at)


def _capture(file_name="20260823_140747.f1cap.zst", recorded_by=None, file_size=46_544_961,
                ingested_at=datetime(2026, 8, 24, 17, 55), content_hash="abc"):
    return SimpleNamespace(file_name=file_name, recorded_by=recorded_by, file_size=file_size,
                           ingested_at=ingested_at, content_hash=content_hash)


class FormatSizeTest(unittest.TestCase):
    def test_megabytes_are_whole(self):
        self.assertEqual(format_size(46_544_961), "44 MB")

    def test_gigabytes_get_a_decimal(self):
        self.assertEqual(format_size(3 * 1024 ** 3), "3.0 GB")

    def test_zero_is_not_special_cased(self):
        self.assertEqual(format_size(0), "0 MB")


class DeletedSessionCellsTest(unittest.TestCase):
    def test_the_four_descriptive_columns(self):
        session, track, recorded, deleted = deleted_session_cells(_tomb())
        self.assertEqual(session, "Race")
        self.assertEqual(track, track_name(2))
        self.assertEqual(recorded, "2026-08-09 21:02")
        self.assertEqual(deleted, "2026-08-10 09:14")

    def test_a_tombstone_that_knows_nothing_renders_em_dashes(self):
        """A rollback of a session whose row was already gone can carry only the uid."""
        cells = deleted_session_cells(_tomb(session_type=None, track_id=None,
                                            recorded_at=None, deleted_at=None))
        self.assertEqual(cells, ("\u2014", "\u2014", "\u2014", "\u2014"))

    def test_a_session_type_newer_than_the_enum_still_renders(self):
        """Enums are stored as raw ints (core invariant #9) - a new value must not crash a row."""
        self.assertEqual(deleted_session_cells(_tomb(session_type=250))[0], "250")

    def test_a_deleted_sprint_reads_as_race(self):
        """The stated limitation, pinned: the tombstone has no weekend_structure to tell it from a
        Grand Prix (core invariant #5), so this must stay true until the tombstone widens."""
        self.assertEqual(deleted_session_cells(_tomb(session_type=SessionType.RACE))[0], "Race")

    def test_a_sprint_weekends_grand_prix_is_recoverable_from_the_type_alone(self):
        """RACE_2 needs no weekend context: a second race is the weekend's final one."""
        self.assertEqual(deleted_session_cells(_tomb(session_type=SessionType.RACE_2))[0], "Race")


class DeletedCaptureLabelTest(unittest.TestCase):
    def test_no_capture_row_at_all(self):
        self.assertEqual(deleted_capture_label([], []), "not recorded")

    def test_one_findable_capture_is_just_its_name(self):
        self.assertEqual(deleted_capture_label(["a.zst"], ["a.zst"]), "a.zst")

    def test_known_but_unfindable_names_every_one_of_them(self):
        """It must match what the refusal names, so no single row is chosen here."""
        self.assertEqual(deleted_capture_label(["a.zst", "b.zst"], []),
                         "a.zst, b.zst  (archive not found)")

    def test_several_findable_counts_the_rest(self):
        self.assertEqual(deleted_capture_label(["a.zst", "b.zst"], ["b.zst", "a.zst"]),
                         "b.zst  (+1 more)")


class CaptureChoiceLabelTest(unittest.TestCase):
    def test_names_everything_that_tells_two_copies_apart(self):
        label = capture_choice_label(_capture(recorded_by="Ana"))
        self.assertIn("20260823_140747.f1cap.zst", label)
        self.assertIn("recorded by Ana", label)
        self.assertIn("44 MB", label)
        self.assertIn("read 2026-08-24 17:55", label)

    def test_an_unset_recorder_says_unknown_rather_than_claiming_you(self):
        self.assertIn("recorder unknown", capture_choice_label(_capture(recorded_by=None)))

    def test_an_unstamped_ingest_is_an_em_dash(self):
        self.assertIn("read \u2014", capture_choice_label(_capture(ingested_at=None)))


class RestoreMessageTest(unittest.TestCase):
    def _refusal(self, reason, **kwargs):
        return RestoreOutcome(restored=False, session_uid=1, reason=reason, **kwargs)

    def test_success_names_the_capture(self):
        message = restore_message(RestoreOutcome(restored=True, session_uid=1,
                                                 capture_name="a.zst"))
        self.assertIn("a.zst", message)
        self.assertIn("laps", message)

    def test_a_missing_archive_sends_you_to_find_moved_captures(self):
        message = restore_message(self._refusal(RestoreProblem.ARCHIVE_MISSING,
                                                capture_name="a.zst"))
        self.assertIn("a.zst", message)
        self.assertIn("Find moved captures", message)
        self.assertNotIn("Forget", message)

    def test_no_capture_row_sends_you_to_forget_and_never_to_the_file(self):
        """The pair that must not read alike: one file can be found again, the other never existed."""
        message = restore_message(self._refusal(RestoreProblem.NO_CAPTURE_ROW))
        self.assertIn("Forget", message)
        self.assertNotIn("Find moved captures", message)

    def test_every_problem_says_something_of_its_own(self):
        messages = {reason: restore_message(self._refusal(reason)) for reason in RestoreProblem}
        self.assertEqual(len(set(messages.values())), len(RestoreProblem))
        for reason, message in messages.items():
            with self.subTest(reason=reason):
                self.assertTrue(message.endswith(".") and len(message) > 20)

    def test_an_ingest_failure_carries_its_error(self):
        message = restore_message(self._refusal(RestoreProblem.INGEST_FAILED,
                                                capture_name="a.zst", error="zstd frame corrupt"))
        self.assertIn("zstd frame corrupt", message)
        self.assertIn("still listed as deleted", message)

    def test_a_refusal_with_no_capture_name_still_reads(self):
        self.assertIn("the recording",
                      restore_message(self._refusal(RestoreProblem.INGEST_FAILED)))


class SlotLabelTest(unittest.TestCase):
    def test_a_non_race_type_is_its_prettified_name(self):
        self.assertEqual(slot_label(SessionType.QUALIFYING_3), "Qualifying 3")
        self.assertEqual(slot_label(SessionType.SPRINT_SHOOTOUT_1), "Sprint Shootout 1")

    def test_the_sprint_flag_wins(self):
        self.assertEqual(slot_label(SessionType.RACE, is_sprint_race=True), "Sprint Race")

    def test_a_grand_prix_reads_race_whatever_number_the_game_put_on_it(self):
        """A sprint weekend reports the Sprint as RACE (15) and the Grand Prix as RACE_2 (16), so
        the raw enum name labelled every sprint weekend's Grand Prix "Race 2"."""
        self.assertEqual(slot_label(SessionType.RACE), "Race")
        self.assertEqual(slot_label(SessionType.RACE_2), "Race")
        self.assertEqual(slot_label(SessionType.RACE_3), "Race")

    def test_a_raw_int_race_type_reads_race_too(self):
        """Enums are stored as raw ints (invariant #9), and a tombstone hands one straight over."""
        self.assertEqual(slot_label(16), "Race")

    def test_a_type_newer_than_the_enum_renders_as_its_number(self):
        self.assertEqual(slot_label(250), "250")


if __name__ == "__main__":
    unittest.main()
