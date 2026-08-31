"""Event-packet ingest: which codes are kept, the overtake filter, and the penalty replay merge.

The rules under test were settled by replaying all 33 captures rather than by reading the spec,
and each one exists because the obvious version of it was wrong - see PRIORITIES -> E15 and
TELEMETRY_NOTES -> "Event packets". The two that would silently lose or duplicate data are the
uid-0 replay (37% of all penalties) and the overtake filter (58% of raw events).
"""
from __future__ import annotations

from types import SimpleNamespace
import unittest

from f1telemetry.src.protocol.enums import DriverStatus, PacketId, PitStatus
from f1telemetry.src.session.assembler import assemble

from .test_session_assembler import _car_lap, _hdr, participants_pkt, session_pkt


def _car(lap_num=1, **state):
    """One car's Lap Data entry, as the overtake filter reads it.

    Delegates to the assembler suite's own helper rather than building a second one. That is not
    only tidiness: these streams carry no Final Classification packet, so ``build()`` falls back to
    ``reconstruct_classification``, which reads position / grid / stops / penalties / status off
    this same entry. A hand-rolled entry with only the four fields the filter needs raises
    ``AttributeError`` from the reconstruction, several layers from anything these tests are about.
    """
    return _car_lap(lap_num, 0.0, **state)


def lap_data_pkt(uid, cars, frame=1, player=0):
    """A Lap Data packet carrying a whole grid - the context an overtake is judged against."""
    return SimpleNamespace(header=_hdr(PacketId.LAP_DATA, uid, frame=frame, player=player),
                           lap_data=list(cars))


def penalty_pkt(uid, vehicle_idx, penalty_type=4, infringement=7, lap_num=3, time=3,
                other=255, places=255, frame=10, session_time=100.0):
    return SimpleNamespace(
        header=_hdr(PacketId.EVENT, uid, frame=frame, session_time=session_time),
        event_string_code=b"PENA",
        event_data_details=SimpleNamespace(penalty=SimpleNamespace(
            penalty_type=penalty_type, infringement_type=infringement,
            vehicle_idx=vehicle_idx, other_vehicle_idx=other, time=time,
            lap_num=lap_num, places_gained=places)))


def overtake_pkt(uid, overtaking, overtaken, frame=11, session_time=100.0):
    return SimpleNamespace(
        header=_hdr(PacketId.EVENT, uid, frame=frame, session_time=session_time),
        event_string_code=b"OVTK",
        event_data_details=SimpleNamespace(overtake=SimpleNamespace(
            overtaking_vehicle_idx=overtaking, being_overtaken_vehicle_idx=overtaken)))


def button_pkt(uid, frame=12):
    """The code that is 79% of every Event packet the game sends, and is never ingested."""
    return SimpleNamespace(header=_hdr(PacketId.EVENT, uid, frame=frame),
                           event_string_code=b"BUTN",
                           event_data_details=SimpleNamespace(buttons=SimpleNamespace(buttons=1)))


def _run(*packets, uid=100):
    """Assemble a minimal stream and return its single SessionResult."""
    stream = [session_pkt(uid), participants_pkt(uid), *packets]
    results = list(assemble(stream))
    assert len(results) == 1, results
    return results[0]


class AllowListTest(unittest.TestCase):

    def test_button_events_are_never_ingested(self):
        """BUTN is the player's controller input: 106,126 of 134,208 measured event packets."""
        session = _run(button_pkt(100))
        self.assertEqual(session.penalties, ())
        self.assertEqual(session.overtakes, ())

    def test_a_session_with_no_events_carries_empty_tuples(self):
        session = _run()
        self.assertEqual(session.penalties, ())
        self.assertEqual(session.overtakes, ())
        self.assertEqual(session.player_overtakes, (0, 0))


