"""What an assignment proposes - the two rules behind the weekend page's writes.

Qt-free by design: anything deciding *what to offer* lives in ``ui/sessions/assignment`` precisely
so it can be asserted without a ``QApplication`` (DECISIONS -> Storage). A rule that needed one
would be in the wrong file.

**These tests are most of the cover season inference has.** Measured against ``f1league.db``
2026-09-07: the rule answers for the 28 sessions of the four career weekends, and every answer
names the round that session is already in - so with everything assigned no picker row is marked.
Its one live check (2026-09-10, the Jeddah weekend unassigned and re-assigned by hand) marked the
weekend's sessions suggested and left both Practice 2 attempts unmarked. No calendar here repeats
a track, so the repeated-track cases below are that rule's only cover.
"""
from __future__ import annotations

import unittest
from datetime import datetime

from f1telemetry.src.domain.models import SessionResult
from f1telemetry.src.domain.season import Season, SeasonMode, SeasonRound
from f1telemetry.src.protocol.enums import Formula, SessionType, Weather
from f1telemetry.src.ui.sessions.assignment import (
    picker_rows,
    suggested_placement,
    weekend_proposal,
)

# This database's real shapes: a plain weekend, and the sprint weekend whose Sprint is RACE (15)
# and whose Grand Prix is RACE_2 (16).
_PLAIN = (1, 2, 3, 5, 6, 7, 15)
_SPRINT = (1, 10, 11, 12, 15, 5, 6, 7, 16)
_PLAIN_TYPES = (SessionType.PRACTICE_1, SessionType.PRACTICE_2, SessionType.PRACTICE_3,
                SessionType.QUALIFYING_1, SessionType.QUALIFYING_2, SessionType.QUALIFYING_3,
                SessionType.RACE)

_CAREER = 3_602_001_884     # the season id every weekend of this database's career carries
_JEDDAH_WEEKEND = 3_602_002_284
_SUZUKA_WEEKEND = 473_146_008
_SUZUKA, _JEDDAH, _MONZA, _MELBOURNE = 13, 29, 11, 0

_SEASON = 2
_ROUND = 5


def make(stype, link, *, weekend, season_link=None, structure=_PLAIN, uid=None,
         recorded_at=None, track_id=_JEDDAH):
    """A bare SessionResult - only the fields these rules read are meaningful here.

    ``season_link`` defaults to the weekend's own id, which is what every online mode reports and
    what makes a session carry no season information at all.
    """
    return SessionResult(
        session_uid=uid if uid is not None else link,
        season_link_id=weekend if season_link is None else season_link,
        weekend_link_id=weekend,
        session_link_id=link,
        game_format=2026,
        track_id=track_id,
        session_type=stype,
        formula=Formula.F1_MODERN,
        weather=Weather.CLEAR,
        total_laps=10,
        game_mode=78,
        player_vehicle_index=0,
        weekend_structure=structure,
        recorded_at=recorded_at,
    )


def weekend(base, *, season_link=None, track_id=_JEDDAH, skip=()):
    """A whole plain weekend, leaving out the slots named in ``skip`` (by structure index)."""
    return [make(stype, base + 10 * i, weekend=base, season_link=season_link,
                 track_id=track_id, recorded_at=datetime(2026, 8, 23, 10 + i, 0))
            for i, stype in enumerate(_PLAIN_TYPES) if i not in skip]


def season(season_id, tracks, *, mode=SeasonMode.DRIVER_CAREER):
    """A season whose calendar is the given tracks, in order, from round 1."""
    return Season(
        mode=mode, number=1, game_format=2026, season_id=season_id,
        rounds=tuple(SeasonRound(round_number=i, track_id=track)
                     for i, track in enumerate(tracks, start=1)))


