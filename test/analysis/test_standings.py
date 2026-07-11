from __future__ import annotations

import os
import tempfile
import unittest

from f1telemetry.src.analysis.standings import (
    by_race_number,
    compute_constructor_standings,
    compute_standings,
    standings_for_rounds,
)
from f1telemetry.src.domain.calendars import official_calendar
from f1telemetry.src.domain.models import Classification, ClassificationEntry, SessionResult
from f1telemetry.src.domain.season import RoundResults, SeasonMode
from f1telemetry.src.protocol.enums import Formula, ResultReason, ResultStatus, SessionType, Weather
from f1telemetry.src.storage.sessions import SessionStore
from f1telemetry.src.storage.seasons import SeasonStore


def _reason():
    return getattr(ResultReason, "INVALID", None) or getattr(ResultReason, "NONE", 0)


def _entry(name, number, position, points):
    return ClassificationEntry(
        vehicle_index=position-1, position=position, driver_name=name, team_id=0,
        race_number=number, nationality_id=0, is_player=False, grid_position=position, points=points,
        num_laps=5, num_pit_stops=1, best_lap_time_ms=70000, best_lap_num=3, total_race_time_s=300.0,
        penalties_time_s=0.0, num_penalties=0, result_status=ResultStatus.FINISHED,
        result_reason=_reason(), tyre_stints=())


def make_session(uid, stype, results):
    """results: list of (name, number, position, points) tuples."""
    entries = tuple(_entry(*r) for r in results)
    return SessionResult(
        session_uid=uid, season_link_id=0, weekend_link_id=0, session_link_id=0,
        game_format=2025, track_id=0, session_type=stype, formula=Formula.F1_MODERN,
        weather=Weather.CLEAR, total_laps=5, game_mode=28, player_vehicle_index=0,
        classification=Classification(entries=entries))


class ComputeStandingsTest(unittest.TestCase):
    def test_sums_points_and_ignores_quali(self):
        race1 = make_session(1, SessionType.RACE, [("Alice", 1, 1, 25), ("Bob", 2, 2, 18)])
        race2 = make_session(2, SessionType.RACE, [("Alice", 1, 1, 25), ("Bob", 2, 2, 18)])
        quali = make_session(3, SessionType.QUALIFYING_3, [("Bob", 1, 1, 0), ("Alice", 7, 2, 0)])

        table = compute_standings([race1, race2, quali])
        self.assertEqual([(r.position, r.driver_name, r.points) for r in table],
                         [(1, "Alice", 50), (2, "Bob", 36)], "Standings should sum points from races and ignore quali")
        # quali was include but contributed nothing
        self.assertEqual(table[0].points, 50, "Alice should have 50 points")
        self.assertEqual(table[1].points, 36, "Bob should have 36 points")

    def test_ignores_points_on_non_race_sessions(self):
        # A non-race final classification can carry non-zero points: the game leaves m_points
        # holding the most recent race's points (it doesn't zero the field for non-scoring
        # sessions). Those must never reach championship standings - only race-type sessions score.
        race = make_session(1, SessionType.RACE, [("Alice", 1, 1, 25), ("Bob", 2, 2, 18)])
        practice = make_session(2, SessionType.PRACTICE_1, [("Alice", 1, 1, 25), ("Bob", 2, 2, 18)])
        shootout = make_session(3, SessionType.SPRINT_SHOOTOUT_1, [("Alice", 1, 1, 25), ("Bob", 2, 2, 18)])

        table = compute_standings([race, practice, shootout])
        self.assertEqual([(r.driver_name, r.points) for r in table], [("Alice", 25), ("Bob", 18)],
                         "Only the race session's points should count; practice/shootout carry none")

    def test_constructor_ignores_points_on_non_race_sessions(self):
        race = make_session(1, SessionType.RACE, [("Alice", 1, 1, 25), ("Bob", 2, 2, 18)])
        practice = make_session(2, SessionType.PRACTICE_1, [("Alice", 1, 1, 25), ("Bob", 2, 2, 18)])

        table = compute_constructor_standings([race, practice])
        # _entry puts every driver on team_id 0, so the single team's total is the race points only.
        self.assertEqual([(r.team_id, r.points) for r in table], [(0, 43)],
                         "Constructor total should count the race session only, not practice")

    def test_breaks_ties_by_name_deterministically(self):
        race1 = make_session(1, SessionType.RACE, [("Amy", 3, 1, 25), ("Zoe", 2, 2, 18)])
        race2 = make_session(2, SessionType.RACE, [("Zoe", 2, 1, 25), ("Amy", 3, 2, 18)])
        table = compute_standings([race1, race2])
        self.assertEqual([r.driver_name for r in table], ["Amy", "Zoe"],
                        "Standings should break ties by driver name if points are equal")
        self.assertEqual({r.points for r in table}, {43}, "Both drivers should have 43 points")

    def test_name_key_splits_drifting_names_but_member_key_merges(self):
        race1 = make_session(1, SessionType.RACE, [("Kevin", 50, 1, 25)])
        race2 = make_session(2, SessionType.RACE, [("Kev_50", 50, 1, 25)])

        by_name = compute_standings([race1, race2])
        self.assertEqual(len(by_name), 2, "By name key should treat drifting names as separate drivers")
        by_number = compute_standings([race1, race2], key=by_race_number)
        self.assertEqual(len(by_number), 1, "By number key should merge drifting names")
        self.assertEqual(by_number[0].points, 50, "Merged driver should have 50 points")
        self.assertEqual(by_number[0].race_number, 50, "Merged driver should have race number 50")
        self.assertEqual(by_number[0].driver_name, "Kev_50", "Merged driver should have the most recent name")

    def test_standings_for_rounds_flattens(self):
        round1 = make_session(1, SessionType.RACE, [("Alice", 1, 1, 25)])
        round2 = make_session(2, SessionType.RACE, [("Alice", 2, 1, 25)])
        rounds = [
            RoundResults(round_number=1, track_id=0, sessions=(round1,)),
            RoundResults(round_number=2, track_id=1, sessions=(round2,)),
            RoundResults(round_number=3, track_id=2, sessions=()),  # empty round
        ]    
        table = standings_for_rounds(rounds)
        self.assertEqual((table[0].driver_name, table[0].points), ("Alice", 50),
                        "Standings should sum points across rounds")
        

class StandingsFromStoreTest(unittest.TestCase):
    def test_full_path_through_store(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        url = f"sqlite:///{path}"
        try:
            with SeasonStore(url) as seasons, SessionStore(url) as sessions:
                season = seasons.create_season(SeasonMode.LEAGUE, 1, 2025,
                                               rounds=official_calendar(2025))
                sessions.save(make_session(2001, SessionType.RACE,
                                           [("Kevin", 50, 1, 25), ("Sam", 51, 2, 18)]))
                sessions.save(make_session(2002, SessionType.RACE,
                                             [("Kevin", 50, 1, 25), ("Sam", 51, 2, 18)]))
                seasons.assign_session(2001, season.season_id, 1)
                seasons.assign_session(2002, season.season_id, 2)

                rounds = seasons.rounds_with_results(season.season_id, sessions)
                table = standings_for_rounds(rounds, key=by_race_number)

            self.assertEqual([(r.position, r.driver_name, r.race_number, r.points) for r in table],
                             [(1, "Kevin", 50, 50), (2, "Sam", 51, 36)],
                             "Standings should sum points across rounds and sessions")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
    

        