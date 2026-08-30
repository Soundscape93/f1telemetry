"""Persistence tests for lap-view iteration 1a: LapStore (laps + Parquet traces + tyre context)
and the session setup-history round-trip on SessionStore.
"""
from __future__ import annotations

import dataclasses

from sqlalchemy import select
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


def make_motion_trace(n=5):
    """A trace carrying the four optional 2b motion channels."""
    return dataclasses.replace(
        make_trace(n),
        pos_x=np.linspace(0.0, 100.0, n),
        pos_z=np.linspace(0.0, 200.0, n),
        g_lat=np.linspace(-1.0, 1.0, n),
        g_long=np.linspace(0.0, 2.0, n),
    )


def make_damage():
    return CarDamage(
        brakes=(1, 2, 3, 4), front_left_wing=5, front_right_wing=6, rear_wing=30,
        floor=10, diffuser=0, sidepod=0, gearbox=0, engine=15,
        engine_mguh_wear=1, engine_es_wear=2, engine_ce_wear=3, engine_ice_wear=4,
        engine_mguk_wear=5, engine_tc_wear=6,
        drs_fault=False, ers_fault=False, engine_blown=False, engine_seized=False,
        brake_temp=(350, 360, 420, 430), engine_temp=118,
    )



def make_lap(n):
    return Lap(
        lap_number=n, lap_time_ms=80000 + n,
        sector1_ms=25000, sector2_ms=30000, sector3_ms=25000,
        is_valid=True, trace=make_trace(),
        tyre_context=LapTyreContext(actual_compound=16, visual_compound=16,
                            age_laps=n, wear=(5.0, 6.0, 7.0, 8.0), damage=(2, 3, 4, 5),
                            blisters=(0, 1, 0, 1),
                            surface_temp=(95, 96, 90, 91), carcass_temp=(100, 101, 88, 89)),
        damage=make_damage(),
        fuel_in_tank=48.5,
        driver_status=3, pit_status=2, preceded_by_garage=True,
        is_out_lap=True, is_in_lap=False, safety_car=1, red_flagged=False
    )