class WeekendProposalTest(unittest.TestCase):
    """Assigning one session offers the rest of its weekend - and says what it will not offer."""

    def setUp(self):
        self.sessions = weekend(_JEDDAH_WEEKEND)
        self.anchor = self.sessions[0]
        self.target = (_SEASON, _ROUND)

    def test_the_rest_of_the_weekend_is_offered_in_running_order(self):
        proposal = weekend_proposal(self.anchor, self.sessions, {}, self.target)
        self.assertEqual(
            ["Practice 2", "Practice 3", "Qualifying 1", "Qualifying 2", "Qualifying 3", "Race"],
            [p.label for p in proposal.sessions])
        self.assertEqual((), proposal.held_back)

    def test_the_anchor_is_never_offered_to_itself(self):
        proposal = weekend_proposal(self.anchor, self.sessions, {}, self.target)
        self.assertNotIn(self.anchor.session_uid,
                         {p.session.session_uid for p in proposal.sessions})

    def test_a_session_already_in_this_round_is_left_alone(self):
        placements = {self.sessions[1].session_uid: self.target}
        proposal = weekend_proposal(self.anchor, self.sessions, placements, self.target)
        self.assertNotIn("Practice 2", [p.label for p in proposal.sessions])
        self.assertEqual(5, len(proposal.sessions))

    def test_a_session_in_another_round_is_offered_and_says_it_would_move(self):
        elsewhere = (1, 12)
        placements = {self.sessions[1].session_uid: elsewhere}
        proposal = weekend_proposal(self.anchor, self.sessions, placements, self.target)
        moving = [p for p in proposal.sessions if p.placement is not None]
        self.assertEqual(1, len(moving))
        self.assertEqual("Practice 2", moving[0].label)
        self.assertEqual(elsewhere, moving[0].placement)

    def test_another_weekends_sessions_are_never_offered(self):
        pool = self.sessions + weekend(_SUZUKA_WEEKEND, track_id=_SUZUKA)
        proposal = weekend_proposal(self.anchor, pool, {}, self.target)
        self.assertEqual(6, len(proposal.sessions))
        self.assertTrue(all(p.session.weekend_link_id == _JEDDAH_WEEKEND
                            for p in proposal.sessions))

    def test_a_single_session_weekend_offers_nothing(self):
        alone = [make(SessionType.RACE, 4_046_315_935, weekend=4_046_315_905)]
        proposal = weekend_proposal(alone[0], alone, {}, self.target)
        self.assertEqual((), proposal.sessions)
        self.assertEqual((), proposal.held_back)

    def test_both_attempts_at_one_slot_are_held_back_and_named(self):
        """This database's real shape: weekend 3602002284's Practice 2 was driven twice."""
        retry = make(SessionType.PRACTICE_2, _JEDDAH_WEEKEND + 10, weekend=_JEDDAH_WEEKEND,
                     uid=8_448_489_651_239_998_166,
                     recorded_at=datetime(2026, 8, 23, 11, 59))
        pool = self.sessions + [retry]
        proposal = weekend_proposal(self.anchor, pool, {}, self.target)
        self.assertEqual(("Practice 2",), proposal.held_back)
        self.assertNotIn("Practice 2", [p.label for p in proposal.sessions])
        self.assertEqual(5, len(proposal.sessions))

    def test_a_repeat_slot_wholly_inside_the_round_is_not_reported_as_held_back(self):
        """It is not being kept out of anything, so saying so would be noise."""
        retry = make(SessionType.PRACTICE_2, _JEDDAH_WEEKEND + 10, weekend=_JEDDAH_WEEKEND,
                     uid=8_448_489_651_239_998_166,
                     recorded_at=datetime(2026, 8, 23, 11, 59))
        pool = self.sessions + [retry]
        placements = {self.sessions[1].session_uid: self.target,
                      retry.session_uid: self.target}
        proposal = weekend_proposal(self.anchor, pool, placements, self.target)
        self.assertEqual((), proposal.held_back)

    def test_a_sprint_weekend_offers_both_races_under_their_own_names(self):
        types = (SessionType.PRACTICE_1, SessionType.SPRINT_SHOOTOUT_1,
                 SessionType.SPRINT_SHOOTOUT_2, SessionType.SPRINT_SHOOTOUT_3,
                 SessionType.RACE, SessionType.QUALIFYING_1, SessionType.QUALIFYING_2,
                 SessionType.QUALIFYING_3, SessionType.RACE_2)
        sprint = [make(stype, _JEDDAH_WEEKEND + 10 * i, weekend=_JEDDAH_WEEKEND,
                       structure=_SPRINT, recorded_at=datetime(2026, 8, 23, 10 + i, 0))
                  for i, stype in enumerate(types)]
        proposal = weekend_proposal(sprint[0], sprint, {}, self.target)
        labels = [p.label for p in proposal.sessions]
        self.assertIn("Sprint Race", labels)
        self.assertIn("Race", labels)
        self.assertLess(labels.index("Sprint Race"), labels.index("Race"))


