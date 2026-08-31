"""``SessionResult.is_mixed_weather``: reading the set of conditions a session ran through.

The set itself is accumulated by the assembler (see test/session/test_session_assembler.py); this
is the reading of it. Dry is CLEAR / LIGHT_CLOUD / OVERCAST, wet is LIGHT_RAIN / HEAVY_RAIN /
STORM - the game's own split, per PRIORITIES -> E14.
"""
from __future__ import annotations

import unittest

from f1telemetry.src.domain.models import SessionResult
from f1telemetry.src.protocol.enums import Formula, SessionType, Weather


def make(*seen, snapshot=Weather.CLEAR):
    """A bare SessionResult - only the weather fields are meaningful here."""
    return SessionResult(
        session_uid=1, season_link_id=1, weekend_link_id=1, session_link_id=1,
        game_format=2026, track_id=2, session_type=SessionType.RACE,
        formula=Formula.F1_MODERN, weather=snapshot, total_laps=10, game_mode=28,
        player_vehicle_index=0, weather_seen=tuple(seen),
    )


class MixedWeatherTest(unittest.TestCase):

    def test_dry_and_wet_together_is_mixed(self):
        self.assertTrue(make(Weather.OVERCAST, Weather.LIGHT_RAIN).is_mixed_weather)
        self.assertTrue(make(Weather.STORM, Weather.CLEAR).is_mixed_weather)

    def test_several_dry_conditions_are_not_mixed(self):
        """Cloud rolling over is a change, but it is not a dry/wet session."""
        session = make(Weather.CLEAR, Weather.LIGHT_CLOUD, Weather.OVERCAST)
        self.assertFalse(session.is_mixed_weather)

    def test_several_wet_conditions_are_not_mixed(self):
        self.assertFalse(make(Weather.LIGHT_RAIN, Weather.HEAVY_RAIN, Weather.STORM)
                         .is_mixed_weather)

    def test_one_condition_is_not_mixed(self):
        self.assertFalse(make(Weather.LIGHT_RAIN).is_mixed_weather)

    def test_no_set_at_all_is_not_mixed(self):
        """A row ingested before the set existed. "Not captured" is not evidence of a change."""
        self.assertFalse(make().is_mixed_weather)

    def test_the_set_never_replaces_the_snapshot(self):
        """Mixed is an additional fact: a mixed session still says what it ended in."""
        session = make(Weather.LIGHT_RAIN, Weather.OVERCAST, snapshot=Weather.OVERCAST)
        self.assertTrue(session.is_mixed_weather)
        self.assertEqual(session.weather, Weather.OVERCAST)

    def test_a_value_outside_the_enum_belongs_to_neither_side(self):
        """safe_enum hands back the raw int for a condition newer than the enum (invariant #9).

        It must not be guessed into a side - on its own it can never make a session read as mixed.
        """
        self.assertFalse(make(Weather.CLEAR, 99).is_mixed_weather)
        self.assertTrue(make(Weather.CLEAR, 99, Weather.STORM).is_mixed_weather)

    def test_raw_ints_read_the_same_as_members(self):
        """Weather is an IntEnum, so a set read back as plain ints must classify identically."""
        self.assertTrue(make(2, 3).is_mixed_weather)
        self.assertFalse(make(0, 1, 2).is_mixed_weather)


if __name__ == "__main__":
    unittest.main()
