"""Selecting the weather icon a session is drawn with.

``MIXED`` is a string sentinel and deliberately not a ``Weather`` member (the game reports one
condition per Session packet, and the stored column is an int), so it is resolved at this one
seam rather than leaking into the domain or the schema.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from f1telemetry.src.protocol.enums import Weather
from f1telemetry.src.ui.components.weather import MIXED, _DROPS, session_weather


def _session(weather, mixed):
    return SimpleNamespace(weather=weather, is_mixed_weather=mixed)


class SessionWeatherTest(unittest.TestCase):

    def test_a_mixed_session_draws_the_mixed_icon(self):
        self.assertIs(session_weather(_session(Weather.OVERCAST, True)), MIXED)

    def test_an_unmixed_session_draws_its_snapshot(self):
        self.assertEqual(session_weather(_session(Weather.LIGHT_RAIN, False)), Weather.LIGHT_RAIN)

    def test_a_session_with_no_set_draws_its_snapshot(self):
        """A row ingested before the set existed reads exactly as it did before E14."""
        self.assertEqual(session_weather(_session(Weather.CLEAR, False)), Weather.CLEAR)

    def test_the_sentinel_is_not_a_weather_member(self):
        """If MIXED ever became a Weather it could be stored, and the column has no room for it."""
        self.assertNotIsInstance(MIXED, Weather)
        self.assertNotIn(MIXED, list(Weather))

    def test_the_icon_knows_how_to_draw_the_sentinel(self):
        """The painter is keyed by value; MIXED has to be one it recognises, not a fallback."""
        self.assertIn(MIXED, _DROPS)


if __name__ == "__main__":
    unittest.main()
