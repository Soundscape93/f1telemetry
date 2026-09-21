"""Where a stored session is placed - the shared rules, and E1e's automatic career assignment.

``domain/placement`` is Qt-free and store-free, so nothing here needs a store or a ``QApplication``.
The career rule is the only rule in the app that writes without asking, so each of its nine
conditions has a test that fails it on its own. The fixtures are this database's real shapes: the
Driver Career '26, whose first five weekends sit at ``3602001884 + 100 * index`` and fill rounds 1-5
of season 2, and the My Team '26 career, whose only weekend reports its own id as the season id.
The proposal's rules, built on the same primitives, are ``test/ui/test_assignment``'s.
"""
from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime

from f1telemetry.src.domain.models import SessionResult
from f1telemetry.src.domain.placement import (
    CAREER_GAME_MODES,
    CareerHold,
    CareerPlan,
    HoldReason,
    plan_career_placements,
    weekends_by_round,
)
from f1telemetry.src.domain.season import Season, SeasonMode, SeasonRound
from f1telemetry.src.protocol.enums import Formula, SessionType, Weather
from f1telemetry.src.protocol.reference import GAME_MODE_NAMES

# This database's 2026 calendar, which its Driver Career (season 2) and My Team (season 5) share.
_CALENDAR = (0, 2, 13, 3, 29, 30, 6, 5, 4, 17, 7, 10, 9, 26, 11, 42, 20, 12, 15, 19, 16, 31, 32, 14)
_MELBOURNE, _SHANGHAI, _SUZUKA, _JEDDAH = 0, 2, 13, 29

_DRIVER_CAREER = 3_602_001_884      # the Driver Career '26 season id; weekend n is this + 100 * n
_MY_TEAM = 3_350_470_238            # the My Team '26 season id - and its first weekend's id as well
_ONLINE_WEEKEND = 4_046_315_905     # an Online Custom weekend, whose season id is its own id
_LEAGUE_SEASON, _DRIVER_SEASON, _MY_TEAM_SEASON = 1, 2, 5

_PLAIN = (1, 2, 3, 5, 6, 7, 15)
_PLAIN_TYPES = (SessionType.PRACTICE_1, SessionType.PRACTICE_2, SessionType.PRACTICE_3,
                SessionType.QUALIFYING_1, SessionType.QUALIFYING_2, SessionType.QUALIFYING_3,
                SessionType.RACE)
_MY_TEAM_STRUCTURE = (1, 2, 3, 8, 15)


def make(stype, slot, *, weekend, season_link, track_id, game_mode=78, structure=_PLAIN,
         uid=None, recorded_at=None):
    """A bare SessionResult at ``slot`` of ``weekend`` - only the fields placement reads matter."""
    link = weekend + 10 * slot
    return SessionResult(
        session_uid=link if uid is None else uid,
        season_link_id=season_link,
        weekend_link_id=weekend,
        session_link_id=link,
        game_format=2026,
        track_id=track_id,
        session_type=stype,
        formula=Formula.F1_MODERN,
        weather=Weather.CLEAR,
        total_laps=10,
        game_mode=game_mode,
        player_vehicle_index=0,
        weekend_structure=structure,
        recorded_at=recorded_at,
    )


def career_weekend(index, track_id, *, career=_DRIVER_CAREER, day=1):
    """A whole plain weekend of one career at weekend index ``index``, driven on one day."""
    weekend = career + 100 * index
    return [make(stype, slot, weekend=weekend, season_link=career, track_id=track_id,
                 recorded_at=datetime(2026, 8, day, 10 + slot))
            for slot, stype in enumerate(_PLAIN_TYPES)]


def season(season_id, mode, tracks=_CALENDAR):
    """A saved season whose calendar is ``tracks`` in order, from round 1."""
    return Season(mode=mode, number=1, game_format=2026, season_id=season_id,
                  rounds=tuple(SeasonRound(round_number=i, track_id=track)
                               for i, track in enumerate(tracks, start=1)))