class SuggestedPlacementTest(unittest.TestCase):
    """Season inference - career modes only, and it names a season before it names a round."""

    def setUp(self):
        self.career = weekend(_JEDDAH_WEEKEND, season_link=_CAREER)
        self.earlier = weekend(3_602_001_984, season_link=_CAREER, track_id=_MELBOURNE)
        self.placements = {s.session_uid: (_SEASON, 2) for s in self.earlier}
        self.pool = self.career + self.earlier
        self.seasons = [season(_SEASON, [_SUZUKA, _MELBOURNE, _MONZA, _SUZUKA, _JEDDAH])]

    def test_the_career_weekends_track_names_its_round(self):
        self.assertEqual(
            (_SEASON, 5),
            suggested_placement(self.career[0], self.pool, self.seasons, self.placements))

    def test_an_online_weekend_carries_no_season_id_and_suggests_nothing(self):
        """season_link == weekend_link in 8 of 8 online weekends: it is the weekend's own id."""
        online = weekend(_SUZUKA_WEEKEND, track_id=_SUZUKA)
        pool = self.pool + online
        self.assertIsNone(
            suggested_placement(online[0], pool, self.seasons, self.placements))

    def test_a_career_id_no_assigned_session_names_suggests_nothing(self):
        self.assertIsNone(
            suggested_placement(self.career[0], self.pool, self.seasons, {}))

    def test_a_career_id_two_seasons_claim_is_ambiguous(self):
        placements = dict(self.placements)
        placements[self.earlier[0].session_uid] = (7, 2)
        self.assertIsNone(
            suggested_placement(self.career[0], self.pool, self.seasons, placements))

    def test_a_track_the_calendar_does_not_hold_suggests_nothing(self):
        seasons = [season(_SEASON, [_SUZUKA, _MELBOURNE, _MONZA])]
        self.assertIsNone(
            suggested_placement(self.career[0], self.pool, seasons, self.placements))

    def test_a_multi_attempt_slot_is_never_suggested(self):
        """The one live session season inference can reach, and the rule that refuses it."""
        retry = make(SessionType.PRACTICE_1, _JEDDAH_WEEKEND, weekend=_JEDDAH_WEEKEND,
                     season_link=_CAREER, uid=999,
                     recorded_at=datetime(2026, 8, 23, 9, 0))
        pool = self.pool + [retry]
        self.assertIsNone(
            suggested_placement(retry, pool, self.seasons, self.placements))
        self.assertIsNone(
            suggested_placement(self.career[0], pool, self.seasons, self.placements))

    def test_a_repeated_track_takes_the_lowest_round_that_is_free(self):
        seasons = [season(_SEASON, [_MONZA, _MELBOURNE, _MONZA, _SUZUKA, _MONZA])]
        monza = weekend(_JEDDAH_WEEKEND, season_link=_CAREER, track_id=_MONZA)
        pool = monza + self.earlier
        self.assertEqual(
            (_SEASON, 1),
            suggested_placement(monza[0], pool, seasons, self.placements))

    def test_a_repeated_track_skips_a_round_another_weekend_already_holds(self):
        seasons = [season(_SEASON, [_MONZA, _MELBOURNE, _MONZA, _SUZUKA, _MONZA])]
        monza = weekend(_JEDDAH_WEEKEND, season_link=_CAREER, track_id=_MONZA)
        taken = weekend(1_111_111_111, season_link=_CAREER, track_id=_MONZA)
        pool = monza + self.earlier + taken
        placements = dict(self.placements)
        placements.update({s.session_uid: (_SEASON, 1) for s in taken})
        self.assertEqual(
            (_SEASON, 3),
            suggested_placement(monza[0], pool, seasons, placements))

    def test_a_repeated_track_with_every_round_taken_suggests_nothing(self):
        seasons = [season(_SEASON, [_MONZA, _MELBOURNE, _MONZA])]
        monza = weekend(_JEDDAH_WEEKEND, season_link=_CAREER, track_id=_MONZA)
        first = weekend(1_111_111_111, season_link=_CAREER, track_id=_MONZA)
        third = weekend(2_222_222_222, season_link=_CAREER, track_id=_MONZA)
        pool = monza + self.earlier + first + third
        placements = dict(self.placements)
        placements.update({s.session_uid: (_SEASON, 1) for s in first})
        placements.update({s.session_uid: (_SEASON, 3) for s in third})
        self.assertIsNone(suggested_placement(monza[0], pool, seasons, placements))

    def test_a_round_already_holding_this_weekend_is_the_answer_not_an_obstacle(self):
        """The weekend is the stronger evidence: a round holds exactly one weekend."""
        seasons = [season(_SEASON, [_MONZA, _MELBOURNE, _MONZA])]
        monza = weekend(_JEDDAH_WEEKEND, season_link=_CAREER, track_id=_MONZA)
        placements = dict(self.placements)
        placements[monza[-1].session_uid] = (_SEASON, 3)
        pool = monza + self.earlier
        self.assertEqual(
            (_SEASON, 3),
            suggested_placement(monza[0], pool, seasons, placements))


