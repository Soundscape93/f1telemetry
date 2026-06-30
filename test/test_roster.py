from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from f1telemetry.src.analysis.standings import league_standings_for_rounds
from f1telemetry.src.domain.models import Classification, ClassificationEntry, SessionResult
from f1telemetry.src.domain.roster import LeagueMember, LeagueRoster, load_roster
from f1telemetry.src.domain.season import RoundResults
from f1telemetry.src.protocol.enums import Formula, ResultReason, ResultStatus, SessionType, Weather


def _reason():
    return getattr(ResultReason, "INVALID", None) or getattr(ResultReason, "NONE", 0)


def _entry(name, number, position, points):
    return ClassificationEntry(
        vehicle_index=position - 1, position=position, driver_name=name, team_id=0,
        race_number=number, is_player=False, grid_position=position, points=points,
        num_laps=5, num_pit_stops=1, best_lap_time_ms=70000, total_race_time_s=300.0,
        penalties_time_s=0.0, num_penalties=0, result_status=ResultStatus.FINISHED,
        result_reason=_reason(), tyre_stints=())


def _race(uid, results):
    return SessionResult(
        session_uid=uid, season_link_id=0, weekend_link_id=0, session_link_id=0,
        game_format=2025, track_id=0, session_type=SessionType.RACE, formula=Formula.F1_MODERN,
        weather=Weather.CLEAR, total_laps=5, game_mode=7, player_vehicle_index=0,
        classification=Classification(entries=results))


class LoadRosterTest(unittest.TestCase):
    """Test loading a league roster from JSON."""
    def _write(self, obj):
        """Write a JSON object to a temporary file and return the path."""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        Path(path).write_text(json.dumps(obj), encoding="utf-8")
        self.addCleanup(os.unlink, path)
        return path
    

    def test_load_members(self):
        """Test that a roster can be loaded from a JSON file with members and optional online names."""
        path = self._write({"members": [
            {"name": "Kevin", "race_number": 50, "online_names": ["soundscape93", "kevin123"]},
            {"name": "Sam", "race_number": 7}]})
        roster = load_roster(path)
        self.assertEqual([m.name for m in roster.members], ["Kevin", "Sam"], "Roster names should match")
        self.assertEqual(roster.members[0].online_names, ("soundscape93", "kevin123"), "Online names should match")
        self.assertEqual(roster.members[1].online_names, (), "Optional online names should default to empty tuple if not provided")

    def test_duplicate_number_rejected(self):
        """Test that loading a roster with duplicate race numbers raises a ValueError."""
        path = self._write({"members": [
            {"name": "A", "race_number": 1}, {"name": "B", "race_number": 1}]})
        with self.assertRaises(ValueError):
            load_roster(path)

    def test_malformed_member_rejected(self):
        """Test that loading a roster with a malformed member (missing name) raises a ValueError."""
        path = self._write({"members": [
            {"name": "NoNumber"}]})
        with self.assertRaises(ValueError):
            load_roster(path)

    
class ResolveTest(unittest.TestCase):
    """Test that a classification entry can be resolved to a canonical name using a roster."""
    def setUp(self):
        """Set up a roster with two members for testing."""
        self.roster = LeagueRoster(members=(
            LeagueMember("Kevin", 50, ("soundscape93", "kevin123")),
            LeagueMember("Sam", 7, ("SammySpeed",)),
        ))

    def test_matches_by_online_name(self):
        """Test that a classification entry can be resolved to a canonical name using an online name."""
        self.assertEqual(self.roster.member_of(_entry("soundscape93", 50, 1, 25)), "Kevin", "Should match by online name")

    def test_falls_back_to_number(self):
        """Test that a classification entry can be resolved to a canonical name using a race number if the online name does not match."""
        self.assertEqual(self.roster.member_of(_entry("RandomGuy", 7, 3, 15)), "Sam", "Should match by race number if online name not found/there")

    def test_unmatched_returns_shown_name(self):
        """"Test that a classification entry that does not match any member returns the shown name."""
        self.assertEqual(self.roster.member_of(_entry("Stranger", 99, 5, 10)), "Stranger", "Should return shown name if no match found")

    def test_online_name_beats_number(self):
        """Test that name resolves to online name even if the number matches a different member."""
        self.assertEqual(self.roster.member_of(_entry("soundscape93", 7, 1, 25)), "Kevin")

    
class LeagueStandingsTest(unittest.TestCase):
    def test_resolves_drivting_identities_and_labels_canonically(self):
        """Test that league standings resolve driver identities and labels canonically using a roster."""
        roster = LeagueRoster(members=(
            LeagueMember("Kevin", 50, ("soundscape93", "kevin123")),
            LeagueMember("Sam", 7, ("SammySpeed",)),
        ))
        # rae1 matche by online name, race2 same humans, names drifted -> matches by number
        race1 = _race(1, [_entry("soundscape93", 50, 1, 25), _entry("SammySpeed", 7, 2, 18)])
        race2 = _race(2, [_entry("kevin123", 50, 1, 25), _entry("rando", 7, 2, 18)])
        rounds = [RoundResults(1, 0, (race1,)), RoundResults(2, 4, (race2,))]

        table = league_standings_for_rounds(rounds, roster)
        self.assertEqual(
            [(row.position, row.driver_name, row.points) for row in table],
            [(1,"Kevin", 50), (2,"Sam", 36)], "Standings should resolve to canonical names and sum points across rounds")
        

if __name__ == "__main__":
    unittest.main()