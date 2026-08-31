"""
Test cases for ERS-related functionality in the session assembler.
"""
from __future__ import annotations

from types import SimpleNamespace
import math
import unittest

import numpy as np

from f1telemetry.src.domain.models import LapTrace
from f1telemetry.src.domain.normalizer import telemetry_sample
from f1telemetry.src.protocol.enums import PacketId
from f1telemetry.src.session.assembler import _SessionBuilder


class LapTraceTest(unittest.TestCase):
    def test_lap_trace_rejects_mismatched_channel_lengths(self) -> None:
        with self.assertRaises(ValueError):
            LapTrace(
                distance=np.array([0.0, 1.0]),
                speed=np.array([1, 2]),
                throttle=np.array([0.1, 0.2]),
                brake=np.array([0.0, 0.0]),
                steer=np.array([0.0, 0.0]),
                gear=np.array([3, 4]),
                engine_rpm=np.array([1000, 2000]),
                drs=np.array([0, 1]),
                ers_store_energy=np.array([10]),
                ers_deploy_mode=np.array([0, 0]),
            )


class TelemetrySampleTest(unittest.TestCase):
    def test_telemetry_sample_uses_car_status_ers_fields(self) -> None:
        lap_data = SimpleNamespace(lap_distance=123.4, driver_status=4, pit_status=0,
                                   pit_lane_timer_active=0)
        car_telemetry = SimpleNamespace(
            speed=245,
            throttle=0.75,
            brake=0.05,
            steer=-0.12,
            gear=7,
            engine_rpm=11000,
            drs=1,
        )
        car_status = SimpleNamespace(ers_store_energy=4321, ers_deploy_mode=2, fuel_in_tank=48.5)

        sample = telemetry_sample(lap_data, car_telemetry, car_status)

        self.assertEqual(sample.distance, 123.4)
        self.assertEqual(sample.ers_store_energy, 4321)
        self.assertEqual(sample.ers_deploy_mode, 2)
        self.assertEqual(sample.fuel, 48.5)

    def test_telemetry_sample_defaults_ers_to_zero_without_car_status(self) -> None:
        lap_data = SimpleNamespace(lap_distance=50.0, driver_status=4, pit_status=0,
                                   pit_lane_timer_active=0)
        car_telemetry = SimpleNamespace(
            speed=180,
            throttle=0.5,
            brake=0.0,
            steer=0.0,
            gear=6,
            engine_rpm=9000,
            drs=0,
        )

        sample = telemetry_sample(lap_data, car_telemetry)

        self.assertEqual(sample.ers_store_energy, 0)
        self.assertEqual(sample.ers_deploy_mode, 0)
        self.assertTrue(math.isnan(sample.fuel), "Fuel in tank should be NaN when car status is not provided")


