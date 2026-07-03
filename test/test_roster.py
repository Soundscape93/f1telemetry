from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from f1telemetry.src.analysis.standings import league_standings_for_rounds
from f1telemetry.src.domain.models import Classification, ClassificationEntry, SessionResult
from f1telemetry.src.domain.roster import (
    LeagueMember,
    LeagueRoster,
    league_display_name,
    load_roster,
    load_roster_csv,
    merge_rosters,
    roster_from_rounds,
    save_roster,
)
from f1telemetry.src.domain.season import RoundResults
from f1telemetry.src.protocol.enums import Formula, ResultReason, ResultStatus, SessionType, Weather


def _reason():
    return getattr(ResultReason, "INVALID", None) or getattr(ResultReason, "NONE", 0)


def _entry(name, number, position, points):
    return ClassificationEntry(
        vehicle_index=position - 1,
        position=position,
        driver_name=name,
        team_id=0,
        race_number=number,
        is_player=False,
        grid_position=position,
        points=points,
        num_laps=5,
        num_pit_stops=1,
        best_lap_time_ms=70000,
        total_race_time_s=300.0,
        penalties_time_s=0.0,
        num_penalties=0,
        result_status=ResultStatus.FINISHED,
        result_reason=_reason(),
        tyre_stints=(),
    )


def _race(uid, results):
    return SessionResult(
        session_uid=uid,
        season_link_id=0,
        weekend_link_id=0,
        session_link_id=0,
        game_format=2025,
        track_id=0,
        session_type=SessionType.RACE,
        formula=Formula.F1_MODERN,
        weather=Weather.CLEAR,
        total_laps=5,
        game_mode=7,
        player_vehicle_index=0,
        classification=Classification(entries=tuple(results)),
    )


