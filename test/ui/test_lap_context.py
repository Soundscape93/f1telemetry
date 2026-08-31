"""The shared lap classification: one reading of each lap, used by three parts of the session page.

The Laps box's indicator, whether the stint split treats a lap as a boundary, and whether the run's
average pace counts it all come from ``analyse_session``. These tests pin the two things that
matters about that: what each kind of lap is classified as, and that the *same* classification
drives the indicator and the exclusion - so the two cannot drift apart the way they did when each
derived its own answer.

Fixtures are the real sessions the stint rules are pinned against, with the stored fields set to
what the captures actually reported.
"""
import dataclasses
import unittest

from f1telemetry.src.domain.models import Lap, LapTyreContext
from f1telemetry.src.protocol.enums import DriverStatus, PitStatus, SafetyCarStatus
from f1telemetry.src.ui.sessions.lap_context import LapContext, analyse_session
from f1telemetry.src.ui.sessions.tyre_stints import stint_average_ms

_S, _M, _H = 16, 17, 18


def _lap(number, compound, wear, ms, age=0, fuel=None, **context):
    """One stored lap. ``context`` sets the lap-state fields; omit it for a pre-E17 row."""
    wheels = (wear, wear * 0.8, wear * 0.6, wear * 0.4)
    lap = Lap(lap_number=number, lap_time_ms=ms, sector1_ms=None, sector2_ms=None, sector3_ms=None,
              is_valid=True, fuel_in_tank=fuel,
              tyre_context=LapTyreContext(actual_compound=compound, visual_compound=compound,
                                          age_laps=age, wear=wheels))
    if not context:
        return lap
    defaults = dict(driver_status=int(DriverStatus.ON_TRACK), pit_status=int(PitStatus.NONE),
                    preceded_by_garage=False, is_out_lap=False, is_in_lap=False,
                    safety_car=int(SafetyCarStatus.NONE), red_flagged=False)
    return dataclasses.replace(lap, **{**defaults, **context})


def _race():
    """A race with a stop: lap 3 into the pits, lap 4 out of them, on a fresh set."""
    return [
        _lap(1, _M, 5.0, 95000, age=0, driver_status=int(DriverStatus.ON_TRACK)),
        _lap(2, _M, 10.0, 90000, age=1, driver_status=int(DriverStatus.ON_TRACK)),
        _lap(3, _M, 15.0, 93000, age=2, driver_status=int(DriverStatus.IN_LAP),
             pit_status=int(PitStatus.PITTING), is_in_lap=True),
        _lap(4, _H, 1.0, 115000, age=0, driver_status=int(DriverStatus.OUT_LAP),
             pit_status=int(PitStatus.IN_PIT_AREA), is_out_lap=True),
        _lap(5, _H, 5.0, 90500, age=1, driver_status=int(DriverStatus.ON_TRACK)),
        _lap(6, _H, 9.0, 90800, age=2, driver_status=int(DriverStatus.ON_TRACK)),
    ]


