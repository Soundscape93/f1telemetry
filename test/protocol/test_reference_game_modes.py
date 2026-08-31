from __future__ import annotations

import unittest

from f1telemetry.src.protocol.reference import game_mode_name


class GameModeNameTest(unittest.TestCase):
    def test_driver_career_26_is_named(self):
        """78 is not in the UDP spec - it was established by reading real recordings."""
        self.assertEqual(game_mode_name(78), "Driver Career '26")

    def test_league_racing_still_reads_as_online_custom(self):
        self.assertEqual(game_mode_name(7), "Online Custom")

    def test_an_unknown_mode_still_renders(self):
        self.assertIn("99", game_mode_name(99))