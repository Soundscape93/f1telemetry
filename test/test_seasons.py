from __future__ import annotations

import os
import tempfile
import unittest

from f1telemetry.src.domain.calendars import official_calendar
from f1telemetry.src.domain.models import Classification, ClassificationEntry, SessionResult
from f1telemetry.src.domain.season import SeasonMode, SeasonRound
from f1telemetry.src.protocol.enums import Formula, ResultReason, ResultStatus, SessionType, Weather
from f1telemetry.src.storage.sessions import SessionStore
from f1telemetry.src.storage.seasons import SeasonStore


def _reason():
    return getattr(ResultReason, "INVALID", None) or getattr(ResultReason, "NONE", 0)



def make_session(uid, stype=SessionType.RACE, winner="Rival"):
    entries = (
        ClassificationEntry(
            vehicle_index=1, position=1, driver_name=winner, team_id=0, is_player=False,
            grid_position=1, points=25, num_laps=5, num_pit_stops=1, best_lap_time_ms=67000,
            total_race_time_s=280.0, penalties_time_s=0.0, num_penalties=0,
            result_status=ResultStatus.FINISHED, result_reason=_reason(), tyre_stints=()),       
    )
    return SessionResult(
        session_uid=uid, season_link_id=0, weekend_link_id=0, session_link_id=0,
        game_format=2025, track_id=17, session_type=stype, formula=Formula.F1_MODERN,
        weather=Weather.CLEAR, total_laps=5, game_mode=28, player_vehicle_index=1,
        classification=Classification(entries=entries))


class StoreTestBase(unittest.TestCase):
    def setUp(self) -> None:
        fd, self._path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        url = f"sqlite:///{self._path}"
        self.session_store = SessionStore(url=url)
        self.seasons = SeasonStore(url=url)
        self.sessions = SessionStore(url=url)       # same database

    def tearDown(self) -> None:
        self.session_store.close()
        self.seasons.close()
        self.sessions.close()
        os.unlink(self._path)


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
        self.assertEqual([r.round_number for r in c25], list(range(1, 25)), "2025 rounds should be numbered 1-24")

    def test_unknown_format_rejected(self):
        with self.assertRaises(ValueError):
            official_calendar(2024)


class SeasonCrudTest(StoreTestBase):
    def test_create_get_list(self):
        s = self.seasons.create_season(SeasonMode.LEAGUE, number=1, game_format=2026, 
                                       nickname="Wednesday League",
                                       rounds=official_calendar(2026))
        self.assertIsNotNone(s.season_id, "new season should have an id")
        self.assertEqual(s.mode, SeasonMode.LEAGUE, "season mode should be LEAGUE")
        self.assertEqual(len(s.rounds), 24, "season should have 24 rounds")

        fetched = self.seasons.get_season(s.season_id)
        self.assertEqual(fetched.nickname, "Wednesday League", "fetched season should have correct nickname")
        self.assertEqual(fetched.rounds[15].track_id, 42, "fetched season should have Madrid as round 16")
        self.assertEqual([x.season_id for x in self.seasons.list_seasons()], [s.season_id],
                        "list should return the created season")

    def test_set_calendar_replaces(self):
        s = self.seasons.create_season(SeasonMode.SOLO_CHAMPIONSHIP, 1, 2025)
        self.assertEqual(len(self.seasons.get_season(s.season_id).rounds), 0, "new season should have no rounds")
        self.seasons.set_calendar(s.season_id, (SeasonRound(1, 5), SeasonRound(2, 11)))
        rounds = self.seasons.get_season(s.season_id).rounds
        self.assertEqual([(r.round_number, r.track_id) for r in rounds], [(1, 5), (2, 11)],
                        "calendar should be replaced with new rounds (1,5) and (2,11)")

    def test_delete_cascades(self):
        s = self.seasons.create_season(SeasonMode.MY_TEAM, 1, 2025, rounds=official_calendar(2025))
        self.sessions.save(make_session(900))
        self.seasons.assign_session(900, s.season_id, 1)
        self.seasons.delete_season(s.season_id)
        self.assertIsNone(self.seasons.get_season(s.season_id), "deleted season should not be retrievable")
        self.assertEqual(self.seasons.assignments_for_season(s.season_id), [],
                        "deleted season should have no assignments (cascaded)")


class AssignmentTest(StoreTestBase):
    def setUp(self):
        super().setUp()
        self.season = self.seasons.create_season(SeasonMode.LEAGUE, 1, 2025, 
                                                rounds=official_calendar(2025))
    
    def test_assign_and_query_results(self):
        self.sessions.save(make_session(1001, SessionType.QUALIFYING_3, winner="Pole"))
        self.sessions.save(make_session(1002, SessionType.RACE, winner="Winner A"))
        self.seasons.assign_session(1001, self.season.season_id, 11)        # Austria quali
        self.seasons.assign_session(1002, self.season.season_id, 11)        # Austria race

        rounds = self.seasons.rounds_with_results(self.season.season_id, self.sessions)
        austria = next(r for r in rounds if r.round_number == 11)
        self.assertEqual(len(austria.sessions), 2, "Austria round should have 2 sessions assigned")
        types = {s.session_type for s in austria.sessions}
        self.assertEqual(types, {SessionType.QUALIFYING_3, SessionType.RACE},
                        "Austria round should have Q3 and RACE sessions assigned")
        race = next(s for s in austria.sessions if s.session_type == SessionType.RACE)
        self.assertEqual(race.classification.winner.driver_name, "Winner A",
                        "Austria race should have correct winner in classification")
        # an empty round should come back with no sessions, not missing
        empty = next(r for r in rounds if r.round_number == 1)
        self.assertEqual(empty.sessions, (), "empty round should have no sessions assigned")

    def test_reject_invalid_round_and_unknwon_reason(self):
        self.sessions.save(make_session(1003))
        with self.assertRaises(ValueError):
            self.seasons.assign_session(1003, self.season.season_id, 99)   # no round 99
        with self.assertRaises(KeyError):
            self.seasons.assign_session(1003, 4242, 1)                     # no such season

    def test_reassign_moves_not_duplicates(self):
        self.sessions.save(make_session(1004, SessionType.RACE))
        self.seasons.assign_session(1004, self.season.season_id, 5)
        self.seasons.assign_session(1004, self.season.season_id, 9)        # move to round 9
        pairs = self.seasons.assignments_for_season(self.season.season_id)
        self.assertEqual(pairs, [(9, 1004)], "session should be reassigned to new round, not duplicated")
    
    def test_unassign(self):
        self.sessions.save(make_session(1005))
        self.seasons.assign_session(1005, self.season.season_id, 3)
        self.seasons.unassign_session(1005)
        self.assertEqual(self.seasons.assignments_for_season(self.season.season_id), [],
                         "unassigned session should not appear in assignments")
        
    def test_assignment_survives_session_reingestation(self):
        self.sessions.save(make_session(1006, SessionType.RACE, winner="Before"))
        self.seasons.assign_session(1006, self.season.season_id, 11)

        # reprocess: SessionStore.save replaces the session row for uid 1006
        self.sessions.save(make_session(1006, SessionType.RACE, winner="After"))

        rounds = self.seasons.rounds_with_results(self.season.season_id, self.sessions)
        austria = next(r for r in rounds if r.round_number == 11)
        self.assertEqual(len(austria.sessions), 1, "Austria round should still have 1 session assigned after reingestion")
        self.assertEqual(austria.sessions[0].classification.winner.driver_name, "After",
                         "Austria round should have the reingested session's classification after reingestion")
        

if __name__ == "__main__":
    unittest.main()