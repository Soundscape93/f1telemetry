"""Unit tests for analysis/traces.py - trace resample/align, time delta, and downsample.

Pure numpy (no Qt / pyqtgraph), so this runs in the normal suite and is the N-series-aware
foundation the iteration-2 overlay builds on.
"""
from __future__ import annotations

import unittest

import numpy as np

from f1telemetry.src.analysis import traces
from f1telemetry.src.domain.models import LapTrace


def make_trace(distance, speed, *, gear=None):
    """A LapTrace over the given distance/speed, other channels held constant/benign."""
    distance = np.asarray(distance, dtype=float)
    speed = np.asarray(speed, dtype=float)
    n = len(distance)
    return LapTrace(
        distance=distance, speed=speed,
        throttle=np.ones(n), brake=np.zeros(n), steer=np.zeros(n),
        gear=np.full(n, 6) if gear is None else np.asarray(gear),
        engine_rpm=np.full(n, 10000),
        drs=np.zeros(n, dtype=int), ers_store_energy=np.zeros(n, dtype=int),
        ers_deploy_mode=np.zeros(n, dtype=int),
    )


class SharedGridTest(unittest.TestCase):
    def test_grid_spans_only_overlap(self):
        a = make_trace([0, 500, 1000], [200, 200, 200])
        b = make_trace([50, 500, 900], [200, 200, 200])
        grid = traces.shared_distance_grid([a, b])
        self.assertEqual(grid[0], 50.0) # latest start
        self.assertEqual(grid[-1], 900.0) # earliest end

    def test_num_sets_point_count(self):
        a = make_trace([0, 1000], [200, 200])
        self.assertEqual(len(traces.shared_distance_grid([a], num=25)), 25)

    def test_non_overlapping_raises(self):
        a = make_trace([0, 100], [100, 100])
        b = make_trace([200, 300], [100, 100])
        with self.assertRaises(ValueError):
            traces.shared_distance_grid([a, b])


class AlignTest(unittest.TestCase):
    def test_all_series_share_the_grid_length(self):
        a = make_trace([0, 100, 200], [100, 150, 200])
        b = make_trace([0, 100, 200], [120, 120, 120])
        aligned = traces.align((a, b), num=11, labels=("A", "B"))
        self.assertEqual([t.label for t in aligned], ["A", "B"])
        self.assertTrue(all(len(t) == 11 for t in aligned))
        self.assertTrue(all(np.array_equal(t.distance, aligned[0].distance) for t in aligned))

    def test_linear_channel_interpolates(self):
        a = make_trace([0, 100], [100, 200])           # speed ramps 100 -> 200
        [aligned] = traces.align((a,), grid=np.array([50.0]))
        self.assertAlmostEqual(aligned.channel("speed")[0], 150.0)

    def test_discrete_channel_is_rounded_to_whole_numbers(self):
        a = make_trace([0, 100, 200], [200, 200, 200], gear=[5, 6, 7])
        [aligned] = traces.align((a,), num=21)
        g = aligned.channel("gear")
        np.testing.assert_array_equal(g, np.round(g))   # no fractional gears


class TimeDeltaTest(unittest.TestCase):
    def test_elapsed_time_from_constant_speed(self):
        # 36 km/h = 10 m/s; 100 m at 10 m/s = 10 s
        t = traces.elapsed_time([0, 50, 100], [36, 36, 36])
        np.testing.assert_allclose(t, [0.0, 5.0, 10.0])

    def test_faster_lap_is_ahead(self):
        ref = make_trace([0, 50, 100], [36, 36, 36])     # 10 m/s
        fast = make_trace([0, 50, 100], [72, 72, 72])    # 20 m/s
        a_ref, a_fast = traces.align((ref, fast))
        delta = traces.time_delta(a_ref, a_fast)
        self.assertTrue(np.all(delta <= 0))              # faster lap reaches each point sooner
        self.assertAlmostEqual(delta[-1], -5.0)          # 10 s vs 5 s over the lap

    def test_time_deltas_is_one_per_series(self):
        ref = make_trace([0, 100], [36, 36])
        others = [make_trace([0, 100], [72, 72]), make_trace([0, 100], [18, 18])]
        aligned = traces.align([ref, *others])
        deltas = traces.time_deltas(aligned[0], aligned[1:])
        self.assertEqual(len(deltas), 2)
        self.assertLess(deltas[0][-1], 0)                # faster -> ahead
        self.assertGreater(deltas[1][-1], 0)             # slower -> behind

    def test_mismatched_grid_raises(self):
        a = traces.resample(make_trace([0, 100], [100, 100]), np.array([0.0, 100.0]))
        b = traces.resample(make_trace([0, 100], [100, 100]), np.array([0.0, 50.0, 100.0]))
        with self.assertRaises(ValueError):
            traces.time_delta(a, b)


class DownsampleTest(unittest.TestCase):
    def test_caps_points_and_keeps_endpoints_aligned(self):
        x = np.arange(100)
        y = x * 2
        dx, dy = traces.downsample(x, y, max_points=10)
        self.assertLessEqual(len(dx), 10)
        self.assertEqual(dx[0], 0)
        self.assertEqual(dx[-1], 99)
        np.testing.assert_array_equal(dy, dx * 2)        # series stays aligned to x

    def test_small_input_unchanged(self):
        x = np.arange(5)
        dx, dy = traces.downsample(x, x * 3, max_points=50)
        np.testing.assert_array_equal(dx, x)
        np.testing.assert_array_equal(dy, x * 3)


class OptionalMotionChannelsTest(unittest.TestCase):
    """align/resample default to LapTrace.CHANNELS (nine), so the 2b motion channels are ignored
    unless explicitly requested - the iteration-2 overlay is unaffected by adding them."""

    def test_align_ignores_motion_channels_by_default(self):
        import dataclasses
        t = dataclasses.replace(
            make_trace([0, 100, 200], [100, 150, 200]),
            pos_x=np.zeros(3), pos_z=np.zeros(3), g_lat=np.zeros(3), g_long=np.zeros(3))
        [aligned] = traces.align((t,), num=11)
        for name in LapTrace.CHANNELS:
            self.assertEqual(len(aligned.channel(name)), 11)   # the nine required are resampled
        with self.assertRaises(KeyError):
            aligned.channel("g_lat")                           # motion channel not aligned

    def test_align_can_include_motion_when_asked(self):
        import dataclasses
        t = dataclasses.replace(
            make_trace([0, 100, 200], [100, 150, 200]),
            pos_x=np.zeros(3), pos_z=np.zeros(3),
            g_lat=np.array([0.0, 1.0, 2.0]), g_long=np.zeros(3))
        [aligned] = traces.align(
            (t,), num=11, channels=LapTrace.CHANNELS + ("g_lat", "g_long"))
        self.assertEqual(len(aligned.channel("g_lat")), 11)    # opt-in, as _draw_overlay does


if __name__ == "__main__":
    unittest.main()