"""A season's standings as its share image - every string the builder decides, without a QApplication.

The fixture is this database's *Mittwoch League* shape rather than a tidy invention: members who
raced with online-name sharing off, so the capture calls them ``Player`` and only the roster names
them, beside an AI field running the real-world race numbers - including an AI Perez on 11, which
is also a member's number. That collision is core invariant #7, and it is why ``driver_standings``
groups a league by roster session keys rather than by race number.
"""
import unittest

from f1telemetry.src.domain.models import Classification, ClassificationEntry, SessionResult
from f1telemetry.src.domain.roster import LeagueMember, LeagueRoster
from f1telemetry.src.domain.season import RoundResults, Season, SeasonMode, SeasonRound
from f1telemetry.src.protocol.enums import (
    Formula,
    ResultReason,
    ResultStatus,
    SessionType,
    Weather,
)
from f1telemetry.src.ui.components.share_document import Align, Notes, Table
from f1telemetry.src.ui.components.standings_share import driver_standings, standings_document
from f1telemetry.src.version import __version__

_MELBOURNE, _SHANGHAI, _SUZUKA = 0, 2, 13
_FERRARI, _RED_BULL = 1, 2
_SWISS, _ITALIAN, _MEXICAN = 79, 41, 52
_QUALIFYING = SessionType.QUALIFYING_3      # a weekend captured no further than qualifying


def _entry(vehicle_index, position, name, *, race_number, points, team_id=_FERRARI,
           nationality_id=_SWISS, is_ai=True):
    return ClassificationEntry(
        vehicle_index=vehicle_index, position=position, driver_name=name, team_id=team_id,
        race_number=race_number, nationality_id=nationality_id, is_player=False,
        grid_position=position, points=points, num_laps=10, num_pit_stops=1,
        best_lap_time_ms=90000, best_lap_num=5, total_race_time_s=1800.0, penalties_time_s=0,
        num_penalties=0, result_status=ResultStatus.FINISHED, result_reason=ResultReason.FINISHED,
        tyre_stints=(), is_ai=is_ai)


def _session(entries, *, session_type=SessionType.RACE, reconstructed=False, uid=1):
    return SessionResult(
        session_uid=uid, season_link_id=1, weekend_link_id=1, session_link_id=1, game_format=2026,
        track_id=_MELBOURNE, session_type=session_type, formula=Formula.F1_MODERN,
        weather=Weather.CLEAR, total_laps=10, game_mode=19, player_vehicle_index=0,
        classification=Classification(entries=tuple(entries), is_reconstructed=reconstructed))


def _round(number, track_id, sessions=()):
    return RoundResults(round_number=number, track_id=track_id, sessions=tuple(sessions))


def _season(nickname="Mittwoch League", number=1, calendar=24):
    return Season(mode=SeasonMode.GRAND_PRIX, number=number, game_format=2026, nickname=nickname,
                  rounds=tuple(SeasonRound(round_number=n, track_id=_MELBOURNE)
                               for n in range(1, calendar + 1)),
                  season_id=1)


# Two members the capture only ever calls "Player", named by their online alias; and an AI Perez on
# 11, the same number as the member on 11. Grouping by number would sum them into one row (#7).
_ROSTER = LeagueRoster(members=(
    LeagueMember(name="Kevin", race_number=50, online_names=("soundscape93",)),
    LeagueMember(name="Fabian", race_number=11, online_names=("Fabibyte",))))


def _grid(kevin, fabian, perez):
    """One classification: the two members on 50 and 11, then the AI Perez who also runs 11."""
    return (_entry(0, 1, "Player", race_number=50, points=kevin, is_ai=False),
            _entry(1, 2, "Player", race_number=11, points=fabian, nationality_id=_ITALIAN,
                   is_ai=False),
            _entry(2, 3, "Sergio Perez", race_number=11, points=perez, team_id=_RED_BULL,
                   nationality_id=_MEXICAN))


_ROUNDS = (
    _round(1, _MELBOURNE, (_session(_grid(25, 18, 15), uid=1),)),
    _round(2, _SHANGHAI, (_session(_grid(18, 25, 12), uid=2),)),
    _round(3, _SUZUKA, (_session(_grid(15, 12, 25), uid=3),)),
) + tuple(_round(n, _MELBOURNE) for n in range(4, 25))


def _document(season=None, rounds=_ROUNDS, season_name="Season 1 (“Mittwoch League”)",
              roster=_ROSTER, **kwargs):
    return standings_document(season or _season(), rounds, season_name, roster, **kwargs)


def _texts(table):
    return [tuple(cell.text for cell in row) for row in table.rows]


