"""Persistence tests for lap-view iteration 1a: LapStore (laps + Parquet traces + tyre context)
and the session setup-history round-trip on SessionStore.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest

import numpy as np

from f1telemetry.src.domain.models import (
    CarDamage, Lap, LapTrace, LapTyreContext, SessionResult, Setup, SetupSnapshot,
)
from f1telemetry.src.protocol.enums import Formula, SessionType, Weather
from f1telemetry.src.storage.sessions import SessionStore

try:
    import pyarrow  # noqa: F401
    from f1telemetry.src.storage.laps import LapStore
    _HAS_PYARROW = True
except ImportError:
    _HAS_PYARROW = False


def make_trace(n=5):
    return LapTrace(
        distance=np.linspace(0, 4000, n),
        speed=np.full(n, 250, dtype=int),
        throttle=np.ones(n),
        brake=np.zeros(n),
        steer=np.zeros(n),
        gear=np.full(n, 7, dtype=int),
        engine_rpm=np.full(n, 11000, dtype=int),
        drs=np.zeros(n, dtype=int),
        ers_store_energy=np.zeros(n, dtype=int),
        ers_deploy_mode=np.zeros(n, dtype=int),
    )


def make_damage():
    return CarDamage(
        brakes=(1, 2, 3, 4), front_left_wing=5, front_right_wing=6, rear_wing=30,
        floor=10, diffuser=0, sidepod=0, gearbox=0, engine=15,
        engine_mguh_wear=1, engine_es_wear=2, engine_ce_wear=3, engine_ice_wear=4,
        engine_mguk_wear=5, engine_tc_wear=6,
        drs_fault=False, ers_fault=False, engine_blown=False, engine_seized=False,
    )


def make_lap(n):
    return Lap(
        lap_number=n, lap_time_ms=80000 + n,
        sector1_ms=25000, sector2_ms=30000, sector3_ms=25000,
        is_valid=True, trace=make_trace(),
        tyre_context=LapTyreContext(actual_compound=16, visual_compound=16,
                                    age_laps=n, wear=(5.0, 6.0, 7.0, 8.0), damage=(2, 3, 4, 5),
                                    blisters=(0, 1, 0, 1)),
        damage=make_damage(),
    )


def make_setup(front_wing=5):
    return Setup(
        front_wing=front_wing, rear_wing=5, on_throttle=50, off_throttle=50,
        front_camber=-3.0, rear_camber=-1.5, front_toe=0.1, rear_toe=0.2,
        front_suspension=1, rear_suspension=1, front_anti_roll_bar=1, rear_anti_roll_bar=1,
        front_ride_height=3, rear_ride_height=4, brake_pressure=95, brake_bias=58,
        engine_braking=50, tyre_pressures=(22.0, 22.0, 23.0, 23.0), ballast=0, fuel_load=10.0,
    )


@unittest.skipUnless(_HAS_PYARROW, "pyarrow required for Parquet trace storage")
class LapStoreRoundTripTest(unittest.TestCase):
    def setUp(self):
        fd, self._db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._traces = tempfile.mkdtemp(suffix="_traces")
        self.store = LapStore(f"sqlite:///{self._db}", trace_dir=self._traces)
        self.addCleanup(shutil.rmtree, self._traces, True)
        self.addCleanup(os.unlink, self._db)
        self.addCleanup(self.store.close)

    def test_lap_trace_and_tyre_context_round_trip(self):
        self.store.save_laps(123, (make_lap(1), make_lap(2)))
        laps = self.store.load_laps(123)
        self.assertEqual([lap.lap_number for lap in laps], [1, 2])
        self.assertEqual(laps[0].lap_time_ms, 80001)
        self.assertEqual((laps[0].sector1_ms, laps[0].sector2_ms, laps[0].sector3_ms),
                         (25000, 30000, 25000))
        self.assertEqual(laps[0].tyre_context.actual_compound, 16)
        self.assertEqual(laps[0].tyre_context.age_laps, 1)
        self.assertEqual(laps[0].tyre_context.wear, (5.0, 6.0, 7.0, 8.0))
        self.assertEqual(laps[0].tyre_context.damage, (2, 3, 4, 5))
        self.assertEqual(laps[0].tyre_context.blisters, (0, 1, 0, 1))
        self.assertEqual(laps[0].damage.rear_wing, 30)
        self.assertEqual(laps[0].damage.brakes, (1, 2, 3, 4))
        self.assertEqual(laps[0].damage.engine_tc_wear, 6)
        self.assertFalse(laps[0].damage.engine_seized)
        self.assertEqual(len(laps[0].trace), 5)
        np.testing.assert_allclose(laps[0].trace.distance, make_trace().distance)
        np.testing.assert_array_equal(laps[0].trace.gear, make_trace().gear)

    def test_resave_replaces_laps(self):
        self.store.save_laps(123, (make_lap(1), make_lap(2), make_lap(3)))
        self.store.save_laps(123, (make_lap(1),))          # fewer laps -> no orphans
        self.assertEqual([lap.lap_number for lap in self.store.load_laps(123)], [1])

    def test_delete_removes_laps_and_traces(self):
        self.store.save_laps(123, (make_lap(1),))
        self.assertEqual(self.store.delete(123), 1)
        self.assertEqual(self.store.load_laps(123), ())
        self.assertFalse(os.path.exists(os.path.join(self._traces, "123")))

    def test_uint64_high_bit_uid(self):
        big = 0x8000_0000_0000_0000
        self.store.save_laps(big, (make_lap(1),))
        self.assertEqual([lap.lap_number for lap in self.store.load_laps(big)], [1])


class SetupHistoryStorageTest(unittest.TestCase):
    """The session's setup history (JSON on the session row) survives save/load."""

    def setUp(self):
        fd, self._db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.store = SessionStore(f"sqlite:///{self._db}")
        self.addCleanup(os.unlink, self._db)
        self.addCleanup(self.store.close)

    def _session(self, history):
        return SessionResult(
            session_uid=777, season_link_id=1, weekend_link_id=2, session_link_id=3,
            game_format=2026, track_id=7, session_type=SessionType.PRACTICE_1,
            formula=Formula.F1_MODERN, weather=Weather.CLEAR, total_laps=10,
            game_mode=27, player_vehicle_index=0, setup_history=history)

    def test_setup_history_round_trips(self):
        history = (SetupSnapshot(0, make_setup(5)), SetupSnapshot(6, make_setup(9)))
        self.store.save(self._session(history))
        loaded = self.store.load(777)
        self.assertEqual([s.from_lap for s in loaded.setup_history], [0, 6])
        self.assertEqual(loaded.setup_history[1].setup.front_wing, 9)
        self.assertEqual(loaded.setup_history[0].setup.tyre_pressures, (22.0, 22.0, 23.0, 23.0))
        self.assertEqual(loaded.setup_for_lap(6).front_wing, 9)
        self.assertEqual(loaded.setup_for_lap(2).front_wing, 5)

    def test_empty_setup_history_round_trips(self):
        self.store.save(self._session(()))
        self.assertEqual(self.store.load(777).setup_history, ())


if __name__ == "__main__":
    unittest.main()