class PenaltyIngestTest(unittest.TestCase):

    def test_a_live_penalty_is_captured_with_its_lap_and_time(self):
        session = _run(penalty_pkt(100, vehicle_idx=3, lap_num=7, time=5))
        self.assertEqual(len(session.penalties), 1)
        penalty = session.penalties[0]
        self.assertEqual(penalty.vehicle_index, 3)
        self.assertEqual(penalty.lap_number, 7)
        self.assertEqual(penalty.time_s, 5)
        self.assertEqual(penalty.frame, 10)

    def test_the_255_sentinel_becomes_none_and_zero_survives(self):
        """`places_gained` is legitimately 0 in 73 of 127 measured rows and 255 in 47 of them."""
        session = _run(penalty_pkt(100, vehicle_idx=1, other=255, time=255, places=0))
        penalty = session.penalties[0]
        self.assertIsNone(penalty.other_vehicle_index)
        self.assertIsNone(penalty.time_s)
        self.assertEqual(penalty.places_gained, 0)

    def test_warnings_are_stored_but_are_not_sporting_penalties(self):
        """69 of 127 measured PENA events are Warnings; the game excludes them from num_penalties."""
        session = _run(penalty_pkt(100, vehicle_idx=1, penalty_type=5),      # Warning
                       penalty_pkt(100, vehicle_idx=1, penalty_type=4, frame=11))  # Time penalty
        self.assertEqual(len(session.penalties), 2)
        self.assertEqual([p.is_sporting for p in session.penalties], [False, True])

    def test_penalties_are_field_wide_and_readable_per_car(self):
        session = _run(penalty_pkt(100, vehicle_idx=3, frame=10),
                       penalty_pkt(100, vehicle_idx=7, frame=11))
        self.assertEqual(len(session.penalties_for(3)), 1)
        self.assertEqual(len(session.penalties_for(7)), 1)
        self.assertEqual(session.penalties_for(9), ())

    def test_penalties_are_ordered_by_lap(self):
        session = _run(penalty_pkt(100, vehicle_idx=1, lap_num=9, frame=10),
                       penalty_pkt(100, vehicle_idx=1, lap_num=2, frame=11))
        self.assertEqual([p.lap_number for p in session.penalties], [2, 9])


class PenaltyReplayTest(unittest.TestCase):
    """The end-of-session replay: uid 0, frame 0, repeated. Core invariant #3 does not hold here."""

    def test_a_replayed_penalty_is_not_dropped_as_init_noise(self):
        """37% of all measured penalties arrive only this way; the old rule discarded every one."""
        session = _run(penalty_pkt(0, vehicle_idx=3, lap_num=4, frame=0, session_time=2515.0))
        self.assertEqual(len(session.penalties), 1)
        self.assertEqual(session.penalties[0].vehicle_index, 3)

    def test_the_replay_repeating_itself_does_not_duplicate_a_penalty(self):
        """One measured capture replayed an 11-row log 64 times over."""
        replay = [penalty_pkt(0, vehicle_idx=3, lap_num=4, frame=0) for _ in range(7)]
        session = _run(*replay)
        self.assertEqual(len(session.penalties), 1)

    def test_the_replay_does_not_duplicate_a_penalty_already_seen_live(self):
        session = _run(penalty_pkt(100, vehicle_idx=3, lap_num=4, frame=10),
                       penalty_pkt(0, vehicle_idx=3, lap_num=4, frame=0))
        self.assertEqual(len(session.penalties), 1)
        self.assertEqual(session.penalties[0].frame, 10)      # the live row wins

    def test_the_replay_recovers_a_penalty_the_live_stream_missed(self):
        """A real case: 20260704_214647 stored +3 s whose live PENA packet never arrived."""
        session = _run(penalty_pkt(100, vehicle_idx=21, penalty_type=5, lap_num=1, frame=10),
                       penalty_pkt(0, vehicle_idx=21, penalty_type=5, lap_num=1, frame=0),
                       penalty_pkt(0, vehicle_idx=21, penalty_type=4, lap_num=4, time=3, frame=0))
        self.assertEqual(len(session.penalties), 2)
        sporting = [p for p in session.penalties if p.is_sporting]
        self.assertEqual([p.time_s for p in sporting], [3])

    def test_two_identical_live_penalties_both_survive_the_merge(self):
        """20260812_202452: one car took two Grid penalties eight seconds apart, and the game
        classified it num_penalties = 2. A dedupe on the detail alone would collapse them."""
        session = _run(
            penalty_pkt(100, vehicle_idx=13, penalty_type=2, infringement=0, lap_num=2,
                        time=255, frame=18853, session_time=927.6),
            penalty_pkt(100, vehicle_idx=13, penalty_type=2, infringement=0, lap_num=2,
                        time=255, frame=19027, session_time=936.1),
            penalty_pkt(0, vehicle_idx=13, penalty_type=2, infringement=0, lap_num=2,
                        time=255, frame=0))
        self.assertEqual(len(session.penalties_for(13)), 2)

    def test_a_replayed_event_before_any_session_is_ignored(self):
        """Nothing to attribute it to. Never observed - every measured replay followed a session."""
        results = list(assemble([penalty_pkt(0, vehicle_idx=1), session_pkt(100),
                                 participants_pkt(100)]))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].penalties, ())


