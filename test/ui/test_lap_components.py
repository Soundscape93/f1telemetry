"""Tests for the pure row/layout logic behind the lap-detail components (Qt-free assertions).

The widgets themselves are thin Qt shells; the bug-prone parts - wheel-order placement and the
damage/setup row formatting - are plain functions, tested here without a QApplication.
"""
from __future__ import annotations

import unittest

from f1telemetry.src.domain.models import CarDamage, Setup
from f1telemetry.src.ui.components.damage_panel import damage_rows
from f1telemetry.src.ui.components.setup_panel import setup_fields


def make_damage():
    return CarDamage(
        brakes=(1, 2, 3, 4), front_left_wing=5, front_right_wing=6, rear_wing=30,
        floor=10, diffuser=0, sidepod=0, gearbox=0, engine=15,
        engine_mguh_wear=1, engine_es_wear=2, engine_ce_wear=3, engine_ice_wear=4,
        engine_mguk_wear=5, engine_tc_wear=6,
        drs_fault=False, ers_fault=True, engine_blown=False, engine_seized=False,
    )


def make_setup():
    return Setup(
        front_wing=5, rear_wing=7, on_throttle=50, off_throttle=55,
        front_camber=-3.0, rear_camber=-1.5, front_toe=0.1, rear_toe=0.2,
        front_suspension=1, rear_suspension=2, front_anti_roll_bar=3, rear_anti_roll_bar=4,
        front_ride_height=3, rear_ride_height=4, brake_pressure=95, brake_bias=58,
        engine_braking=50, tyre_pressures=(22.0, 22.5, 23.0, 23.5), ballast=0, fuel_load=10.0,
    )


class DamageRowsTest(unittest.TestCase):
    def test_sections_and_values(self):
        rows = dict(damage_rows(make_damage()))
        self.assertIsNone(rows["Aero"])            # section headers carry no value
        self.assertIsNone(rows["Faults"])
        self.assertEqual(rows["Rear wing"], "30%")
        self.assertEqual(rows["Brake FR"], "4%")   # brakes tuple RL,RR,FL,FR -> FR is index 3
        self.assertEqual(rows["ERS"], "⚠ yes")
        self.assertEqual(rows["DRS"], "—")


class SetupFieldsTest(unittest.TestCase):
    def test_sections_and_values(self):
        rows = setup_fields(make_setup())
        headers = [label for label, field in rows if field is None]
        fields = {f.label: f for _, f in rows if f is not None}

        self.assertIn("Aerodynamics", headers)
        self.assertNotIn("Ballast", fields)  # ballast removed
        self.assertNotIn("Ballast & Fuel", headers)
        self.assertIn("Fuel Load", fields)

        fw = fields["Front Wing"]
        self.assertEqual(fw.display, "5")
        self.assertEqual((fw.min_display, fw.max_display), ("0", "50"))
        self.assertAlmostEqual(fw.fraction, 5 / 50)

        self.assertEqual(fields["Front Right Tyre Pressure"].display, "22.0 PSI")


if __name__ == "__main__":
    unittest.main()
