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
    is_ai_entry,
    league_display_name,
    load_roster,
    load_roster_csv,
    looks_like_ai,
    merge_rosters,
    roster_from_rounds,
    save_roster,
)
from f1telemetry.src.domain.season import RoundResults
from f1telemetry.src.protocol.enums import Formula, ResultReason, ResultStatus, SessionType, Weather


def _reason():
    return getattr(ResultReason, "INVALID", None) or getattr(ResultReason, "NONE", 0)


def _entry(name, number, position, points, is_ai=False, vehicle_index=None):
    return ClassificationEntry(
        vehicle_index=position - 1 if vehicle_index is None else vehicle_index,
        position=position,
        driver_name=name,
        team_id=0,
        race_number=number,
        nationality_id=0,
        is_player=False,
        grid_position=position,
        points=points,
        num_laps=5,
        num_pit_stops=1,
        best_lap_time_ms=70000,
        best_lap_num=0,
        total_race_time_s=300.0,
        penalties_time_s=0.0,
        num_penalties=0,
        result_status=ResultStatus.FINISHED,
        result_reason=_reason(),
        tyre_stints=(),
        is_ai=is_ai,
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

    def test_duplicate_number_allowed_when_both_have_online_names(self):
        path = self._write(
            {
                "members": [
                    {"name": "Ann", "race_number": 11, "online_names": ["annie"]},
                    {"name": "Bo", "race_number": 11, "online_names": ["bobo"]},
                ]
            }
        )
        roster = load_roster(path)
        self.assertEqual([m.name for m in roster.members], ["Ann", "Bo"])

    def test_duplicate_member_name_rejected(self):
        path = self._write(
            {"members": [{"name": "Kevin", "race_number": 1},
                         {"name": "kevin", "race_number": 2}]}
        )
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

    def test_seeded_names_stay_unique_when_a_member_changes_number(self):
        # canonical names are the grouping key, so the seed must not emit two "roli"s
        rounds = [
            RoundResults(1, 0, (_race(1, [_entry("roli", 24, 1, 25)]),)),
            RoundResults(2, 4, (_race(2, [_entry("roli", 25, 1, 25)]),)),
        ]

        roster = roster_from_rounds(rounds)

        self.assertEqual(
            [(m.name, m.race_number) for m in roster.members],
            [("roli", 24), ("roli (25)", 25)],
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

    def test_member_key_is_tagged_with_the_resolved_member(self):
        """matched by online name trough the entry's own number differs -> the member's key."""
        self.assertEqual(self.roster.member_key(_entry("soundscape93", 7, 1, 25)), ("member", "Kevin"))

    def test_member_key_falls_back_to_entry_number_when_unmatched(self):
        self.assertEqual(self.roster.member_key(_entry("Player", 88, 5, 10)), ("driver", 88))

    def test_member_key_tags_ai_separately_from_a_member_on_the_same_number(self):
        """The collision that broke driver standings: an AI on a member's number."""
        self.assertNotEqual(
            self.roster.member_key(_entry("Sergio Perez", 50, 9, 2, is_ai=True)),
            self.roster.member_key(_entry("soundscape93", 50, 1, 25)),
        )

    def test_alias_match_is_case_insensitive(self):
        self.assertEqual(self.roster.member_of(_entry("SOUNDSCAPE93", 99, 1, 25)), "Kevin")

    def test_generic_shown_name_never_matches_an_alias(self):
        """a roster listing "Player" as an alias must not swallow every privacy-restricted human."""
        roster = LeagueRoster(members=(LeagueMember("Kevin", 50, ("Player",)),))
        self.assertEqual(roster.member_of(_entry("Player", 88, 1, 25)), "Player")

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


class AiIdentityTest(unittest.TestCase):
    """AI cars must never resolve to a league member who shares their race number."""

    def setUp(self):
        # Fabian runs 11, and so does the AI Sergio Perez - the real league collision.
        self.roster = LeagueRoster(
            members=(LeagueMember("Fabian", 11, ("Fabibyte",)),)
        )

    def test_flagged_ai_does_not_match_by_race_number(self):
        self.assertIsNone(self.roster.member_for(_entry("Sergio Perez", 11, 9, 2, is_ai=True)))

    def test_legacy_row_without_flag_falls_back_to_the_name_heuristic(self):
        # stored before is_ai was captured: is_ai=False, but the name is an AI driver's
        entry = _entry("Sergio Perez", 11, 9, 2)
        self.assertFalse(is_ai_entry(entry))
        self.assertTrue(looks_like_ai(entry))
        self.assertIsNone(self.roster.member_for(entry))

    def test_human_still_matches_by_race_number(self):
        self.assertEqual(self.roster.member_of(_entry("Player", 11, 1, 25)), "Fabian")

    def test_explicit_alias_beats_the_ai_name_heuristic(self):
        # a human whose gamertag happens to be an AI's name: the roster said so, so it wins
        roster = LeagueRoster(members=(LeagueMember("Fabian", 11, ("Sergio Perez",)),))
        self.assertEqual(roster.member_of(_entry("Sergio Perez", 11, 1, 25)), "Fabian")

    def test_flagged_ai_is_not_rescued_by_an_alias(self):
        # ...but the game's own flag is authoritative: an AI car is never a member
        roster = LeagueRoster(members=(LeagueMember("Fabian", 11, ("Sergio Perez",)),))
        self.assertIsNone(roster.member_for(_entry("Sergio Perez", 11, 9, 2, is_ai=True)))

    def test_session_keys_keep_ai_and_member_apart(self):
        entries = [_entry("Fabibyte", 11, 2, 18), _entry("Sergio Perez", 11, 9, 2, is_ai=True)]
        keys = self.roster.session_keys(entries)
        self.assertEqual(len(set(keys)), 2, "an AI and a member on one number are two rows")
        self.assertEqual(keys[0], ("member", "Fabian"))

    def test_seeded_roster_skips_ai_cars(self):
        race = _race(1, [_entry("Fabibyte", 11, 1, 25),
                         _entry("Sergio Perez", 11, 2, 18, is_ai=True)])

        roster = roster_from_rounds([RoundResults(1, 0, (race,))])

        self.assertEqual(
            [(m.race_number, m.online_names) for m in roster.members],
            [(11, ("Fabibyte",))],
            "an AI name must never become a league member's alias",
        )


class SessionKeyUniquenessTest(unittest.TestCase):
    """Two cars in one classification are two drivers - never one merged standings row."""

    def test_two_hidden_humans_on_one_number_do_not_merge(self):
        roster = LeagueRoster()
        entries = [_entry("Player", 88, 1, 25, vehicle_index=3),
                   _entry("Player", 88, 2, 18, vehicle_index=9)]

        keys = roster.session_keys(entries)

        self.assertEqual(len(set(keys)), 2, "indistinguishable cars split rather than merge")

    def test_two_humans_on_one_number_resolve_by_alias(self):
        roster = LeagueRoster(
            members=(LeagueMember("Ann", 11, ("annie",)), LeagueMember("Bo", 11, ("bobo",)))
        )
        keys = roster.session_keys([_entry("annie", 11, 1, 25), _entry("bobo", 11, 2, 18)])

        self.assertEqual(list(keys), [("member", "Ann"), ("member", "Bo")])

    def test_shared_number_without_an_alias_is_rejected_at_load(self):
        roster = LeagueRoster(members=(LeagueMember("Ann", 11, ("annie",)),))
        entries = [_entry("annie", 11, 1, 25), _entry("Player", 11, 2, 18)]

        keys = roster.session_keys(entries)

        self.assertEqual(keys[0], ("member", "Ann"))
        self.assertNotEqual(keys[1], keys[0], "the alias match claims the member, not the number")


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

    def test_ai_sharing_a_members_race_number_does_not_join_their_row(self):
        """Regression: Fabibyte (#11) and the AI Sergio Perez (#11) were summed into one row,
        which the last-seen name then relabelled 'Sergio Perez' — see docs/DECISIONS.md."""
        roster = LeagueRoster(members=(LeagueMember("Fabian", 11, ("Fabibyte",)),))
        race = _race(
            1,
            [
                _entry("patrickstein12", 2, 1, 25),
                _entry("Fabibyte", 11, 2, 18),
                _entry("Sergio Perez", 11, 9, 2, is_ai=True),
            ],
        )

        table = league_standings_for_rounds([RoundResults(1, 0, (race,))], roster)

        self.assertEqual(
            [(row.position, row.driver_name, row.points) for row in table],
            [(1, "patrickstein12", 25), (2, "Fabibyte", 18), (3, "Sergio Perez", 2)],
            "the AI keeps its own row; the member keeps their own points and name",
        )

    def test_ai_points_still_accumulate_across_rounds(self):
        # full-grid championship view: AI drivers stay in the table and stay grouped
        roster = LeagueRoster(members=(LeagueMember("Fabian", 11, ("Fabibyte",)),))
        rounds = [
            RoundResults(1, 0, (_race(1, [_entry("Sergio Perez", 11, 1, 25, is_ai=True)]),)),
            RoundResults(2, 4, (_race(2, [_entry("Sergio Perez", 11, 1, 25, is_ai=True)]),)),
        ]

        table = league_standings_for_rounds(rounds, roster)

        self.assertEqual([(r.driver_name, r.points) for r in table], [("Sergio Perez", 50)])


class RosterlessLeagueTest(unittest.TestCase):
    """A league whose members all share public online names needs no roster file at all.

    The roster workflow buys canonical names, aliases and hidden-telemetry handling - it is not
    a prerequisite for standings.
    """

    def _race_with_ai(self, uid):
        return _race(uid, [
            _entry("patrickstein12", 2, 1, 25),
            _entry("Fabibyte", 11, 2, 18),
            _entry("Sergio Perez", 11, 9, 2, is_ai=True),
        ])

    def test_empty_roster_still_produces_standings(self):
        table = league_standings_for_rounds(
            [RoundResults(1, 0, (self._race_with_ai(1),))], LeagueRoster())

        self.assertEqual(
            [(r.driver_name, r.points) for r in table],
            [("patrickstein12", 25), ("Fabibyte", 18), ("Sergio Perez", 2)],
            "no roster file: public online names carry the standings on their own",
        )

    def test_capture_seeded_roster_holds_no_ai_and_still_splits_the_collision(self):
        rounds = [RoundResults(1, 0, (self._race_with_ai(1),))]

        roster = roster_from_rounds(rounds)          # what a rosterless season renders with
        table = league_standings_for_rounds(rounds, roster)

        self.assertEqual([m.race_number for m in roster.members], [2, 11])
        self.assertEqual(
            [(r.driver_name, r.points) for r in table],
            [("patrickstein12", 25), ("Fabibyte", 18), ("Sergio Perez", 2)],
        )

    def test_public_names_group_across_rounds_without_a_roster(self):
        rounds = [
            RoundResults(1, 0, (_race(1, [_entry("Fabibyte", 11, 1, 25)]),)),
            RoundResults(2, 4, (_race(2, [_entry("Fabibyte", 11, 1, 25)]),)),
        ]

        table = league_standings_for_rounds(rounds, LeagueRoster())

        self.assertEqual([(r.driver_name, r.points) for r in table], [("Fabibyte", 50)])


if __name__ == "__main__":
    unittest.main()