class OvertakeFilterTest(unittest.TestCase):

    def _grid(self, uid=100):
        """Two cars, both racing. Tests that need a car in the pits build their own grid."""
        return lap_data_pkt(uid, [_car(), _car()])

    def test_a_pass_between_two_racing_cars_is_kept(self):
        session = _run(self._grid(), overtake_pkt(100, overtaking=1, overtaken=0))
        self.assertEqual(len(session.overtakes), 1)
        overtake = session.overtakes[0]
        self.assertEqual(overtake.overtaking_vehicle_index, 1)
        self.assertEqual(overtake.overtaken_vehicle_index, 0)

    def test_the_lap_number_is_the_overtaking_car_s(self):
        session = _run(lap_data_pkt(100, [_car(lap_num=4), _car(lap_num=9)]),
                       overtake_pkt(100, overtaking=1, overtaken=0))
        self.assertEqual(session.overtakes[0].lap_number, 9)

    def test_passing_a_car_in_the_pit_lane_is_not_an_overtake(self):
        """5,112 of 14,635 raw events have the overtaken car in the pit lane."""
        session = _run(lap_data_pkt(100, [_car(pit_status=PitStatus.IN_PIT_AREA), _car()]),
                       overtake_pkt(100, overtaking=1, overtaken=0))
        self.assertEqual(session.overtakes, ())

    def test_the_pit_lane_timer_alone_is_enough_to_drop_it(self):
        session = _run(lap_data_pkt(100, [_car(pit_lane_timer_active=1), _car()]),
                       overtake_pkt(100, overtaking=1, overtaken=0))
        self.assertEqual(session.overtakes, ())

    def test_passing_a_car_parked_in_the_garage_is_not_an_overtake(self):
        """2,827 raw events have the overtaken car sitting in the garage."""
        session = _run(lap_data_pkt(100, [_car(driver_status=DriverStatus.IN_GARAGE), _car()]),
                       overtake_pkt(100, overtaking=1, overtaken=0))
        self.assertEqual(session.overtakes, ())

    def test_an_out_lap_is_not_racing(self):
        session = _run(lap_data_pkt(100, [_car(driver_status=DriverStatus.OUT_LAP), _car()]),
                       overtake_pkt(100, overtaking=1, overtaken=0))
        self.assertEqual(session.overtakes, ())

    def test_the_overtaking_car_being_in_the_pits_also_drops_it(self):
        session = _run(lap_data_pkt(100, [_car(), _car(pit_status=PitStatus.PITTING)]),
                       overtake_pkt(100, overtaking=1, overtaken=0))
        self.assertEqual(session.overtakes, ())

    def test_a_pass_and_an_immediate_re_pass_are_two_events(self):
        """Both are kept on purpose: no cancel window is accurate per race (0.61x-1.91x)."""
        session = _run(self._grid(),
                       overtake_pkt(100, overtaking=1, overtaken=0, frame=11, session_time=100.0),
                       overtake_pkt(100, overtaking=0, overtaken=1, frame=40, session_time=101.5))
        self.assertEqual(len(session.overtakes), 2)

    def test_an_overtake_with_no_lap_data_yet_is_skipped(self):
        session = _run(overtake_pkt(100, overtaking=1, overtaken=0))
        self.assertEqual(session.overtakes, ())

    def test_an_index_outside_the_grid_is_skipped(self):
        """Never observed - all 14,635 measured events carried valid indices - but not assumed."""
        session = _run(self._grid(), overtake_pkt(100, overtaking=1, overtaken=23))
        self.assertEqual(session.overtakes, ())

    def test_an_overtake_on_a_zeroed_header_is_ignored(self):
        """The replay carries no frame or lap, so a pass in it could not be placed."""
        session = _run(self._grid(), overtake_pkt(0, overtaking=1, overtaken=0))
        self.assertEqual(session.overtakes, ())


class OvertakeCountTest(unittest.TestCase):
    """The derived reading. Never stored - see SessionResult.overtakes_for."""

    def _session(self):
        return _run(lap_data_pkt(100, [_car(), _car(), _car()]),
                    overtake_pkt(100, overtaking=0, overtaken=1, frame=11),
                    overtake_pkt(100, overtaking=0, overtaken=2, frame=12),
                    overtake_pkt(100, overtaking=2, overtaken=0, frame=13))

    def test_made_and_suffered_are_counted_separately(self):
        self.assertEqual(self._session().overtakes_for(0), (2, 1))
        self.assertEqual(self._session().overtakes_for(2), (1, 1))

    def test_a_car_in_no_pass_counts_zero(self):
        session = _run(lap_data_pkt(100, [_car(), _car()]),
                       overtake_pkt(100, overtaking=1, overtaken=0))
        self.assertEqual(session.overtakes_for(5), (0, 0))

    def test_the_player_count_uses_the_player_vehicle_index(self):
        """The details grid shows the player's own passes, never the field's."""
        self.assertEqual(self._session().player_overtakes, (2, 1))


if __name__ == "__main__":
    unittest.main()
