"""Unit tests for the canonical track-layout builder (analysis.track_layout).

Pure numpy: fixed-grid resample + per-point nanmedian, the min-laps threshold, robustness to a
single-lap excursion, and the S/F-gap self-heal. No stores, no Qt.
"""
from __future__ import annotations

import unittest

import numpy as np

from f1telemetry.src.analysis.track_layout import build_layout
from f1telemetry.src.domain.models import LapTrace


def _trace(distance, pos_x, pos_z) -> LapTrace:
    """A minimal Motion-carrying LapTrace (the nine required channels are zero-filled)."""
    n = len(distance)
    zeros = np.zeros(n)
    return LapTrace(
        distance=np.asarray(distance, dtype=float),
        speed=zeros, throttle=zeros, brake=zeros, steer=zeros, gear=zeros,
        engine_rpm=zeros, drs=zeros, ers_store_energy=zeros, ers_deploy_mode=zeros,
        pos_x=np.asarray(pos_x, dtype=float), pos_z=np.asarray(pos_z, dtype=float),
        g_lat=zeros, g_long=zeros,
    )


def _circle(n=2000, length=3000.0, start=0.0, end=None, radius=500.0) -> LapTrace:
    """A clean circular 'lap': pos = (r·cosθ, r·sinθ), θ = 2π·distance/length."""
    end = length if end is None else end
    d = np.linspace(start, end, n)
    theta = 2 * np.pi * d / length
    return _trace(d, radius * np.cos(theta), radius * np.sin(theta))


class BuildLayoutTests(unittest.TestCase):
    def test_returns_none_below_min_laps(self):
        self.assertIsNone(build_layout([_circle(), _circle()]))  # default min_laps == 3

    def test_min_laps_override(self):
        self.assertIsNotNone(build_layout([_circle(), _circle()], min_laps=2))

    def test_identical_laps_match_analytic(self):
        layout = build_layout([_circle(), _circle(), _circle()])
        self.assertIsNotNone(layout)
        self.assertEqual(len(layout), 1000)
        theta = 2 * np.pi * layout.distance / 3000.0
        self.assertTrue(np.allclose(layout.pos_x, 500 * np.cos(theta), atol=1.0))
        self.assertTrue(np.allclose(layout.pos_z, 500 * np.sin(theta), atol=1.0))

    def test_excursion_is_rejected_by_median(self):
        d = np.linspace(0, 3000, 2000)
        theta = 2 * np.pi * d / 3000.0
        x, z = 500 * np.cos(theta), 500 * np.sin(theta)
        x_bad = x.copy()
        x_bad[900:1000] += 1000.0                       # a big single-lap off-line excursion
        layout = build_layout([_trace(d, x, z), _trace(d, x, z), _trace(d, x_bad, z)])
        expected = 500 * np.cos(2 * np.pi * layout.distance / 3000.0)
        self.assertTrue(np.allclose(layout.pos_x, expected, atol=1.0))

    def test_gap_self_heals_no_nan(self):
        # one lap misses the first 300 m (a lap-1-style S/F gap); the others cover it
        layout = build_layout([_circle(start=0), _circle(start=0), _circle(start=300)])
        self.assertFalse(np.isnan(layout.pos_x).any())
        self.assertFalse(np.isnan(layout.pos_z).any())


if __name__ == "__main__":
    unittest.main()