class SessionAssemblerErSCarryForwardTest(unittest.TestCase):
    def test_builder_carries_latest_car_status_forward_across_frames(self) -> None:
        builder = _SessionBuilder()

        builder.feed(
            SimpleNamespace(
                header=SimpleNamespace(
                    packet_id=PacketId.SESSION,
                    session_uid=1,
                    packet_format=2026,
                    player_car_index=0,
                    session_time=0.0,
                ),
                season_link_identifier=10,
                weekend_link_identifier=20,
                session_link_identifier=30,
                track_id=5,
                session_type=15,
                formula=0,
                weather=0,
                game_mode=28,
                total_laps=2,
                num_sessions_in_weekend=0,
                ai_difficulty=95,
                weekend_structure=[0] * 12,
                track_length=5000.0,
                sector_2_lap_distance_start=1500.0,
                sector_3_lap_distance_start=3000.0,
            )
        )

        builder.feed(
            SimpleNamespace(
                header=SimpleNamespace(
                    packet_id=PacketId.CAR_STATUS,
                    session_uid=1,
                    frame_identifier=100,
                    player_car_index=0,
                ),
                car_status_data=[SimpleNamespace(
                    ers_store_energy=111,
                    ers_deploy_mode=1,
                    actual_tyre_compound=16,
                    visual_tyre_compound=16,
                    tyres_age_laps=1,
                    fuel_in_tank=50.0
                    )],
            )
        )

        builder.feed(
            SimpleNamespace(
                header=SimpleNamespace(
                    packet_id=PacketId.SESSION_HISTORY,
                    session_uid=1,
                    player_car_index=0,
                ),
                car_idx=0,
                num_laps=1,
                best_lap_time_lap_num=1,
                lap_history_data=[
                    SimpleNamespace(
                        lap_time_in_ms=90000,
                        sector1_time_minutes_part=0,
                        sector1_time_ms_part=30000,
                        sector2_time_minutes_part=0,
                        sector2_time_ms_part=30000,
                        sector3_time_minutes_part=0,
                        sector3_time_ms_part=30000,
                        lap_valid_bit_flags=0x08,
                    )
                ],
            )
        )

        builder.feed(
            SimpleNamespace(
                header=SimpleNamespace(
                    packet_id=PacketId.LAP_DATA,
                    session_uid=1,
                    frame_identifier=200,
                    player_car_index=0,
                ),
                lap_data=[SimpleNamespace(current_lap_num=1, lap_distance=25.0,
                                          driver_status=4, pit_status=0,
                                          pit_lane_timer_active=0)],
            )
        )
        builder.feed(
            SimpleNamespace(
                header=SimpleNamespace(
                    packet_id=PacketId.CAR_TELEMETRY,
                    session_uid=1,
                    frame_identifier=200,
                    player_car_index=0,
                ),
                car_telemetry_data=[
                    SimpleNamespace(
                        speed=200,
                        throttle=0.7,
                        brake=0.0,
                        steer=0.0,
                        gear=7,
                        engine_rpm=10000,
                        drs=1,
                        tyres_surface_temperature=(90, 90, 90, 90),
                        tyres_inner_temperature=(95, 95, 95, 95),
                        brakes_temperature=(300, 300, 300, 300),
                        engine_temperature=110,
                    )
                ],
            )
        )

        builder.feed(
            SimpleNamespace(
                header=SimpleNamespace(
                    packet_id=PacketId.CAR_STATUS,
                    session_uid=1,
                    frame_identifier=201,
                    player_car_index=0,
                ),
                car_status_data=[SimpleNamespace(
                    ers_store_energy=222,
                    ers_deploy_mode=2,
                    actual_tyre_compound=16,
                    visual_tyre_compound=16,
                    tyres_age_laps=1,
                    fuel_in_tank=49.5
                )],
            )
        )

        builder.feed(
            SimpleNamespace(
                header=SimpleNamespace(
                    packet_id=PacketId.LAP_DATA,
                    session_uid=1,
                    frame_identifier=201,
                    player_car_index=0,
                ),
                lap_data=[SimpleNamespace(current_lap_num=1, lap_distance=50.0,
                                          driver_status=4, pit_status=0,
                                          pit_lane_timer_active=0)],
            )
        )
        builder.feed(
            SimpleNamespace(
                header=SimpleNamespace(
                    packet_id=PacketId.CAR_TELEMETRY,
                    session_uid=1,
                    frame_identifier=201,
                    player_car_index=0,
                ),
                car_telemetry_data=[
                    SimpleNamespace(
                        speed=210,
                        throttle=0.8,
                        brake=0.0,
                        steer=0.0,
                        gear=8,
                        engine_rpm=10500,
                        drs=1,
                        tyres_surface_temperature=(90, 90, 90, 90),
                        tyres_inner_temperature=(95, 95, 95, 95),
                        brakes_temperature=(300, 300, 300, 300),
                        engine_temperature=110,
                    )
                ],
            )
        )

        result = builder.build()
        self.assertIsNotNone(result)
        assert result is not None

        self.assertEqual(len(result.laps), 1)
        self.assertEqual(result.laps[0].trace.ers_store_energy.tolist(), [111, 222])
        self.assertEqual(result.laps[0].trace.ers_deploy_mode.tolist(), [1, 2])
        # lap-start fuel = the first frame's Car Status reading (50.0), not the later 49.5
        self.assertEqual(result.laps[0].fuel_in_tank, 50.0)


if __name__ == "__main__":
    unittest.main()