def placed(sessions, placement):
    """Every one of ``sessions`` placed at ``placement``."""
    return {s.session_uid: placement for s in sessions}


def applied(placements, plan):
    """``placements`` as they stand once the pipeline has written ``plan``."""
    result = {uid: placement for uid, placement in placements.items()
              if (uid, placement) not in plan.unassigned}
    result.update(plan.assigned)
    return result


def held(session, reason, track_round, index_round, season_id=_DRIVER_SEASON):
    """The plan that holds ``session`` alone."""
    return CareerPlan(held=(CareerHold(session_uid=session.session_uid, season_id=season_id,
                                       reason=reason, track_round=track_round,
                                       index_round=index_round),))


class DriverCareerTest(unittest.TestCase):
    """Each condition failing alone: Melbourne placed by hand in round 1, Jeddah newly stored."""

    def setUp(self):
        self.melbourne = career_weekend(0, _MELBOURNE, day=4)
        self.jeddah = career_weekend(4, _JEDDAH, day=23)
        self.race = self.jeddah[-1]
        self.all = self.melbourne + self.jeddah
        self.placements = placed(self.melbourne, (_DRIVER_SEASON, 1))
        self.seasons = [season(_LEAGUE_SEASON, SeasonMode.GRAND_PRIX),
                        season(_DRIVER_SEASON, SeasonMode.DRIVER_CAREER),
                        season(_MY_TEAM_SEASON, SeasonMode.MY_TEAM)]

    def plan(self, new, all_sessions=None, *, seasons=None, placements=None):
        return plan_career_placements(
            new,
            self.all if all_sessions is None else all_sessions,
            self.seasons if seasons is None else seasons,
            self.placements if placements is None else placements)

    def test_a_new_weekend_of_a_placed_career_fills_its_round(self):
        """Index 4 is round 5, Jeddah's round - and a weekend never blocks its own round."""
        self.assertEqual(
            CareerPlan(assigned=tuple((s.session_uid, (_DRIVER_SEASON, 5)) for s in self.jeddah)),
            self.plan(self.jeddah))

    def test_1_a_game_mode_off_the_allow_list_is_left_alone(self):
        # Grand Prix '23, Online Custom, Career '25 Online, Challenge Career '25
        for game_mode in (4, 7, 29, 30):
            with self.subTest(game_mode=game_mode):
                race = replace(self.race, game_mode=game_mode)
                self.assertEqual(
                    CareerPlan(), self.plan([race], self.melbourne + self.jeddah[:-1] + [race]))

    def test_2_a_session_already_placed_is_never_moved(self):
        placements = {**self.placements, self.race.session_uid: (_DRIVER_SEASON, 7)}
        self.assertEqual(CareerPlan(), self.plan([self.race], placements=placements))

    def test_3_a_career_no_season_holds_is_left_alone(self):
        self.assertEqual(CareerPlan(), self.plan([self.race], placements={}))

    def test_3_a_career_two_seasons_hold_is_left_alone(self):
        seasons = self.seasons + [season(6, SeasonMode.DRIVER_CAREER)]
        placements = {**self.placements, self.melbourne[0].session_uid: (6, 1)}
        self.assertEqual(
            CareerPlan(), self.plan([self.race], seasons=seasons, placements=placements))

    def test_3_an_unsaved_season_is_never_the_one_named(self):
        unsaved = replace(season(_DRIVER_SEASON, SeasonMode.DRIVER_CAREER), season_id=None)
        self.assertEqual(
            CareerPlan(),
            self.plan([self.race], seasons=self.seasons + [unsaved], placements={}))

    def test_4_a_career_placed_in_a_season_of_the_other_career_mode_is_left_alone(self):
        placements = placed(self.melbourne, (_MY_TEAM_SEASON, 1))
        self.assertEqual(CareerPlan(), self.plan([self.race], placements=placements))

    def test_5_a_weekend_index_that_is_not_a_whole_number_from_zero_is_left_alone(self):
        for offset in (450, -100):
            with self.subTest(offset=offset):
                race = make(SessionType.RACE, 6, weekend=_DRIVER_CAREER + offset,
                             season_link=_DRIVER_CAREER, track_id=_JEDDAH)
                self.assertEqual(CareerPlan(), self.plan([race], self.melbourne + [race]))

    def test_6_a_track_the_calendar_does_not_hold_is_held(self):
        seasons = [season(_DRIVER_SEASON, SeasonMode.DRIVER_CAREER,
                          tuple(t for t in _CALENDAR if t != _JEDDAH))]
        self.assertEqual(held(self.race, HoldReason.NO_TRACK_ROUND, None, 5),
                         self.plan([self.race], seasons=seasons))

    def test_6_a_track_the_calendar_holds_twice_is_held_not_guessed(self):
        calendar = _CALENDAR[:8] + (_JEDDAH,) + _CALENDAR[9:]      # Jeddah at rounds 5 and 9
        seasons = [season(_DRIVER_SEASON, SeasonMode.DRIVER_CAREER, calendar)]
        self.assertEqual(held(self.race, HoldReason.NO_TRACK_ROUND, None, 5),
                         self.plan([self.race], seasons=seasons))

    def test_7_a_weekend_after_a_skipped_one_is_held_with_both_rounds(self):
        """If the index counts weekends driven, skipping Shanghai makes Suzuka index 1, not 2."""
        suzuka = career_weekend(1, _SUZUKA, day=12)
        self.assertEqual(held(suzuka[-1], HoldReason.ROUNDS_DISAGREE, 3, 2),
                         self.plan([suzuka[-1]], self.melbourne + suzuka))

    def test_7_a_weekend_after_a_skipped_one_is_written_if_the_index_counts_rounds(self):
        suzuka = career_weekend(2, _SUZUKA, day=12)
        self.assertEqual(CareerPlan(assigned=((suzuka[-1].session_uid, (_DRIVER_SEASON, 3)),)),
                         self.plan([suzuka[-1]], self.melbourne + suzuka))

    def test_8_a_round_holding_another_weekend_is_held(self):
        online = make(SessionType.RACE, 6, weekend=_ONLINE_WEEKEND, season_link=_ONLINE_WEEKEND,
                      track_id=_JEDDAH, game_mode=7)
        placements = {**self.placements, online.session_uid: (_DRIVER_SEASON, 5)}
        self.assertEqual(held(self.race, HoldReason.ROUND_TAKEN, 5, 5),
                         self.plan([self.race], self.all + [online], placements=placements))

    def test_8_the_same_round_of_another_season_does_not_count(self):
        online = make(SessionType.RACE, 6, weekend=_ONLINE_WEEKEND, season_link=_ONLINE_WEEKEND,
                      track_id=_JEDDAH, game_mode=7)
        placements = {**self.placements, online.session_uid: (_MY_TEAM_SEASON, 5)}
        self.assertEqual(CareerPlan(assigned=((self.race.session_uid, (_DRIVER_SEASON, 5)),)),
                         self.plan([self.race], self.all + [online], placements=placements))

    def test_9_an_attempt_older_than_one_already_stored_is_held(self):
        """An import can bring an older attempt after the newer one: it never displaces it."""
        older = replace(self.jeddah[1], session_uid=8_448_489_651_239_998_166,
                        recorded_at=datetime(2026, 8, 23, 10, 30))
        self.assertEqual(held(older, HoldReason.SUPERSEDED, 5, 5),
                         self.plan([older], self.all + [older]))

    def test_the_first_condition_to_fail_names_the_hold(self):
        """An older attempt at a round another weekend holds is held for the round."""
        retry = replace(self.jeddah[1], session_uid=8_448_489_651_239_998_166,
                        recorded_at=datetime(2026, 8, 23, 10, 30))
        online = make(SessionType.RACE, 6, weekend=_ONLINE_WEEKEND, season_link=_ONLINE_WEEKEND,
                      track_id=_JEDDAH, game_mode=7)
        placements = {**self.placements, online.session_uid: (_DRIVER_SEASON, 5)}
        self.assertEqual(held(retry, HoldReason.ROUND_TAKEN, 5, 5),
                         self.plan([retry], self.all + [retry, online], placements=placements))