def make_legacy_lap(n):
    """A lap as it was stored before PIPELINE_VERSION 4: no lap context at all."""
    return Lap(
        lap_number=n, lap_time_ms=80000 + n,
        sector1_ms=25000, sector2_ms=30000, sector3_ms=25000,
        is_valid=True, trace=make_trace(),
        tyre_context=LapTyreContext(actual_compound=16, visual_compound=16,
                            age_laps=n, wear=(5.0, 6.0, 7.0, 8.0), damage=(2, 3, 4, 5),
                            blisters=(0, 1, 0, 1),
                            surface_temp=(95, 96, 90, 91), carcass_temp=(100, 101, 88, 89)),
        damage=make_damage(),
        fuel_in_tank=48.5,
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
        self.assertEqual(laps[0].fuel_in_tank, 48.5)
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
        self.assertEqual(laps[0].tyre_context.surface_temp, (95, 96, 90, 91))
        self.assertEqual(laps[0].tyre_context.carcass_temp, (100, 101, 88, 89))
        self.assertEqual(laps[0].damage.brake_temp, (350, 360, 420, 430))
        self.assertEqual(laps[0].damage.engine_temp, 118)

    def test_lap_context_round_trips(self):
        """Every lap-context column, through the row and back - including the false ones.

        ``is_in_lap=False`` and ``red_flagged=False`` are in here on purpose: a mapping that dropped
        them would read back None, which the charts take as "never captured" and answer with the
        old inference instead.
        """
        self.store.save_laps(123, (make_lap(1),))
        lap = self.store.load_laps(123)[0]
        self.assertEqual(lap.driver_status, 3)
        self.assertEqual(lap.pit_status, 2)
        self.assertIs(lap.preceded_by_garage, True)
        self.assertIs(lap.is_out_lap, True)
        self.assertIs(lap.is_in_lap, False)
        self.assertEqual(lap.safety_car, 1)
        self.assertIs(lap.red_flagged, False)
        self.assertTrue(lap.has_lap_context)

    def test_a_lap_without_context_reads_back_none_and_not_a_coerced_false(self):
        """The distinction the whole fallback rests on: None means "this was never captured", and
        False would mean "the game said no". A lap stored before these columns has to read None."""
        self.store.save_laps(456, (make_legacy_lap(1),))
        lap = self.store.load_laps(456)[0]
        for field in ("driver_status", "pit_status", "preceded_by_garage", "is_out_lap",
                      "is_in_lap", "safety_car", "red_flagged"):
            with self.subTest(field=field):
                self.assertIsNone(getattr(lap, field))
        self.assertFalse(lap.has_lap_context)

    def test_lap_context_survives_the_cheap_listing(self):
        """``list`` is what the session detail reads, so the context has to come with it - it skips
        the Parquet files, not the columns."""
        self.store.save_laps(123, (make_lap(1),))
        lap = self.store.list(123)[0]
        self.assertTrue(lap.has_lap_context)
        self.assertIs(lap.is_out_lap, True)
        self.assertIsNone(lap.trace)

    def test_list_omits_traces_but_keeps_metadata(self):
        self.store.save_laps(123, (make_lap(1), make_lap(2)))
        laps = self.store.list(123)
        self.assertEqual([lap.lap_number for lap in laps], [1, 2])  # ordered, cheap
        self.assertEqual(all(lap.trace is None for lap in laps), True)  # no Parquet read
        self.assertEqual(laps[0].lap_time_ms, 80001, "metadata preserved")
        self.assertEqual(laps[0].tyre_context.wear, (5.0, 6.0, 7.0, 8.0), "tyre context preserved") # metadata still
        self.assertEqual(laps[0].damage.rear_wing, 30, "damage preserved")

    def test_load_single_lap_hydrates_trace(self):
        self.store.save_laps(123, (make_lap(1), make_lap(2)))
        lap = self.store.load(123, 2)
        self.assertEqual(lap.lap_number, 2)
        self.assertEqual(len(lap.trace), 5)     # trace hydrated
        np.testing.assert_array_equal(lap.trace.gear, make_trace().gear)
        self.assertIsNone(self.store.load(123, 999), "nonexistent lap returns None")    # missing lap -> None
    
    def test_motion_channels_round_trip(self):
        lap = dataclasses.replace(make_lap(1), trace=make_motion_trace())
        self.store.save_laps(321, (lap,))
        loaded = self.store.load(321, 1)
        self.assertTrue(loaded.trace.has_motion)
        np.testing.assert_allclose(loaded.trace.pos_x, make_motion_trace().pos_x)
        np.testing.assert_allclose(loaded.trace.g_lat, make_motion_trace().g_lat)

    def test_pre_2b_lap_loads_without_motion(self):
        # make_lap uses make_trace (no motion) -> the file has no motion columns, loads with None
        self.store.save_laps(55, (make_lap(1),))
        loaded = self.store.load(55, 1)
        self.assertIsNone(loaded.trace.pos_x)
        self.assertFalse(loaded.trace.has_motion)

    def test_pre_2c_damage_blob_loads_with_default_temps(self):
        lap = make_lap(1)
        self.store.save_laps(88, (lap,))
        # simulate an older row: strip the 2c keys from the persisted damage JSON
        from sqlalchemy import update
        from f1telemetry.src.storage.schema import LapRow
        with self.store._Session.begin() as db:
            row = db.scalar(select(LapRow).where(LapRow.session_uid == "88"))
            legacy = {k: v for k, v in row.damage.items() if k not in ("brake_temp", "engine_temp")}
            row.damage = legacy
        loaded = self.store.load(88, 1)
        self.assertEqual(loaded.damage.brake_temp, (0, 0, 0, 0))
        self.assertEqual(loaded.damage.engine_temp, 0)

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


@unittest.skipUnless(_HAS_PYARROW, "pyarrow required for Parquet trace storage")
class TraceFileMotionTest(unittest.TestCase):
    """trace_files writes motion columns only when present and reads pre-2b files without them."""

    def setUp(self):
        self._dir = tempfile.mkdtemp(suffix="_tf")
        self.addCleanup(shutil.rmtree, self._dir, True)

    def _path(self, name):
        return os.path.join(self._dir, name)

    def test_motion_columns_written_and_read(self):
        from f1telemetry.src.storage.trace_files import write_trace, read_trace
        p = self._path("motion.parquet")
        write_trace(p, make_motion_trace())
        back = read_trace(p)
        self.assertTrue(back.has_motion)
        np.testing.assert_allclose(back.pos_z, make_motion_trace().pos_z)

    def test_pre_2b_file_has_no_motion_columns_and_loads(self):
        import pyarrow.parquet as pq
        from f1telemetry.src.storage.trace_files import write_trace, read_trace, _REQUIRED
        p = self._path("legacy.parquet")
        write_trace(p, make_trace())                       # no motion -> nine-channel schema
        self.assertEqual(set(pq.read_table(p).column_names), set(_REQUIRED))
        back = read_trace(p)
        self.assertIsNone(back.pos_x)
        self.assertFalse(back.has_motion)


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