class TitleTests(unittest.TestCase):
    """What the image calls itself, and what it saves as."""

    def test_a_round_is_named_with_the_track_it_was_run_at(self):
        """"After round 3" alone makes a reader count down a calendar to place it."""
        self.assertEqual("Season 1 (“Mittwoch League”) — Standings after round 3 (Suzuka)",
                         _document(through=3).title)

    def test_without_a_round_it_is_simply_the_season_s_standings(self):
        self.assertEqual("Season 1 (“Mittwoch League”) — Standings", _document().title)

    def test_a_round_that_is_not_on_the_calendar_is_named_without_a_track(self):
        """Rather than inventing one: a round the season does not have has no track to print."""
        self.assertEqual("Season 1 (“Mittwoch League”) — Standings after round 99",
                         _document(through=99).title)

    def test_the_file_name_leads_with_the_season_and_carries_its_nickname(self):
        self.assertEqual("Season-1_Mittwoch-League_Standings-round-3", _document(through=3).name)

    def test_a_season_without_a_nickname_drops_that_part_rather_than_doubling_the_join(self):
        self.assertEqual("Season-2_Standings-round-3",
                         _document(season=_season(nickname=None, number=2), through=3).name)

    def test_the_whole_season_saves_without_a_round(self):
        self.assertEqual("Season-1_Mittwoch-League_Standings", _document().name)

    def test_the_footer_is_the_app_and_its_version(self):
        self.assertEqual(f"f1telemetry v{__version__}", _document().footer)


class MetaTests(unittest.TestCase):
    """The meta line counts what actually scored, against the whole calendar."""

    def test_it_counts_the_rounds_that_put_points_on_the_board(self):
        self.assertEqual("3 of 24 rounds counted", _document().meta)

    def test_a_slice_counts_only_the_rounds_it_kept(self):
        self.assertEqual("2 of 24 rounds counted", _document(through=2).meta)

    def test_a_round_holding_no_race_does_not_count(self):
        """A weekend captured up to qualifying has a round but no points in it."""
        rounds = (_round(1, _MELBOURNE,
                         (_session(_grid(25, 18, 15), session_type=_QUALIFYING),)),)
        self.assertEqual("0 of 1 rounds counted", _document(rounds=rounds).meta)


class SliceTests(unittest.TestCase):
    """"As of round N" is the rounds up to N, and nothing else changes."""

    def test_a_later_round_s_points_are_not_in_an_earlier_round_s_standings(self):
        """Fabibyte leads after two rounds on a tie broken by name, and loses the lead at Suzuka."""
        self.assertEqual([("1", "Fabibyte", "11", "43"), ("2", "soundscape93", "50", "43"),
                          ("3", "Sergio Perez", "11", "27")],
                         _texts(_document(through=2).blocks[0]))
        self.assertEqual([("1", "soundscape93", "50", "58"), ("2", "Fabibyte", "11", "55"),
                          ("3", "Sergio Perez", "11", "52")],
                         _texts(_document(through=3).blocks[0]))

    def test_the_round_named_is_included_rather_than_stopped_before(self):
        """"After round 1" means round 1 has been run, not that it is still to come."""
        self.assertEqual([("1", "soundscape93", "50", "25"), ("2", "Fabibyte", "11", "18"),
                          ("3", "Sergio Perez", "11", "15")],
                         _texts(_document(through=1).blocks[0]))

    def test_no_round_is_dropped_when_none_is_named(self):
        self.assertEqual(["58", "55", "52"],
                         [row[-1].text for row in _document().blocks[0].rows])


class StandingsRuleTests(unittest.TestCase):
    """Which of the two standings applies, and why a league cannot go by race number."""

    def test_a_league_groups_by_roster_so_an_ai_sharing_a_number_keeps_its_own_row(self):
        """Core invariant #7: the AI field runs the real-world numbers, and Perez is on 11 here."""
        rows = driver_standings(_ROUNDS, _ROSTER)
        self.assertEqual([("Fabibyte", 11, 55), ("Sergio Perez", 11, 52)],
                         [(row.driver_name, row.race_number, row.points) for row in rows
                          if row.race_number == 11])

    def test_without_a_roster_the_captured_names_are_the_identity(self):
        """Which is why both members read "Player" and sum into one row - right for a solo season,
        and exactly what having a roster is for."""
        self.assertEqual([("Player", 113), ("Sergio Perez", 52)],
                         [(row.driver_name, row.points) for row in driver_standings(_ROUNDS)])

    def test_the_document_is_built_from_that_same_rule_rather_than_a_second_one(self):
        rows = driver_standings(_ROUNDS, _ROSTER)
        self.assertEqual([(str(row.position), row.driver_name, str(row.race_number),
                           str(row.points)) for row in rows],
                         _texts(_document().blocks[0]))