class KindsOfLapTest(unittest.TestCase):
    """One case per kind of lap the Laps box can mark, plus the two that carry no mark."""

    def setUp(self):
        self.analysis = analyse_session(_race(), standing_start=True)

    def test_a_normal_flying_lap_is_unmarked_and_counts(self):
        context = self.analysis.for_lap(2)
        self.assertEqual(context.indicators, ())
        self.assertFalse(context.excluded_from_pace)
        self.assertIsNone(context.tooltip)
        self.assertTrue(context.stored)

    def test_an_in_lap_is_marked_and_excluded(self):
        context = self.analysis.for_lap(3)
        self.assertEqual(context.indicators, ("IN-LAP",))
        self.assertTrue(context.excluded_from_pace)
        self.assertIn("In-lap", context.tooltip)

    def test_an_out_lap_is_marked_and_excluded(self):
        context = self.analysis.for_lap(4)
        self.assertEqual(context.indicators, ("OUT-LAP",))
        self.assertTrue(context.excluded_from_pace)
        self.assertIn("Out-lap", context.tooltip)

    def test_a_safety_car_lap_is_marked_and_excluded(self):
        laps = [dataclasses.replace(lap, safety_car=int(SafetyCarStatus.FULL))
                if lap.lap_number in (5, 6) else lap for lap in _race()]
        context = analyse_session(laps, standing_start=True).for_lap(5)
        self.assertEqual(context.indicators, ("SC",))
        self.assertTrue(context.under_safety_car)
        self.assertTrue(context.excluded_from_pace)

    def test_a_virtual_safety_car_counts_as_one_and_says_so(self):
        laps = [dataclasses.replace(lap, safety_car=int(SafetyCarStatus.VIRTUAL))
                if lap.lap_number == 5 else lap for lap in _race()]
        context = analyse_session(laps, standing_start=True).for_lap(5)
        self.assertTrue(context.under_safety_car)
        self.assertIn("Virtual safety car", context.tooltip)

    def test_a_formation_lap_is_not_a_safety_car_lap(self):
        """Every race here reports FORMATION_LAP on lap 1. It is not a safety car and must not be
        marked as one - the standing start already accounts for that lap being slow."""
        laps = [dataclasses.replace(lap, safety_car=int(SafetyCarStatus.FORMATION_LAP))
                if lap.lap_number == 1 else lap for lap in _race()]
        context = analyse_session(laps, standing_start=True).for_lap(1)
        self.assertFalse(context.under_safety_car)
        self.assertNotIn("SC", context.indicators)
        self.assertEqual(context.indicators, ("START",))    # the grid, which is the real reason

    def test_a_red_flagged_lap_is_marked_and_excluded(self):
        laps = [dataclasses.replace(lap, red_flagged=True) if lap.lap_number == 2 else lap
                for lap in _race()]
        context = analyse_session(laps, standing_start=True).for_lap(2)
        self.assertEqual(context.indicators, ("RED-FLAG",))
        self.assertTrue(context.excluded_from_pace)
        self.assertIn("Red-flag", context.tooltip)

    def test_a_double_stop_lap_carries_both_marks(self):
        """``11708585...`` lap 21: out of the pits at the start, back into them at the end."""
        laps = [dataclasses.replace(lap, is_in_lap=True, is_out_lap=True)
                if lap.lap_number == 4 else lap for lap in _race()]
        self.assertEqual(analyse_session(laps, standing_start=True).for_lap(4).indicators,
                         ("OUT-LAP", "IN-LAP"))      # in the order the lap ran, not by severity

    def test_legacy_laps_carry_no_stored_context_and_fall_back(self):
        """A session ingested before the bump: nothing is stored, so the classification comes from
        the shape of the split - and it still produces an answer rather than nothing."""
        laps = [_lap(1, _M, 5.0, 95000, age=0), _lap(2, _M, 10.0, 90000, age=1),
                _lap(3, _M, 15.0, 93000, age=2),
                _lap(4, _H, 1.0, 115000, age=0), _lap(5, _H, 5.0, 90500, age=1),
                _lap(6, _H, 9.0, 90800, age=2)]
        analysis = analyse_session(laps, standing_start=True)
        self.assertFalse(analysis.stored)
        self.assertFalse(analysis.for_lap(1).stored)
        self.assertTrue(analysis.for_lap(4).is_out_lap)     # inferred: first lap of a post-pit run
        self.assertTrue(analysis.for_lap(3).is_in_lap)      # inferred: the runs meet at 3 -> 4

    def test_a_lap_the_session_does_not_have_reads_as_nothing(self):
        context = self.analysis.for_lap(99)
        self.assertEqual(context, LapContext(99))
        self.assertFalse(context.excluded_from_pace)


class StandingStartTest(unittest.TestCase):
    """Lap 1 of a race begins at rest; lap 1 of a practice session does not."""

    def test_a_race_lap_one_is_marked_and_excluded(self):
        context = analyse_session(_race(), standing_start=True).for_lap(1)
        self.assertTrue(context.is_standing_start)
        self.assertEqual(context.indicators, ("START",))
        self.assertTrue(context.excluded_from_pace)
        self.assertIn("Standing start", context.tooltip)

    def test_a_practice_lap_one_is_neither_marked_nor_excluded(self):
        """The first stored lap of a practice run is often the quickest of the session, and it is a
        flying lap like any other. Only the caller knows which this is - a Sprint Race and a Grand
        Prix share a session_type (core invariant #5)."""
        context = analyse_session(_race(), standing_start=False).for_lap(1)
        self.assertFalse(context.is_standing_start)
        self.assertEqual(context.indicators, ())
        self.assertFalse(context.excluded_from_pace)
        self.assertIsNone(context.tooltip)

    def test_the_standing_start_says_it_is_out_of_the_average(self):
        context = analyse_session(_race(), standing_start=True).for_lap(1)
        self.assertIn("Standing start", context.tooltip)
        self.assertIn("average", context.tooltip)


