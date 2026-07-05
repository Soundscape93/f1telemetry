"""Test cases for the domain normalizer functions."""
from __future__ import annotations

from types import SimpleNamespace
import unittest

from f1telemetry.src.domain.models import Lap, Participant
from f1telemetry.src.domain.normalizer import (
    Sample,
    build_trace,
    normalize_classification,
    normalize_participants,
    normalize_session,
)
from f1telemetry.src.protocol.enums import Formula, ResultStatus, SessionType, Weather


def _header(**kwargs) -> SimpleNamespace:
    """Build a fake packet header for testing."""
    base = dict(session_uid=1, packet_format=2025, player_car_index=0, frame_identifier=0)
    base.update(kwargs)
    return SimpleNamespace(**base)


class NormalizeParticipantsTest(unittest.TestCase):
    """Test cases for normalizing participant data."""
    def _packet(self):
        """Build a fake participants packet for testing."""
        people = [
            SimpleNamespace(name=b"Leclerc", team_id=2, driver_id=9, race_number=16,
                            nationality=8, ai_controlled=0, network_id=1),
            SimpleNamespace(name=b"Verstappen", team_id=0, driver_id=3, race_number=1,
                            nationality=10, ai_controlled=1, network_id=0),
            SimpleNamespace(name=b"Ghost", team_id=99, driver_id=99, race_number=99,
                            nationality=99, ai_controlled=1, network_id=0),         # unused slot
        ]
        return SimpleNamespace(header=_header(player_car_index=0), num_active_cars=2, participants=people)
    

    def test_trim_to_active_cars(self):
        self.assertEqual(len(normalize_participants(self._packet())), 2)

    def test_marks_player_decodes_name_and_ai(self):
        roster = normalize_participants(self._packet())
        self.assertEqual(roster[0].driver_name, "Leclerc")
        self.assertTrue(roster[0].is_player)
        self.assertFalse(roster[0].is_ai)
        self.assertFalse(roster[1].is_player)
        self.assertEqual(roster[1].driver_name, "Verstappen")
        self.assertTrue(roster[1].is_ai)

    def test_vehicle_indices(self):
        self.assertEqual([p.vehicle_index for p in normalize_participants(self._packet())], [0, 1])


class NormalizeSessionTest(unittest.TestCase):
    """Test cases for normalizing session data."""
    def _packet(self):
        """Build a fake session packet for testing."""
        return SimpleNamespace(
            header=_header(session_uid=12345, packet_format=2026, player_car_index=3),
            season_link_identifier=100, weekend_link_identifier=200, session_link_identifier=300,
            track_id=7, session_type=int(SessionType.RACE), formula=int(Formula.F1_MODERN),
            weather=int(Weather.CLEAR), game_mode=28, total_laps=5)
    
    def test_metadata_and_keys(self):
        """The scaffold has the right metadata and hierarchy keys."""
        s = normalize_session(self._packet())
        self.assertEqual(s.session_uid, 12345)
        self.assertEqual((s.season_link_id, s.weekend_link_id, s.session_link_id), (100, 200, 300))
        self.assertEqual(s.game_format, 2026)
        self.assertEqual(s.player_vehicle_index, 3)
        self.assertEqual(s.total_laps, 5)

    def test_enums_resolved(self):
        """The scaffold has the right enum values for session type, formula, and weather."""
        s = normalize_session(self._packet())
        self.assertEqual(s.session_type, SessionType.RACE)
        self.assertEqual(s.formula, Formula.F1_MODERN)
        self.assertEqual(s.weather, Weather.CLEAR)

    def test_scaffold_content_empty(self):
        """The scaffold has empty content for participants, laps, setup, and classification."""
        s = normalize_session(self._packet())
        self.assertEqual(s.participants, ())
        self.assertEqual(s.laps, ())
        self.assertIsNone(s.classification)


class BuildTraceTest(unittest.TestCase):
    """Test cases for the trace builder function."""
    def test_transposes_samples_into_channels(self):
        """The builder transposes a list of Sample objects into a dict of channels."""
        samples = [
            Sample(distance=0.0, speed=100, throttle=1.0, brake=0.0, steer=0.0,
                   gear=3, engine_rpm=9000, drs=0, ers_store_energy=4000, ers_deploy_mode=1),
            Sample(distance=10.0, speed=120, throttle=0.8, brake=0.0, steer=0.1,
                gear=4, engine_rpm=9500, drs=1, ers_store_energy=3900, ers_deploy_mode=2),
        ]
        trace = build_trace(samples)
        self.assertEqual(len(trace), 2)
        self.assertEqual(trace.distance.tolist(), [0.0, 10.0])
        self.assertEqual(trace.speed.tolist(), [100, 120])
        self.assertEqual(trace.gear.tolist(), [3, 4])
        self.assertEqual(trace.ers_deploy_mode.tolist(), [1, 2])


