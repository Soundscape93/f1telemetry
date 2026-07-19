"""Tests for the missing-Final-Classification fallback: when no Final Classification packet
arrives, ``reconstruct_classification`` (and the assembler that calls it) rebuilds a best-effort
result from the last Lap Data frame + per-car Session History, flagged ``is_reconstructed``.
"""
from __future__ import annotations

from types import SimpleNamespace
import unittest

from f1telemetry.src.domain.models import Participant
from f1telemetry.src.domain.normalizer import reconstruct_classification
from f1telemetry.src.protocol.enums import PacketId, ResultStatus
from f1telemetry.src.session.assembler import assemble
from f1telemetry.test.session.test_session_assembler import session_pkt, participants_pkt

def _header(**kwargs) -> SimpleNamespace:
    base = dict(session_uid=1, packet_format=2026, player_car_index=0, frame_identifier=0)
    base.update(kwargs)
    return SimpleNamespace(**base)

def _roster() -> tuple[Participant, ...]:
    return (
        Participant(vehicle_index=0, driver_name="You", team_id=2, driver_id=9,
                    race_number=16, nationality_id=8, is_ai=False, is_player=True, network_id=1),
        Participant(vehicle_index=1, driver_name="Rival", team_id=0, driver_id=3,
                    race_number=1, nationality_id=10, is_ai=True, is_player=False, network_id=0),
    )

def _lap_row(position, grid=None, laps_in_progress=1, pit_stops=1, penalties=0,
             status=ResultStatus.FINISHED) -> SimpleNamespace:
    """One car's Lap Data entry (the fields reconstruct_classification reads)."""
    return SimpleNamespace(
        car_position=position, grid_position=position if grid is None else grid,
        current_lap_num=laps_in_progress, num_pit_stops=pit_stops, penalties=penalties,
        result_status=int(status), lap_distance=0.0)

def _lap_data_packet(rows, player=0, uid=1, frame=0, pid=None) -> SimpleNamespace:
    hdr = _header(session_uid=uid, frame_identifier=frame, player_car_index=player)
    if pid is not None:
        hdr.packet_id = pid
    return SimpleNamespace(header=hdr, lap_data=list(rows))

def _stint(actual, visual, end) -> SimpleNamespace:
    return SimpleNamespace(tyre_actual_compound=actual, tyre_visual_compound=visual, end_lap=end)

def _sh(lap_ms, best_lap_num=0, stints=(), car_idx=0, uid=1, pid=None) -> SimpleNamespace:
    hdr = _header(session_uid=uid, player_car_index=0)
    if pid is not None:
        hdr.packet_id = pid
    return SimpleNamespace(
        header=hdr, car_idx=car_idx, num_laps=len(lap_ms), best_lap_time_lap_num=best_lap_num,
        lap_history_data=[SimpleNamespace(lap_time_in_ms=m) for m in lap_ms],
        num_tyre_stints=len(stints), tyre_stints_history_data=list(stints))

class ReconstructClassificationTest(unittest.TestCase):
    """Direct unit tests of reconstruct_classification."""

    def _build(self):
        # car 0 finishes P2 (with a 5s penalty), car 1 wins P1
        rows = [_lap_row(2, penalties=5), _lap_row(1)]
        histories = {
            0: _sh([90000, 88000], best_lap_num=2, stints=[_stint(16, 16, 1), _stint(17, 17, 2)]),
            1: _sh([80000, 79000], best_lap_num=1, stints=[_stint(16, 16, 2)], car_idx=1),
        }
        return reconstruct_classification(_roster(), _lap_data_packet(rows), histories, {0: 2, 1: 1})

    def test_is_reconstructed_flag_set(self):
        self.assertTrue(self._build().is_reconstructed)

    def test_sorted_by_position_winner_first(self):
        c = self._build()
        self.assertEqual([e.position for e in c.entries], [1, 2])
        self.assertEqual(c.winner.driver_name, "Fernando Alonso")   # AI id 3 -> canonical name
        self.assertTrue(c.player.is_player)
        self.assertEqual(c.player.position, 2)

    def test_total_race_time_recovered_from_lap_sum(self):
        c = self._build()
        self.assertAlmostEqual(c.player.total_race_time_s, 178.0)    # 90.0 + 88.0
        self.assertAlmostEqual(c.winner.total_race_time_s, 159.0)    # 80.0 + 79.0

    def test_penalties_time_recovered_from_lap_data(self):
        c = self._build()
        self.assertEqual(c.player.penalties_time_s, 5)
        self.assertEqual(c.winner.penalties_time_s, 0)

    def test_best_lap_num_laps_and_stints(self):
        c = self._build()
        self.assertEqual(c.player.best_lap_time_ms, 88000)   # best_lap_time_lap_num=2 -> 2nd entry
        self.assertEqual(c.player.num_laps, 2)               # both laps completed
        self.assertEqual(c.player.best_lap_num, 2)           # from best_lap_num_by_index
        self.assertEqual(len(c.player.tyre_stints), 2)
        self.assertEqual(c.player.tyre_stints[1].end_lap, 2)

    def test_points_left_zero(self):
        # points are the one Final-Classification-only field; reconstruction leaves them 0
        self.assertEqual([e.points for e in self._build().entries], [0, 0])

    def test_no_lap_data_returns_none(self):
        self.assertIsNone(reconstruct_classification(_roster(), None, {}, {}))

    def test_missing_history_falls_back_to_lap_count(self):
        rows = [_lap_row(1, laps_in_progress=4)]              # on lap 4 -> 3 completed
        c = reconstruct_classification((_roster()[0],), _lap_data_packet(rows), {}, {})
        self.assertEqual(c.entries[0].num_laps, 3)
        self.assertEqual(c.entries[0].total_race_time_s, 0.0)  # no history to sum
        self.assertEqual(c.entries[0].best_lap_time_ms, 0)

class StrippedFinalClassificationStreamTest(unittest.TestCase):
    """End-to-end: a packet stream with NO Final Classification packet still yields a
    classification via the assembler's fallback, flagged reconstructed."""

    def test_no_final_classification_yields_reconstructed(self):
        rows = [_lap_row(2, penalties=5), _lap_row(1)]
        stream = [session_pkt(1), participants_pkt(1)]
        stream.append(_lap_data_packet(rows, uid=1, frame=1, pid=PacketId.LAP_DATA))
        stream.append(_sh([90000, 88000], best_lap_num=2, car_idx=0, pid=PacketId.SESSION_HISTORY))
        stream.append(_sh([80000, 79000], best_lap_num=1, car_idx=1, pid=PacketId.SESSION_HISTORY))
        (result,) = list(assemble(stream))

        c = result.classification
        self.assertIsNotNone(c)
        self.assertTrue(c.is_reconstructed)
        self.assertEqual([e.position for e in c.entries], [1, 2])
        self.assertEqual(c.player.penalties_time_s, 5)
        self.assertAlmostEqual(c.player.total_race_time_s, 178.0)
        self.assertEqual(c.player.best_lap_num, 2)

if __name__ == "__main__":
    unittest.main()