class MyTeamTest(unittest.TestCase):
    """The My Team '26 career: Melbourne, its first weekend, with only Practice 1 placed by hand."""

    def setUp(self):
        weekend = dict(weekend=_MY_TEAM, season_link=_MY_TEAM, track_id=_MELBOURNE, game_mode=79,
                       structure=_MY_TEAM_STRUCTURE)
        self.p1 = make(SessionType.PRACTICE_1, 0, uid=17_378_690_421_755_431_367,
                       recorded_at=datetime(2026, 9, 14, 16, 30, 53), **weekend)
        self.sq = make(SessionType.SHORT_QUALIFYING, 3, uid=1_895_972_933_271_309_063,
                       recorded_at=datetime(2026, 9, 14, 16, 43, 5), **weekend)
        self.race = make(SessionType.RACE, 4, uid=18_341_194_389_738_841_940,
                         recorded_at=datetime(2026, 9, 14, 16, 51, 2), **weekend)
        self.placements = {self.p1.session_uid: (_MY_TEAM_SEASON, 1)}

    def test_a_first_weekend_assigns_the_rest_of_itself_in_recorded_order(self):
        """Season id == weekend id, the shape the proposal reads as an online mode - index 0."""
        plan = plan_career_placements([self.race, self.sq], [self.p1, self.sq, self.race],
                                      [season(_MY_TEAM_SEASON, SeasonMode.MY_TEAM)],
                                      self.placements)
        self.assertEqual(CareerPlan(assigned=((self.sq.session_uid, (_MY_TEAM_SEASON, 1)),
                                              (self.race.session_uid, (_MY_TEAM_SEASON, 1)))),
                         plan)

    def test_each_career_is_written_only_into_its_own_season_mode(self):
        """27 and 28 are the same careers on the 2025 cars, with no capture of either here."""
        cases = ((79, SeasonMode.MY_TEAM, True), (79, SeasonMode.DRIVER_CAREER, False),
                 (27, SeasonMode.MY_TEAM, True), (27, SeasonMode.DRIVER_CAREER, False),
                 (28, SeasonMode.DRIVER_CAREER, True), (28, SeasonMode.MY_TEAM, False),
                 (78, SeasonMode.DRIVER_CAREER, True), (78, SeasonMode.MY_TEAM, False))
        for game_mode, mode, written in cases:
            with self.subTest(game_mode=game_mode, mode=mode.name):
                p1, race = (replace(s, game_mode=game_mode) for s in (self.p1, self.race))
                plan = plan_career_placements([race], [p1, race],
                                              [season(_MY_TEAM_SEASON, mode)], self.placements)
                expected = ((race.session_uid, (_MY_TEAM_SEASON, 1)),) if written else ()
                self.assertEqual(CareerPlan(assigned=expected), plan)

    def test_an_online_weekend_of_the_same_shape_is_left_alone(self):
        """Online Custom and Grand Prix '23 report the weekend's own id as the season id too."""
        for game_mode in (7, 4):
            with self.subTest(game_mode=game_mode):
                p1, race = (replace(s, game_mode=game_mode, season_link_id=_ONLINE_WEEKEND,
                                    weekend_link_id=_ONLINE_WEEKEND)
                            for s in (self.p1, self.race))
                plan = plan_career_placements(
                    [race], [p1, race], [season(_LEAGUE_SEASON, SeasonMode.GRAND_PRIX)],
                    {p1.session_uid: (_LEAGUE_SEASON, 1)})
                self.assertEqual(CareerPlan(), plan)