class NormalizeClassificationTest(unittest.TestCase):
    """Test cases for normalizing classification data."""
    def _roster(self):
        """Build a fake roster of participants for testing."""
        return (
            Participant(vehicle_index=0, driver_name="You", team_id=2, driver_id=9,
                        race_number=16, nationality_id=8, is_ai=False, is_player=True, network_id=1),
            Participant(vehicle_index=1, driver_name="Rival", team_id=0, driver_id=3,
                        race_number=1, nationality_id=10, is_ai=True, is_player=False, network_id=0),
        )
    
    def _entry(self, pos, pts, actual, visual, end, n):
        """Build a fake classification entry for testing."""
        return SimpleNamespace(
            position=pos, num_laps=5, grid_position=pos, points=pts, num_pit_stops=1,
            result_status=int(ResultStatus.FINISHED), result_reason=0, best_lap_time_in_ms=68000,
            total_race_time=279.5, penalties_time=0, num_penalties=0, num_tyre_stints=n,
            tyre_stints_actual=actual + [0] * (8 - len(actual)),
            tyre_stints_visual=visual + [0] * (8 - len(visual)),
            tyre_stints_end_laps=end + [0] * (8 - len(end)))
    
    def _packet(self):
        """Build a fake classification packet for testing."""
        # car 0 finishes 2nd, car 1 wins -> must come out sorted with the winner first
        cars = [self._entry(2, 18, [17, 18], [16, 18], [2, 5], 2),
                self._entry(1, 25, [16], [16], [5], 1)]
        return SimpleNamespace(header=_header(player_car_index=0), num_cars=2,
            final_classification_data=cars)
    
    def test_sorted_by_position(self):
        """The classification is sorted by finishing position, not by vehicle index."""
        c = normalize_classification(self._packet(), self._roster())
        self.assertEqual([e.position for e in c.entries], [1, 2])

    def test_winner_and_player_denormalized(self):
        """The winner and player entries are denormalized with driver name and team."""
        c = normalize_classification(self._packet(), self._roster())
        # the winner is an AI (driver_id 3) -> canonical full name is baked in;
        # the player is human -> the captured name is left untouched
        self.assertEqual(c.winner.driver_name, "Fernando Alonso")
        self.assertEqual(c.winner.points, 25)
        self.assertEqual(c.player.driver_name, "You")
        self.assertEqual(c.player.is_player, True)
        self.assertEqual(c.player.team_id, 2)
        self.assertEqual(c.player.race_number, 16)
        self.assertEqual(c.winner.race_number, 1)

    def test_best_lap_num_from_history_map(self):
        """best_lap_num is taken from the per-car Session History map, by vehicle index."""
        c = normalize_classification(self._packet(), self._roster(), {0: 3, 1: 8})
        self.assertEqual(c.player.best_lap_num, 3)   # vehicle index 0
        self.assertEqual(c.winner.best_lap_num, 8)   # vehicle index 1

    def test_best_lap_num_defaults_to_zero(self):
        """With no history map, best_lap_num is 0 (no fastest-lap tyre resolvable)."""
        c = normalize_classification(self._packet(), self._roster())
        self.assertEqual(c.winner.best_lap_num, 0)

    def test_unknown_ai_id_keeps_captured_name(self):
        """An AI whose driver_id isn't in the appendix keeps its captured name."""
        roster = (
            Participant(vehicle_index=0, driver_name="You", team_id=2, driver_id=9,
                        race_number=16, nationality_id=8, is_ai=False, is_player=True, network_id=1),
            Participant(vehicle_index=1, driver_name="Backmarker", team_id=0, driver_id=9999,
                        race_number=1, nationality_id=10, is_ai=True, is_player=False, network_id=0),
        )
        c = normalize_classification(self._packet(), roster)
        self.assertEqual(c.winner.driver_name, "Backmarker")

    def test_tyre_stints_trimmed(self):
        """The tyre stint arrays are trimmed to the car's num_tyre_stints."""
        c = normalize_classification(self._packet(), self._roster())
        self.assertEqual(len(c.player.tyre_stints), 2)
        self.assertEqual(c.player.tyre_stints[0].visual_compound, 16)
        self.assertEqual(c.player.tyre_stints[0].actual_compound, 17)
        self.assertEqual(c.player.tyre_stints[1].end_lap, 5)

    def test_result_status_enum(self):
        """The result status is resolved to the ResultStatus enum."""
        c = normalize_classification(self._packet(), self._roster())
        self.assertEqual(c.player.result_status, ResultStatus.FINISHED)

    
class ModelPropertiesTest(unittest.TestCase):
    def test_lap_is_complete_tracks_lap_time(self):
        complete = Lap(lap_number=1, lap_time_ms=70000, sector1_ms=23000, sector2_ms=23000,
                       sector3_ms=24000, is_valid=True, trace=None)
        partial = Lap(lap_number=2, lap_time_ms=None, sector1_ms=None, sector2_ms=None,
                      sector3_ms=None, is_valid=False, trace=None)
        self.assertTrue(complete.is_complete)
        self.assertFalse(partial.is_complete)

    
if __name__ == "__main__":
    unittest.main()