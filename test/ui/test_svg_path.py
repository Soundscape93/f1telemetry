"""Tests for the SVG path ``d`` parser behind the car-status graphic (iteration 2c styling).

Covers M/L/H/V/C/Q/Z plus the S/T smooth-curve reflection and the A elliptical-arc conversion that
were added to unblock authoring intricate shapes in Inkscape. Parses paths only - no QApplication,
since ``_svg_path``/``_arc_to`` operate on a bare QPainterPath.
"""
from __future__ import annotations

import unittest

from f1telemetry.src.ui.components.car_status_graphic import _svg_path


def _elems(path):
    """(type, x, y) per element, rounded - lets two paths built the same way compare exactly."""
    return [(path.elementAt(i).type, round(path.elementAt(i).x, 3), round(path.elementAt(i).y, 3))
            for i in range(path.elementCount())]


class BasicCommandTest(unittest.TestCase):
    def test_absolute_line_square(self):
        rect = _svg_path("M0 0 L10 0 L10 10 L0 10 Z").boundingRect()
        self.assertAlmostEqual(rect.x(), 0.0)
        self.assertAlmostEqual(rect.y(), 0.0)
        self.assertAlmostEqual(rect.width(), 10.0)
        self.assertAlmostEqual(rect.height(), 10.0)

    def test_relative_matches_absolute(self):
        rel = _svg_path("M0 0 l10 0 l0 10 l-10 0 z")
        absolute = _svg_path("M0 0 L10 0 L10 10 L0 10 Z")
        self.assertEqual(_elems(rel), _elems(absolute))

    def test_horizontal_vertical(self):
        rect = _svg_path("M0 0 H10 V10 H0 Z").boundingRect()
        self.assertAlmostEqual(rect.width(), 10.0)
        self.assertAlmostEqual(rect.height(), 10.0)

    def test_cubic_endpoint(self):
        path = _svg_path("M0 0 C10 0 10 10 0 10")
        self.assertAlmostEqual(path.currentPosition().x(), 0.0)
        self.assertAlmostEqual(path.currentPosition().y(), 10.0)

    def test_implicit_repeat_after_moveto_is_lineto(self):
        # a second coordinate pair after M with no command letter is an implicit L
        rect = _svg_path("M0 0 10 0 10 10 0 10 Z").boundingRect()
        self.assertAlmostEqual(rect.width(), 10.0)
        self.assertAlmostEqual(rect.height(), 10.0)


class SmoothCurveTest(unittest.TestCase):
    def test_smooth_cubic_reflects_previous_control(self):
        # after C ... second control (10,10) at point (0,10) -> S first control reflects to (-10,10)
        smooth = _svg_path("M0 0 C10 0 10 10 0 10 S-10 20 0 20")
        explicit = _svg_path("M0 0 C10 0 10 10 0 10 C-10 10 -10 20 0 20")
        self.assertEqual(_elems(smooth), _elems(explicit))

    def test_smooth_quad_reflects_previous_control(self):
        # after Q ... control (0,10) at point (10,10) -> T control reflects to (20,10)
        smooth = _svg_path("M0 0 Q0 10 10 10 T20 20")
        explicit = _svg_path("M0 0 Q0 10 10 10 Q20 10 20 20")
        self.assertEqual(_elems(smooth), _elems(explicit))

    def test_smooth_without_prior_curve_uses_current_point(self):
        # S not preceded by C/S -> first control collapses to the current point
        smooth = _svg_path("M0 0 S10 10 20 0")
        explicit = _svg_path("M0 0 C0 0 10 10 20 0")
        self.assertEqual(_elems(smooth), _elems(explicit))


class ArcTest(unittest.TestCase):
    def test_semicircle_bounds_and_endpoint(self):
        # rx=ry=50, chord 100 -> exact half circle from (0,0) to (100,0)
        path = _svg_path("M0 0 A50 50 0 0 1 100 0")
        rect = path.boundingRect()
        self.assertAlmostEqual(rect.width(), 100.0, delta=0.5)
        self.assertAlmostEqual(rect.height(), 50.0, delta=0.5)
        self.assertAlmostEqual(path.currentPosition().x(), 100.0, delta=0.01)
        self.assertAlmostEqual(path.currentPosition().y(), 0.0, delta=0.01)

    def test_sweep_flag_flips_the_bulge(self):
        # sweep=1 draws the positive-angle arc -> bulges up (negative y in screen coords);
        # sweep=0 bulges down (positive y). The two land on opposite sides of the chord.
        up = _svg_path("M0 0 A50 50 0 0 1 100 0").boundingRect()
        down = _svg_path("M0 0 A50 50 0 0 0 100 0").boundingRect()
        self.assertLess(up.y(), -0.01)            # arc rises above the chord
        self.assertGreaterEqual(down.y(), -0.01)  # arc sits at/below the chord


    def test_unequal_radii_endpoint(self):
        path = _svg_path("M0 0 A80 40 0 0 1 160 0")
        rect = path.boundingRect()
        self.assertAlmostEqual(rect.width(), 160.0, delta=0.5)
        self.assertAlmostEqual(rect.height(), 40.0, delta=0.5)
        self.assertAlmostEqual(path.currentPosition().x(), 160.0, delta=0.01)

    def test_zero_radius_degenerates_to_line(self):
        path = _svg_path("M0 0 A0 50 0 0 1 10 10")
        self.assertAlmostEqual(path.currentPosition().x(), 10.0)
        self.assertAlmostEqual(path.currentPosition().y(), 10.0)


if __name__ == "__main__":
    unittest.main()