class TableShapeTests(unittest.TestCase):
    """The two tables are the season page's own, laid out for a still image."""

    def test_the_driver_table_carries_the_page_s_columns(self):
        drivers = _document().blocks[0]
        self.assertEqual("Drivers", drivers.title)
        self.assertEqual(["POS", "DRIVER", "NO.", "POINTS"], [c.header for c in drivers.columns])

    def test_the_constructor_table_names_teams_the_way_the_page_does(self):
        """``team_display_name``, so "Ferrari '26" reads "Ferrari" here as it does on screen."""
        constructors = _document().blocks[1]
        self.assertEqual("Constructors", constructors.title)
        self.assertEqual(["POS", "TEAM", "POINTS"], [c.header for c in constructors.columns])
        self.assertEqual([("1", "Ferrari", "113"), ("2", "Red Bull Racing", "52")],
                         _texts(constructors))

    def test_numbers_sit_right_and_only_names_may_wrap(self):
        for table in _document().blocks:
            with self.subTest(table=table.title):
                self.assertEqual(Align.RIGHT, table.columns[0].align)
                self.assertEqual(Align.RIGHT, table.columns[-1].align)
                self.assertTrue(table.columns[1].wrap)
                self.assertFalse(table.columns[-1].wrap)

    def test_every_driver_carries_the_flag_the_page_shows_beside_their_name(self):
        self.assertEqual([_SWISS, _ITALIAN, _MEXICAN],
                         [row[1].icon.key for row in _document().blocks[0].rows])

    def test_one_flag_serves_every_driver_of_a_nationality(self):
        self.assertEqual([_SWISS, _ITALIAN, _MEXICAN],
                         [icon.key for icon in _document().icons()])

    def test_the_total_is_the_one_emphasised_cell_in_a_row(self):
        """It is what the table is read for, and a photo needs an anchor the page does not."""
        for row in _document().blocks[0].rows:
            self.assertEqual([False, False, False, True], [cell.strong for cell in row])


class NotCountedTests(unittest.TestCase):
    """A race the standings had to skip is said out loud rather than left as a silence."""

    _REBUILT = _round(2, _SHANGHAI, (_session(_grid(18, 25, 12), reconstructed=True, uid=2),))

    def test_one_skipped_race_is_named_under_the_drivers_table(self):
        rounds = (_ROUNDS[0], self._REBUILT) + _ROUNDS[2:]
        self.assertEqual("One race is missing from these totals: the game sent no final "
                         "classification for it, so it awarded no points.",
                         _document(rounds=rounds).blocks[0].note)

    def test_several_are_counted_in_the_same_sentence(self):
        rebuilt = _round(3, _SUZUKA, (_session(_grid(15, 12, 25), reconstructed=True, uid=3),))
        rounds = (_ROUNDS[0], self._REBUILT, rebuilt) + _ROUNDS[3:]
        self.assertEqual("2 races are missing from these totals: the game sent no final "
                         "classification for them, so they awarded no points.",
                         _document(rounds=rounds).blocks[0].note)

    def test_a_season_that_counted_everything_says_nothing(self):
        self.assertEqual("", _document().blocks[0].note)

    def test_a_skipped_race_is_not_a_counted_round_either(self):
        rounds = (_ROUNDS[0], self._REBUILT) + _ROUNDS[2:]
        self.assertEqual("2 of 24 rounds counted", _document(rounds=rounds).meta)

    def test_a_round_skipped_after_the_one_named_is_not_mentioned(self):
        """The note describes the totals shown, so it is sliced with them."""
        rounds = (_ROUNDS[0], _ROUNDS[1], _round(
            3, _SUZUKA, (_session(_grid(15, 12, 25), reconstructed=True, uid=3),)))
        self.assertEqual("", _document(rounds=rounds, through=2).blocks[0].note)


class NothingToRankTests(unittest.TestCase):
    """A season with no points yet is a sentence, not two empty grids."""

    _PENDING = (_round(1, _MELBOURNE,
                       (_session(_grid(25, 18, 15), session_type=_QUALIFYING),)),)

    def test_it_says_so_in_one_line_instead_of_two_headings_over_nothing(self):
        blocks = _document(rounds=self._PENDING, through=1).blocks
        self.assertEqual(1, len(blocks))
        self.assertIsInstance(blocks[0], Notes)
        self.assertEqual(["No round has scored points yet - standings count only a race the game "
                          "sent a final classification for."],
                         [line.text for line in blocks[0].lines])

    def test_it_still_titles_and_places_itself(self):
        """The image is worth sending: "nothing yet, after round 1" is an answer."""
        document = _document(rounds=self._PENDING, through=1)
        self.assertEqual("Season 1 (“Mittwoch League”) — Standings after round 1 (Melbourne)",
                         document.title)
        self.assertEqual("0 of 1 rounds counted", document.meta)

    def test_a_race_that_could_not_be_counted_is_named_there_too(self):
        """Otherwise the one state where the reason matters most is the one that never says it."""
        rounds = (_round(1, _MELBOURNE, (_session(_grid(25, 18, 15), reconstructed=True),)),)
        lines = _document(rounds=rounds, through=1).blocks[0].lines
        self.assertEqual(2, len(lines))
        self.assertTrue(lines[1].text.startswith("One race is missing from these totals"))

    def test_anything_to_rank_is_two_tables(self):
        self.assertEqual([Table, Table], [type(block) for block in _document().blocks])


if __name__ == "__main__":
    unittest.main()
