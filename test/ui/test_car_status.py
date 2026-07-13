"""Tests for the pure car-status threshold model (iteration 2c, Qt-free).

Covers the three threshold families and the assembled part/corner builders without a QApplication.
"""
from __future__ import annotations

import unittest

from f1telemetry.src.domain.models import CarDamage, LapTyreContext
from f1telemetry.src.protocol.enums import ActualTyreCompound
from f1telemetry.src.ui.components.car_status import (
    Status,
    body_status,
    brake_temp_status,
    damage_parts,
    tyre_corners,
    tyre_temp_status,
    tyre_window,
    wear_status,
    worst,
)


class MonotonicThresholdTest(unittest.TestCase):
    def test_wear_bands_60_80(self):
        self.assertEqual(wear_status(0), Status.OK)
        self.assertEqual(wear_status(59), Status.OK)
        self.assertEqual(wear_status(60), Status.WARNING)
        self.assertEqual(wear_status(79), Status.WARNING)
        self.assertEqual(wear_status(80), Status.CRITICAL)
        self.assertEqual(wear_status(100), Status.CRITICAL)

    def test_body_bands_15_40_are_stricter(self):
        self.assertEqual(body_status(14), Status.OK)
        self.assertEqual(body_status(15), Status.WARNING)
        self.assertEqual(body_status(39), Status.WARNING)
        self.assertEqual(body_status(40), Status.CRITICAL)
        # a value that is only a warning for the body is still OK for wear
        self.assertEqual(wear_status(40), Status.OK)


class TyreTempBandTest(unittest.TestCase):
    def test_compound_specific_windows(self):
        c5 = ActualTyreCompound.C5.value      # window (70, 90)
        self.assertEqual(tyre_temp_status(65, c5), Status.COLD)
        self.assertEqual(tyre_temp_status(80, c5), Status.OK)
        self.assertEqual(tyre_temp_status(95, c5), Status.CRITICAL)
        c1 = ActualTyreCompound.C1.value      # window (90, 115)
        self.assertEqual(tyre_temp_status(88, c1), Status.COLD)   # 88 is COLD on C1, OK on C5
        self.assertEqual(tyre_temp_status(100, c1), Status.OK)
        self.assertEqual(tyre_temp_status(120, c1), Status.CRITICAL)

    def test_boundaries_inclusive_of_window(self):
        c5 = ActualTyreCompound.C5.value
        self.assertEqual(tyre_temp_status(70, c5), Status.OK)     # == cold_below -> in window
        self.assertEqual(tyre_temp_status(90, c5), Status.OK)     # == hot_above -> in window

    def test_unknown_compound_uses_default_window(self):
        self.assertEqual(tyre_window(999), (80, 110))
        self.assertEqual(tyre_temp_status(75, 999), Status.COLD)
        self.assertEqual(tyre_temp_status(90, 999), Status.OK)
        self.assertEqual(tyre_temp_status(120, 999), Status.CRITICAL)

    def test_missing_reading_is_none(self):
        self.assertEqual(tyre_temp_status(0, ActualTyreCompound.C3.value), Status.NONE)


class BrakeTempBandTest(unittest.TestCase):
    def test_bands(self):
        self.assertEqual(brake_temp_status(0), Status.NONE)
        self.assertEqual(brake_temp_status(200), Status.COLD)
        self.assertEqual(brake_temp_status(400), Status.OK)
        self.assertEqual(brake_temp_status(750), Status.OK)       # boundary: not yet warning
        self.assertEqual(brake_temp_status(800), Status.WARNING)
        self.assertEqual(brake_temp_status(1100), Status.CRITICAL)


class WorstOfTest(unittest.TestCase):
    def test_severity_order(self):
        self.assertEqual(worst(Status.OK, Status.WARNING, Status.COLD), Status.WARNING)
        self.assertEqual(worst(Status.OK, Status.CRITICAL), Status.CRITICAL)
        self.assertEqual(worst(Status.OK, Status.COLD), Status.COLD)
        self.assertEqual(worst(Status.NONE, Status.OK), Status.OK)


def _damage(**overrides):
    base = dict(
        brakes=(0, 0, 0, 0), front_left_wing=0, front_right_wing=0, rear_wing=0,
        floor=0, diffuser=0, sidepod=0, gearbox=0, engine=0,
        engine_mguh_wear=0, engine_es_wear=0, engine_ce_wear=0, engine_ice_wear=0,
        engine_mguk_wear=0, engine_tc_wear=0,
        drs_fault=False, ers_fault=False, engine_blown=False, engine_seized=False,
        brake_temp=(0, 0, 0, 0), engine_temp=0,
    )
    base.update(overrides)
    return CarDamage(**base)


class DamagePartsTest(unittest.TestCase):
    def test_engine_block_takes_worst_subwear(self):
        parts = {p.key: p for p in damage_parts(_damage(engine_ice_wear=10, engine_mguk_wear=82))}
        self.assertEqual(parts["engine"].status, Status.CRITICAL)   # 82 -> red
        self.assertIn("MGU-K 82%", parts["engine"].detail)

    def test_body_uses_strict_rule(self):
        parts = {p.key: p for p in damage_parts(_damage(front_left_wing=20))}
        self.assertEqual(parts["front_wing_left"].status, Status.WARNING)   # 20% -> orange (strict)

    def test_keys_and_colours_present(self):
        parts = {p.key: p for p in damage_parts(_damage())}
        for key in ("front_wing_left", "front_wing_right", "rear_wing", "floor",
                    "diffuser", "sidepod", "engine", "gearbox"):
            self.assertIn(key, parts)
            self.assertTrue(parts[key].colour.startswith("#"))


class TyreCornersTest(unittest.TestCase):
    def _context(self):
        return LapTyreContext(
            actual_compound=ActualTyreCompound.C5.value, visual_compound=16, age_laps=4,
            wear=(41.0, 44.0, 18.0, 15.0),           # RL, RR, FL, FR
            surface_temp=(96, 121, 76, 80), carcass_temp=(96, 121, 72, 80),
        )

    def test_temp_and_wear_are_separate_signals(self):
        corners = {c.key: c for c in tyre_corners(self._context(),
                                                  _damage(brake_temp=(660, 665, 300, 300)))}
        rr = corners["rr"]                            # carcass 121 on C5 (hot) but wear 44 (ok)
        self.assertEqual(rr.temp_status, Status.CRITICAL)
        self.assertEqual(rr.wear_status, Status.OK)
        self.assertEqual(rr.brake_status, Status.OK)  # 665 °C in band
        fl = corners["fl"]                            # carcass 72 on C5 (in 70-90) -> OK
        self.assertEqual(fl.temp_status, Status.OK)

    def test_wheel_order_and_defaults_without_damage(self):
        corners = tyre_corners(self._context())       # no damage -> brake temp 0 -> NONE
        self.assertEqual([c.key for c in corners], ["rl", "rr", "fl", "fr"])
        self.assertEqual(corners[0].brake_status, Status.NONE)


if __name__ == "__main__":
    unittest.main()