class PickerRowsTest(unittest.TestCase):
    """What the picker offers for one round, and in what order."""

    def setUp(self):
        self.suzuka = weekend(_SUZUKA_WEEKEND, track_id=_SUZUKA)
        self.jeddah = weekend(_JEDDAH_WEEKEND, track_id=_JEDDAH)
        self.pool = self.suzuka + self.jeddah
        self.seasons = [season(_SEASON, [_SUZUKA, _MELBOURNE, _MONZA, _SUZUKA, _JEDDAH])]
        self.target = (_SEASON, 1)

    def test_the_default_filter_is_the_rounds_own_track(self):
        rows = picker_rows(self.pool, self.seasons, {}, self.target, track_id=_SUZUKA)
        self.assertEqual(7, len(rows))
        self.assertTrue(all(row.session.track_id == _SUZUKA for row in rows))

    def test_showing_all_tracks_offers_every_stored_session(self):
        rows = picker_rows(self.pool, self.seasons, {}, self.target, track_id=None)
        self.assertEqual(14, len(rows))

    def test_a_session_already_in_this_round_is_not_offered(self):
        placements = {self.suzuka[0].session_uid: self.target}
        rows = picker_rows(self.pool, self.seasons, placements, self.target, track_id=_SUZUKA)
        self.assertEqual(6, len(rows))

    def test_a_session_in_another_round_stays_and_is_marked(self):
        elsewhere = (1, 12)
        placements = {self.suzuka[0].session_uid: elsewhere}
        rows = picker_rows(self.pool, self.seasons, placements, self.target, track_id=_SUZUKA)
        marked = [row for row in rows if row.placement is not None]
        self.assertEqual(1, len(marked))
        self.assertEqual(elsewhere, marked[0].placement)

    def test_rows_carry_the_weekend_running_order(self):
        rows = picker_rows(self.pool, self.seasons, {}, self.target, track_id=_SUZUKA)
        self.assertEqual(
            ["Practice 1", "Practice 2", "Practice 3", "Qualifying 1", "Qualifying 2",
             "Qualifying 3", "Race"],
            [row.label for row in rows])

    def test_a_suggested_session_sorts_first(self):
        career = weekend(3_602_002_384, season_link=_CAREER, track_id=_SUZUKA)
        earlier = weekend(3_602_001_984, season_link=_CAREER, track_id=_MELBOURNE)
        pool = self.suzuka + career + earlier
        placements = {s.session_uid: (_SEASON, 2) for s in earlier}
        rows = picker_rows(pool, self.seasons, placements, self.target, track_id=_SUZUKA)
        self.assertTrue(rows[0].suggested)
        self.assertEqual(_SUZUKA_WEEKEND, rows[-1].session.weekend_link_id)
        self.assertEqual(7, sum(1 for row in rows if row.suggested))

    def test_both_attempts_at_a_slot_are_offered_and_neither_is_suggested(self):
        """Rule 3 declines to choose for the user; it never takes the choice away."""
        retry = make(SessionType.PRACTICE_2, _SUZUKA_WEEKEND + 10, weekend=_SUZUKA_WEEKEND,
                     track_id=_SUZUKA, uid=999, recorded_at=datetime(2026, 8, 25, 9, 0))
        pool = self.pool + [retry]
        rows = picker_rows(pool, self.seasons, {}, self.target, track_id=_SUZUKA)
        practice_2 = [row for row in rows if row.label == "Practice 2"]
        self.assertEqual(2, len(practice_2))
        self.assertTrue(all(row.attempts == 2 for row in practice_2))
        self.assertFalse(any(row.suggested for row in practice_2))

    def test_unassigned_sessions_sort_above_ones_that_would_have_to_move(self):
        """Picking an assigned session moves it, so the answer with no consequence leads."""
        newer = weekend(9_999_999_999, track_id=_SUZUKA)
        pool = self.suzuka + newer
        placements = {s.session_uid: (1, 12) for s in newer}
        rows = picker_rows(pool, self.seasons, placements, self.target, track_id=_SUZUKA)
        self.assertIsNone(rows[0].placement)
        self.assertIsNotNone(rows[-1].placement)
        self.assertEqual([row.placement is None for row in rows],
                         sorted((row.placement is None for row in rows), reverse=True))

    def test_a_row_carries_its_track_and_its_weekends_size(self):
        rows = picker_rows(self.pool, self.seasons, {}, self.target, track_id=_SUZUKA)
        self.assertEqual("Suzuka", rows[0].track)
        self.assertIn("7 sessions", rows[0].weekend)

    def test_nothing_stored_offers_nothing(self):
        self.assertEqual([], picker_rows([], self.seasons, {}, self.target, track_id=_SUZUKA))


if __name__ == "__main__":
    unittest.main()