class LoadRosterTest(unittest.TestCase):
    """Test loading and saving a league roster from JSON."""

    def _write(self, obj):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        Path(path).write_text(json.dumps(obj), encoding="utf-8")
        self.addCleanup(os.unlink, path)
        return path

    def test_load_members(self):
        path = self._write(
            {
                "members": [
                    {
                        "name": "Kevin",
                        "race_number": 50,
                        "online_names": ["soundscape93", "kevin123"],
                    },
                    {"name": "Sam", "race_number": 7},
                ]
            }
        )
        roster = load_roster(path)
        self.assertEqual([m.name for m in roster.members], ["Kevin", "Sam"])
        self.assertEqual(roster.members[0].online_names, ("soundscape93", "kevin123"))
        self.assertEqual(roster.members[1].online_names, ())

    def test_save_roster_round_trips(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        self.addCleanup(os.unlink, path)

        roster = LeagueRoster(
            members=(LeagueMember("Kevin", 50, ("soundscape93", "kevin123")),)
        )
        save_roster(path, roster)

        self.assertEqual(load_roster(path), roster)

    def test_duplicate_number_rejected(self):
        path = self._write(
            {"members": [{"name": "A", "race_number": 1}, {"name": "B", "race_number": 1}]}
        )
        with self.assertRaises(ValueError):
            load_roster(path)

    def test_malformed_member_rejected(self):
        path = self._write({"members": [{"name": "NoNumber"}]})
        with self.assertRaises(ValueError):
            load_roster(path)

    def test_blank_name_rejected(self):
        path = self._write({"members": [{"name": " ", "race_number": 44}]})
        with self.assertRaises(ValueError):
            load_roster(path)


class CsvRosterTest(unittest.TestCase):
    """Test CSV import as a source for canonical roster JSON."""

    def _write_csv(self, text):
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        Path(path).write_text(text, encoding="utf-8")
        self.addCleanup(os.unlink, path)
        return path

    def test_loads_csv_with_aliases_and_extra_columns(self):
        path = self._write_csv(
            "Name,Race Number,Online Names,Notes\n"
            "Kevin,50,soundscape93;kevin123,admin\n"
            "Sam,7,,\n"
        )

        roster = load_roster_csv(path)

        self.assertEqual([m.name for m in roster.members], ["Kevin", "Sam"])
        self.assertEqual(roster.members[0].race_number, 50)
        self.assertEqual(roster.members[0].online_names, ("soundscape93", "kevin123"))
        self.assertEqual(roster.members[1].online_names, ())

    def test_csv_header_tolerates_underscores_and_case(self):
        path = self._write_csv("NAME,RACE_NUMBER,ONLINE_NAMES\nKevin,50,soundscape93\n")

        roster = load_roster_csv(path)

        self.assertEqual(roster.members[0], LeagueMember("Kevin", 50, ("soundscape93",)))

    def test_csv_requires_unique_numbers(self):
        path = self._write_csv("name,race_number\nA,1\nB,1\n")
        with self.assertRaises(ValueError):
            load_roster_csv(path)

    def test_csv_requires_name_and_number_headers(self):
        path = self._write_csv("name\nA\n")
        with self.assertRaises(ValueError):
            load_roster_csv(path)

    def test_csv_rejects_blank_name(self):
        path = self._write_csv("name,race_number\n ,50\n")
        with self.assertRaises(ValueError):
            load_roster_csv(path)


class SeedRosterTest(unittest.TestCase):
    """Test seeding a roster from captured classifications."""

    def test_seeds_from_round_classifications(self):
        race = _race(
            1,
            [
                _entry("Player", 50, 1, 25),
                _entry("SammySpeed", 7, 2, 18),
            ],
        )

        roster = roster_from_rounds([RoundResults(1, 0, (race,))])

        self.assertEqual(
            [(m.name, m.race_number, m.online_names) for m in roster.members],
            [("SammySpeed", 7, ("SammySpeed",)), ("Driver 50", 50, ())],
        )

    def test_merge_keeps_primary_names_and_adds_aliases(self):
        primary = LeagueRoster((LeagueMember("Kevin", 50, ("soundscape93",)),))
        fallback = LeagueRoster(
            (
                LeagueMember("Kev", 50, ("kevin123",)),
                LeagueMember("Sam", 7, ()),
            )
        )

        merged = merge_rosters(primary, fallback)

        self.assertEqual(
            [(m.name, m.race_number, m.online_names) for m in merged.members],
            [("Sam", 7, ()), ("Kevin", 50, ("soundscape93", "kevin123"))],
        )


class ResolveTest(unittest.TestCase):
    """Test that a classification entry can resolve to a canonical roster name."""

    def setUp(self):
        self.roster = LeagueRoster(
            members=(
                LeagueMember("Kevin", 50, ("soundscape93", "kevin123")),
                LeagueMember("Sam", 7, ("SammySpeed",)),
            )
        )

    def test_matches_by_online_name(self):
        self.assertEqual(self.roster.member_of(_entry("soundscape93", 50, 1, 25)), "Kevin")

    def test_falls_back_to_number(self):
        self.assertEqual(self.roster.member_of(_entry("RandomGuy", 7, 3, 15)), "Sam")

    def test_unmatched_returns_shown_name(self):
        self.assertEqual(self.roster.member_of(_entry("Stranger", 99, 5, 10)), "Stranger")

    def test_online_name_beats_number(self):
        self.assertEqual(self.roster.member_of(_entry("soundscape93", 7, 1, 25)), "Kevin")

    def test_member_of_is_still_canonical_identity(self):
        self.assertEqual(self.roster.member_of(_entry("Player", 50, 1, 25)), "Kevin")

    def test_member_key_uses_resolved_member_number(self):
        # matched by online name though the entry's own number differs -> the member's number
        self.assertEqual(self.roster.member_key(_entry("soundscape93", 7, 1, 25)), 50)

    def test_member_key_falls_back_to_entry_number_when_unmatched(self):
        self.assertEqual(self.roster.member_key(_entry("Player", 88, 5, 10)), 88)

    def test_display_prefers_public_online_name(self):
        self.assertEqual(
            league_display_name(_entry("soundscape93", 50, 1, 25), self.roster),
            "soundscape93",
        )

    def test_display_falls_back_to_roster_for_generic_player(self):
        self.assertEqual(
            league_display_name(_entry("Player", 50, 1, 25), self.roster),
            "soundscape93",
        )

    def test_display_falls_back_to_roster_for_blank_name(self):
        self.assertEqual(
            league_display_name(_entry(" ", 7, 1, 25), self.roster),
            "SammySpeed",
        )


class LeagueStandingsTest(unittest.TestCase):
    def test_resolves_drifting_identities_and_displays_public_names(self):
        roster = LeagueRoster(
            members=(
                LeagueMember("Kevin", 50, ("soundscape93", "kevin123")),
                LeagueMember("Sam", 7, ("SammySpeed",)),
            )
        )
        race1 = _race(
            1,
            [
                _entry("soundscape93", 50, 1, 25),
                _entry("SammySpeed", 7, 2, 18),
            ],
        )
        race2 = _race(
            2,
            [
                _entry("kevin123", 50, 1, 25),
                _entry("rando", 7, 2, 18),
            ],
        )
        rounds = [RoundResults(1, 0, (race1,)), RoundResults(2, 4, (race2,))]

        table = league_standings_for_rounds(rounds, roster)

        self.assertEqual(
            [(row.position, row.driver_name, row.points) for row in table],
            [(1, "kevin123", 50), (2, "rando", 36)],
        )

    def test_league_standings_display_falls_back_for_generic_player(self):
        roster = LeagueRoster(members=(LeagueMember("Kevin", 50, ("soundscape93",)),))
        race = _race(1, [_entry("Player", 50, 1, 25)])
        rounds = [RoundResults(1, 0, (race,))]

        table = league_standings_for_rounds(rounds, roster)

        self.assertEqual(
            [(row.position, row.driver_name, row.points) for row in table],
            [(1, "soundscape93", 25)],
        )

    def test_unknown_players_do_not_collide_by_shown_name(self):
        # two roster-unknown humans both shown as "Player": number-keyed, so two distinct rows
        roster = LeagueRoster()
        race = _race(1, [_entry("Player", 88, 1, 25), _entry("Player", 42, 2, 18)])
        rounds = [RoundResults(1, 0, (race,))]

        table = league_standings_for_rounds(rounds, roster)

        self.assertEqual(len(table), 2, "distinct numbers must not merge into one row")
        self.assertEqual(
            sorted((row.race_number, row.points) for row in table),
            [(42, 18), (88, 25)],
        )


if __name__ == "__main__":
    unittest.main()