class BatchTest(unittest.TestCase):
    """Several new sessions at once - an import, or one recording holding more than one session."""

    def setUp(self):
        self.melbourne = career_weekend(0, _MELBOURNE, day=4)
        self.jeddah = career_weekend(4, _JEDDAH, day=23)
        self.placements = placed(self.melbourne, (_DRIVER_SEASON, 1))
        self.seasons = [season(_DRIVER_SEASON, SeasonMode.DRIVER_CAREER)]

    def test_two_weekends_claiming_one_round_the_earlier_recorded_takes_it(self):
        """Two careers filed in one season, whose Suzuka weekends are both index 2."""
        restarted = 1_234_567_800
        shanghai = career_weekend(1, _SHANGHAI, career=restarted, day=5)
        mine = career_weekend(2, _SUZUKA, day=20)[-1]
        theirs = career_weekend(2, _SUZUKA, career=restarted, day=12)[-1]
        placements = {**self.placements, **placed(shanghai, (_DRIVER_SEASON, 2))}
        plan = plan_career_placements([mine, theirs], self.melbourne + shanghai + [mine, theirs],
                                      self.seasons, placements)
        self.assertEqual(
            CareerPlan(assigned=((theirs.session_uid, (_DRIVER_SEASON, 3)),),
                       held=(CareerHold(session_uid=mine.session_uid, season_id=_DRIVER_SEASON,
                                        reason=HoldReason.ROUND_TAKEN, track_round=3,
                                        index_round=3),)),
            plan)

    def retry(self, hour, minute):
        """A second Practice 2 at Jeddah, recorded at ``hour``:``minute`` on the weekend's day."""
        return replace(self.jeddah[1], session_uid=8_448_489_651_239_998_166,
                       recorded_at=datetime(2026, 8, 23, hour, minute))

    def test_two_attempts_in_one_recording_the_later_is_written_and_the_earlier_held(self):
        """This database's Jeddah Practice 2: 11:59 and the 12:07 kept, in one recording."""
        retry = self.retry(11, 30)
        new = self.jeddah + [retry]
        plan = plan_career_placements(new, self.melbourne + new, self.seasons, self.placements)
        written = [s for s in sorted(new, key=lambda s: s.recorded_at) if s is not self.jeddah[1]]
        self.assertEqual(
            CareerPlan(assigned=tuple((s.session_uid, (_DRIVER_SEASON, 5)) for s in written),
                       held=(CareerHold(session_uid=self.jeddah[1].session_uid,
                                        season_id=_DRIVER_SEASON, reason=HoldReason.SUPERSEDED,
                                        track_round=5, index_round=5),)),
            plan)

    def test_a_later_attempt_replaces_an_earlier_one_assigned_to_its_round(self):
        """The usual case live: the aborted attempt was assigned as soon as it was recorded."""
        retry = self.retry(18, 0)
        placements = {**self.placements, **placed(self.jeddah, (_DRIVER_SEASON, 5))}
        plan = plan_career_placements([retry], self.melbourne + self.jeddah + [retry],
                                      self.seasons, placements)
        self.assertEqual(
            CareerPlan(assigned=((retry.session_uid, (_DRIVER_SEASON, 5)),),
                       unassigned=((self.jeddah[1].session_uid, (_DRIVER_SEASON, 5)),)),
            plan)

    def test_an_earlier_attempt_placed_in_another_round_is_left_alone(self):
        retry = self.retry(18, 0)
        placements = {**self.placements, **placed(self.jeddah, (_DRIVER_SEASON, 5)),
                      self.jeddah[1].session_uid: (_DRIVER_SEASON, 7)}
        plan = plan_career_placements([retry], self.melbourne + self.jeddah + [retry],
                                      self.seasons, placements)
        self.assertEqual(CareerPlan(assigned=((retry.session_uid, (_DRIVER_SEASON, 5)),)), plan)

    def test_recording_the_attempts_separately_ends_where_one_recording_does(self):
        retry = self.retry(11, 30)
        stored = self.melbourne + self.jeddah + [retry]
        together = applied(self.placements, plan_career_placements(
            self.jeddah + [retry], stored, self.seasons, self.placements))
        first = applied(self.placements, plan_career_placements(
            self.jeddah, self.melbourne + self.jeddah, self.seasons, self.placements))
        separately = applied(first, plan_career_placements(
            [retry], stored, self.seasons, first))
        self.assertEqual(together, separately)
        self.assertEqual((_DRIVER_SEASON, 5), separately[retry.session_uid])
        self.assertNotIn(self.jeddah[1].session_uid, separately)

    def test_two_attempts_recorded_at_the_same_moment_are_both_held(self):
        """Neither is the latest, so neither is chosen - the user picks."""
        twin = self.retry(11, 0)
        new = [self.jeddah[1], twin]
        plan = plan_career_placements(new, self.melbourne + self.jeddah + [twin], self.seasons,
                                      self.placements)
        self.assertEqual(
            CareerPlan(held=tuple(CareerHold(session_uid=s.session_uid, season_id=_DRIVER_SEASON,
                                             reason=HoldReason.SUPERSEDED, track_round=5,
                                             index_round=5)
                                  for s in new)),
            plan)

    def test_the_placements_passed_in_are_left_as_they_were(self):
        """A plan, not a write: the placements only change when the pipeline writes them."""
        retry = self.retry(18, 0)
        placements = {**self.placements, **placed(self.jeddah, (_DRIVER_SEASON, 5))}
        before = dict(placements)
        plan_career_placements([retry], self.melbourne + self.jeddah + [retry], self.seasons,
                               placements)
        self.assertEqual(before, placements)

    def test_nothing_new_plans_nothing(self):
        self.assertEqual(CareerPlan(), plan_career_placements(
            [], self.melbourne + self.jeddah, self.seasons, self.placements))


