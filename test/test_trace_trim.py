"""Tests for lap-trace trimming - isolating the timed lap from pre-line / out / formation samples.

`m_lapDistance` is negative before the car crosses the start/finish line, and the formation lap
(race lap 1) and out-laps share their current_lap_num with the timed lap that follows, so a raw lap
buffer can carry that junk in front of the real 0..track-length pass. ``_trim_to_timed_lap`` keeps
only the final forward pass; these tests pin the behaviour for the cases that were producing traces
running from ~0 back to ~-5000 and forward to ~+5000, while proving clean laps are left untouched.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from f1telemetry.src.session.assembler import _trim_to_timed_lap


def samples(distances):
    """Lightweight stand-ins - _trim_to_timed_lap only reads ``.distance``."""
    return [SimpleNamespace(distance=float(d)) for d in distances]


def distances(samples):
    return [s.distance for s in samples]


class TrimToTimedLapTest(unittest.TestCase):
    def test_clean_lap_is_unchanged(self):
        # a normal lap (e.g. a Melbourne race lap): 0..L, monotonic, no pre-line -> no-op
        clean = samples([0, 1000, 2500, 4000, 5300])
        self.assertEqual(distances(_trim_to_timed_lap(clean)), [0, 1000, 2500, 4000, 5300])

    def test_formation_then_race_lap_1(self):
        # race lap 1: formation lap at negative distance, then 0..L, one line crossing, monotonic
        buf = samples([-5300, -3000, -1000, -10, 0, 2000, 5300])
        self.assertEqual(distances(_trim_to_timed_lap(buf)), [0, 2000, 5300])

    def test_out_lap_then_timed_lap_positive_reset(self):
        # out-lap 0..L, then a reset to 0 for the timed lap (both under one lap number)
        buf = samples([0, 2500, 5300, 0, 2500, 5300])
        self.assertEqual(distances(_trim_to_timed_lap(buf)), [0, 2500, 5300])

    def test_observed_zero_back_to_negative_then_forward(self):
        # the reported shape: starts ~0, dips to ~-5000, then runs forward to ~+5000
        buf = samples([0, -2500, -5000, -2500, 0, 2500, 5000])
        self.assertEqual(distances(_trim_to_timed_lap(buf)), [0, 2500, 5000])

    def test_final_lap_keeps_racing_lap_not_the_slow_down(self):
        # last lap: the full racing lap, then a post-finish reset + short slow-down/in-lap fragment
        buf = samples([0, 2500, 5300, 0, 400, 800])
        self.assertEqual(distances(_trim_to_timed_lap(buf)), [0, 2500, 5300])

    def test_pure_out_lap_all_negative_is_dropped(self):
        # an out-lap that never crosses the line (all pre-line) trims to nothing -> not stored
        self.assertEqual(_trim_to_timed_lap(samples([-5300, -3000, -500])), [])

    def test_mid_lap_join_left_for_the_distance_guard(self):
        # joined mid-lap (no reset, no crossing): unchanged here; _store_trace drops it on >200m
        buf = samples([3000, 4000, 5300])
        self.assertEqual(distances(_trim_to_timed_lap(buf)), [3000, 4000, 5300])

    def test_small_backward_blip_is_not_a_boundary(self):
        # sensor noise / a brief backward wobble (<300 m) must not truncate a clean lap
        buf = samples([0, 1000, 990, 2000, 5300])
        self.assertEqual(distances(_trim_to_timed_lap(buf)), [0, 1000, 990, 2000, 5300])

    def test_empty_buffer(self):
        self.assertEqual(_trim_to_timed_lap([]), [])


if __name__ == "__main__":
    unittest.main()