class RedFlagRestartTest(unittest.TestCase):
    """A race restarts from the grid box, and the game never times the lap out of the pit lane.

    Both red flags in this database look exactly like this - Shanghai sprint 2 -> 4 and Shanghai
    race 11 -> 13, each with the intervening lap number missing. The restart lap is a standing
    start; the OUT_LAP the game leaves on it is left over from the lap it did not time.
    """

    def _restarted(self):
        """Laps 1, 2, 4, 5, 6 - the red flag falls on lap 2 and lap 3 is never stored."""
        return [
            _lap(1, _M, 5.0, 95000, age=0),
            _lap(2, _M, 2.3, 170826, age=1, red_flagged=True),      # wear reads near-new: artefact
            _lap(4, _M, 6.8, 99308, age=3, driver_status=int(DriverStatus.OUT_LAP)),
            _lap(5, _M, 11.5, 95745, age=4),
            _lap(6, _M, 16.1, 95435, age=5),
        ]

    def test_the_restart_lap_is_a_standing_start_not_an_out_lap(self):
        context = analyse_session(self._restarted(), standing_start=True).for_lap(4)
        self.assertTrue(context.is_standing_start)
        self.assertTrue(context.is_restart)
        self.assertFalse(context.is_out_lap)
        self.assertEqual(context.indicators, ("START",))
        self.assertTrue(context.excluded_from_pace)

    def test_the_restart_says_it_was_a_restart_and_not_the_grid_at_the_start(self):
        analysis = analyse_session(self._restarted(), standing_start=True)
        self.assertIn("restarted from the grid box", analysis.for_lap(4).tooltip)
        self.assertIn("Standing start", analysis.for_lap(1).tooltip)
        self.assertNotIn("Standing start", analysis.for_lap(4).tooltip)

    def test_the_red_flagged_lap_itself_is_marked_red_not_start(self):
        context = analyse_session(self._restarted(), standing_start=True).for_lap(2)
        self.assertEqual(context.indicators, ("RED-FLAG",))
        self.assertFalse(context.is_standing_start)

    def test_a_practice_restart_is_left_to_the_pit_lane_timer(self):
        """Only a session that starts on the grid restarts on it. A practice or qualifying session
        resumes with the field leaving the pit lane, which the stored out-lap flag already says."""
        context = analyse_session(self._restarted(), standing_start=False).for_lap(4)
        self.assertFalse(context.is_standing_start)
        self.assertFalse(context.is_restart)
        self.assertEqual(context.indicators, ())

    def test_the_red_flag_leaves_the_run_whole_and_the_axis_on_real_lap_numbers(self):
        """The point of it all: one run of laps 1-6, so lap 2 is stint lap 2 and the hole left by
        the lap the game skipped sits at stint lap 3, where it happened."""
        analysis = analyse_session(self._restarted(), standing_start=True)
        self.assertEqual(len(analysis.stints), 1)
        stint = analysis.stints[0]
        self.assertEqual([lap.lap_number for lap in stint.laps], [1, 2, 4, 5, 6])
        self.assertEqual([lap.stint_lap for lap in stint.laps], [1, 2, 4, 5, 6])

    def test_the_average_counts_only_the_laps_actually_raced(self):
        analysis = analyse_session(self._restarted(), standing_start=True)
        self.assertEqual(analysis.excluded_laps, frozenset({1, 2, 4}))
        self.assertEqual(stint_average_ms(analysis.stints[0], analysis.excluded_laps), 95590.0)


class OneClassificationTest(unittest.TestCase):
    """The property the split exists for: what the table marks is what the average leaves out."""

    def test_every_excluded_lap_carries_a_chip_and_a_tooltip(self):
        """The property the whole column exists for: an average is readable off the page because no
        lap is ever dropped from it without the table saying so."""
        for standing_start in (True, False):
            with self.subTest(standing_start=standing_start):
                analysis = analyse_session(_race(), standing_start=standing_start)
                for number in analysis.excluded_laps:
                    context = analysis.for_lap(number)
                    with self.subTest(lap=number):
                        self.assertTrue(context.indicators)
                        self.assertIsNotNone(context.tooltip)

    def test_and_the_converse_no_chipped_lap_is_silently_counted(self):
        """The other direction, so the two sets are proved equal rather than merely overlapping."""
        analysis = analyse_session(_race(), standing_start=True)
        for number, context in analysis.by_lap.items():
            with self.subTest(lap=number):
                self.assertEqual(bool(context.indicators), number in analysis.excluded_laps)

    def test_the_average_uses_exactly_the_laps_the_table_leaves_unflagged(self):
        analysis = analyse_session(_race(), standing_start=True)
        stint = next(s for s in analysis.stints if s.first_lap_number == 4)
        counted = [lap.lap_time_ms for lap in stint.laps
                   if lap.lap_number not in analysis.excluded_laps]
        self.assertEqual(counted, [90500, 90800])       # lap 4, the out-lap, is not among them
        self.assertEqual(stint_average_ms(stint, analysis.excluded_laps), 90650.0)

    def test_a_safety_car_run_reports_the_pace_it_actually_ran(self):
        """One Shanghai race's final run averaged 1:55.967 with four safety-car laps in it. The
        laps are still drawn; they just stop standing for the run's pace."""
        laps = [dataclasses.replace(lap, safety_car=int(SafetyCarStatus.FULL))
                if lap.lap_number == 5 else lap for lap in _race()]
        laps = [dataclasses.replace(lap, lap_time_ms=140000) if lap.lap_number == 5 else lap
                for lap in laps]
        analysis = analyse_session(laps, standing_start=True)
        stint = next(s for s in analysis.stints if s.first_lap_number == 4)
        self.assertEqual(stint_average_ms(stint, analysis.excluded_laps), 90800.0)
        self.assertEqual(len(stint.laps), 3)        # all three still drawn, including the SC lap


if __name__ == "__main__":
    unittest.main()