class AllowListTest(unittest.TestCase):
    """The game modes E1e writes for - raw ids, each paired with its own season mode."""

    def test_it_is_both_careers_on_both_car_sets_and_nothing_else(self):
        self.assertEqual({27, 28, 78, 79}, set(CAREER_GAME_MODES))

    def test_every_id_is_one_the_reference_names_and_pairs_with_the_career_it_names(self):
        """Keyed on the id (core invariant #9); the name is only how a mis-pairing would show."""
        careers = {SeasonMode.MY_TEAM: "My Team Career", SeasonMode.DRIVER_CAREER: "Driver Career"}
        for game_mode, mode in CAREER_GAME_MODES.items():
            with self.subTest(game_mode=game_mode):
                self.assertIn(game_mode, GAME_MODE_NAMES)
                self.assertTrue(GAME_MODE_NAMES[game_mode].startswith(careers[mode]))


class WeekendsByRoundTest(unittest.TestCase):
    """Which weekends a season's rounds already hold - condition 8, and the repeated-track rule."""

    def setUp(self):
        self.melbourne = career_weekend(0, _MELBOURNE, day=4)
        self.jeddah = career_weekend(4, _JEDDAH, day=23)

    def test_only_the_asked_seasons_rounds_count(self):
        placements = {**placed(self.melbourne, (_DRIVER_SEASON, 1)),
                      **placed(self.jeddah, (_MY_TEAM_SEASON, 1))}
        self.assertEqual(
            {1: {self.melbourne[0].weekend_link_id}},
            weekends_by_round(_DRIVER_SEASON, self.melbourne + self.jeddah, placements))

    def test_a_placement_whose_session_is_not_stored_is_skipped(self):
        placements = {**placed(self.melbourne, (_DRIVER_SEASON, 1)), 999: (_DRIVER_SEASON, 5)}
        self.assertEqual({1: {self.melbourne[0].weekend_link_id}},
                         weekends_by_round(_DRIVER_SEASON, self.melbourne, placements))


if __name__ == "__main__":
    unittest.main()
