"""The stint rules behind the session detail's pace and tyre-life charts.

Every fixture here is real: the lap numbers, compounds, wear and times are read out of the project's
own database, and each session is present because it breaks a naive implementation. The comments say
which trap each one carries, so a future change that "simplifies" a rule fails against real data
rather than against an invented case.
"""
import unittest
from math import isnan

from f1telemetry.src.domain.models import Lap, LapTyreContext
from f1telemetry.src.ui.sessions.tyre_stints import (
    in_lap_numbers,
    pace_y_range,
    split_tyre_stints,
    stint_average_label,
    stint_average_ms,
    stint_axis_max,
    stint_series,
)

_S, _M, _H, _I = 16, 17, 18, 7      # visual compounds: soft, medium, hard, intermediate


def _lap(number, compound, wear, ms, age=0, fuel=None):
    """One stored lap. ``wear`` is the worst wheel's %, or a full RL, RR, FL, FR tuple."""
    wheels = wear if isinstance(wear, tuple) else (wear, wear * 0.8, wear * 0.6, wear * 0.4)
    return Lap(lap_number=number, lap_time_ms=ms, sector1_ms=None, sector2_ms=None, sector3_ms=None,
               is_valid=True, fuel_in_tank=fuel,
               tyre_context=LapTyreContext(actual_compound=compound, visual_compound=compound,
                                           age_laps=age, wear=wheels))


def _untyred(number, ms):
    """A lap stored before tyre context was captured - it can't be placed on any set."""
    return Lap(lap_number=number, lap_time_ms=ms, sector1_ms=None, sector2_ms=None, sector3_ms=None,
               is_valid=True, tyre_context=None)


def _session_11708585():
    """A 27-lap race carrying two traps at once.

    ``tyre_age_laps`` runs 0, 2, 2, 4, 4 inside the opening stint - splitting on it gives fourteen
    stints - and lap 21 is a stale in-lap reading that reports the *old* compound at 61% wear, after
    laps 19-20 went missing entirely. The right answer is three stints: M 1-9, H 10-18, M 22-29.
    """
    ages = (0, 2, 2, 4, 4, 5, 6, 7, 9)      # the Car Status snapshot straddling the game's increment
    wear = (9, 15, 21, 27, 33, 39, 45, 51, 57)
    times = (91724, 88152, 89767, 88759, 89815, 90030, 90012, 90326, 93345)
    laps = [_lap(n, _M, w, t, a) for n, (w, t, a) in enumerate(zip(wear, times, ages), start=1)]

    wear = (3, 7, 11, 15, 19, 24, 27, 31, 39)
    times = (107168, 88556, 87455, 88805, 88851, 88526, 89848, 91056, 91382)
    laps += [_lap(n, _H, w, t) for n, (w, t) in enumerate(zip(wear, times), start=10)]

    laps.append(_lap(21, _M, 61, 112199))   # stale: old compound, wear still climbing, no reset

    wear = (3, 8, 14, 19, 24, 29, 34, 39)
    times = (107636, 88282, 87723, 88067, 89150, 88814, 89367, 89233)
    laps += [_lap(n, _M, w, t) for n, (w, t) in enumerate(zip(wear, times), start=22)]
    return laps


def _session_14435457():
    """A 29-lap, two-stop race - the clean three-stint case, and both out-laps are large.

    Stint 2 opens at 119.594 s against an 82.7 s median (+36.9 s) and stint 3 at 96.528 s (+14.7 s).
    """
    laps = [_lap(1, _M, 6.01, 90518), _lap(2, _M, 12.10, 91701)]
    wear = (0.00, 2.88, 5.65, 8.78, 11.83, 14.77, 17.69, 20.89, 24.03,
            27.06, 30.10, 33.15, 36.24, 39.34, 42.47, 45.37, 48.57, 51.63)
    times = (119594, 87341, 82005, 81852, 81971, 82306, 82430, 82056, 82180,
             82994, 83450, 83234, 82839, 82737, 82737, 83334, 82870, 83031)
    laps += [_lap(n, _H, w, t) for n, (w, t) in enumerate(zip(wear, times), start=3)]
    wear = (0.00, 3.32, 7.05, 10.73, 14.73, 18.37, 22.29, 26.09, 30.64)
    times = (96528, 86778, 80780, 81539, 81184, 82110, 81613, 82114, 81829)
    laps += [_lap(n, _M, w, t) for n, (w, t) in enumerate(zip(wear, times), start=21)]
    return laps


def _session_12316788():
    """A race whose opening stint is one lap, then a hole at lap 3.

    The reason the out-lap flag must be read from the *unfiltered* ordinal: the minimum-laps rule
    removes lap 1's stint, and the 170.8 s lap behind it is a post-pit out-lap, not a race start.
    """
    return [
        _lap(1, _M, 6.75, 99971),
        _lap(2, _M, 2.32, 170826),      # wear resets - a new set - and this lap carries the stop
        # lap 3 was never stored
        _lap(4, _M, 6.79, 99308), _lap(5, _M, 11.48, 95745), _lap(6, _M, 16.09, 95435),
        _lap(7, _M, 20.81, 96316), _lap(8, _M, 25.34, 95980), _lap(9, _M, 30.94, 96710),
        _lap(10, _M, 35.74, 96725),
    ]


def _session_13974110():
    """A practice session whose second stint starts on a *used* set (9.38% worn, not ~0)."""
    wear = (4.97, 8.96, 12.86, 17.36, 20.83, 28.59, 37.39)
    times = (97552, 96373, 96629, 108097, 97930, 100473, 100162)
    laps = [_lap(n, _H, w, t) for n, (w, t) in enumerate(zip(wear, times), start=1)]
    laps += [_lap(8, _S, 9.38, 97781), _lap(9, _S, 16.40, 99363)]       # used set, wear climbs on
    laps += [_lap(10, _I, 11.66, 111516), _lap(11, _I, 16.85, 110526)]
    laps.append(_lap(12, _S, 38.15, 100290))    # one lap on a set already run - below the minimum
    return laps


class TestSplitTyreStints(unittest.TestCase):

    def test_splits_on_wear_dropping_and_on_the_compound_changing(self):
        stints = split_tyre_stints(_session_11708585())
        self.assertEqual([(s.first_lap_number, s.last_lap_number) for s in stints],
                         [(1, 9), (10, 18), (22, 29)])
        self.assertEqual([s.visual_compound for s in stints], [_M, _H, _M])

    def test_age_jumping_and_repeating_does_not_split_a_stint(self):
        """Laps 1-9 report ages 0, 2, 2, 4, 4, 5, 6, 7, 9 and are one set of mediums throughout."""
        stints = split_tyre_stints(_session_11708585())
        self.assertEqual(stints[0].lap_count, 9)

    def test_a_stale_in_lap_reading_is_dropped_by_the_minimum(self):
        """Lap 21 reports the old compound at 61% wear; it belongs to no stint the driver ran."""
        stints = split_tyre_stints(_session_11708585())
        placed = {lap.lap_number for stint in stints for lap in stint.laps}
        self.assertNotIn(21, placed)

    def test_two_stints_on_the_same_compound_still_split_on_the_wear_drop(self):
        """Laps 21 -> 22 are both medium; only the wear reset says a new set went on."""
        stints = split_tyre_stints(_session_11708585())
        self.assertEqual(stints[2].first_lap_number, 22)
        self.assertEqual(stints[2].visual_compound, _M)

    def test_minimum_two_laps_is_what_drops_the_artefact(self):
        laps = _session_11708585()
        self.assertEqual(len(split_tyre_stints(laps)), 3)
        self.assertEqual(len(split_tyre_stints(laps, min_laps=1)), 4)   # the artefact reappears

    def test_a_stint_starting_on_a_used_set_is_still_a_stint(self):
        stints = split_tyre_stints(_session_13974110())
        self.assertEqual([(s.first_lap_number, s.last_lap_number) for s in stints],
                         [(1, 7), (8, 9), (10, 11)])
        self.assertAlmostEqual(stints[1].laps[0].tyre_life, 100 - 9.38, places=2)

    def test_tyre_life_is_the_worst_wheel_not_the_first_and_not_the_mean(self):
        """Real row: the worst corner is RR, so neither RL nor the mean gives the right answer."""
        laps = [_lap(1, _M, (8.21, 9.93, 5.43, 6.45), 94701),
                _lap(2, _M, (12.67, 14.65, 8.54, 9.75), 94466)]
        life = split_tyre_stints(laps)[0].laps[0].tyre_life
        self.assertAlmostEqual(life, 100 - 9.93, places=2)

    def test_equal_wear_is_not_a_drop(self):
        """A Time Trial pair whose worst wheel reads 4.5 both laps - the -0.0 float artefact."""
        laps = [_lap(1, _S, (4.5, 3.78, 3.75, 2.7), 78233),
                _lap(2, _S, (4.5, 3.52, 3.97, 2.62), 78273)]
        self.assertEqual(len(split_tyre_stints(laps)), 1)

    def test_the_three_stint_race_matches_its_classification(self):
        stints = split_tyre_stints(_session_14435457())
        self.assertEqual([(s.first_lap_number, s.last_lap_number) for s in stints],
                         [(1, 2), (3, 20), (21, 29)])

    def test_laps_with_no_tyre_context_are_skipped(self):
        laps = [_lap(1, _M, 5, 90000), _untyred(2, 90100), _lap(3, _M, 12, 90200)]
        stints = split_tyre_stints(laps)
        self.assertEqual([lap.lap_number for lap in stints[0].laps], [1, 3])

    def test_no_laps_gives_no_stints(self):
        self.assertEqual(split_tyre_stints([]), ())

    def test_a_fresh_set_of_the_same_compound_splits_on_the_age_reset(self):
        """Jeddah P1 (10198131…): a tyre-saving practice programme on softs, then a qualifying
        simulation on a fresh set of the same compound. The new set's first reading is *higher* than
        the old set's last, so the compound is unchanged and wear never drops - the age counter
        falling is the only thing that says a new set went on.
        """
        laps = [_lap(1, _S, 9.51, 94781, age=0),
                _lap(2, _S, 15.92, 96212, age=1),
                _lap(3, _S, 17.97, 92696, age=0)]   # fresh set, and wear reads higher, not lower
        stints = split_tyre_stints(laps, min_laps=1)
        self.assertEqual([(s.first_lap_number, s.last_lap_number) for s in stints],
                         [(1, 2), (3, 3)])

    def test_the_one_lap_programme_is_dropped_rather_than_folded_into_the_run_before_it(self):
        """The same session at the real minimum. The one-lap qualifying sim can't be charted, but it
        is no longer absorbed into the tyre-saving run as though one set had worn 9.51 -> 17.97.
        """
        laps = [_lap(1, _S, 9.51, 94781, age=0),
                _lap(2, _S, 15.92, 96212, age=1),
                _lap(3, _S, 17.97, 92696, age=0)]
        stints = split_tyre_stints(laps)
        self.assertEqual(len(stints), 1)
        self.assertEqual([lap.lap_number for lap in stints[0].laps], [1, 2])

    def test_a_run_opening_on_a_flying_lap_is_not_called_an_out_lap(self):
        """Suzuka P1: the second run's first stored lap is 1:33.219, quicker than either lap of the
        first. The real out-lap was never stored, so this is a flying lap - and the quickest of the
        session."""
        laps = [_lap(1, _S, 9.93, 94701, age=0), _lap(2, _S, 14.65, 94466, age=1),
                _lap(3, _S, 7.76, 93219, age=0), _lap(4, _S, 18.71, 100483, age=1)]
        stints = split_tyre_stints(laps)
        self.assertEqual(len(stints), 2)
        self.assertTrue(stints[1].follows_pit)              # it does follow a stop
        self.assertFalse(stints[1].laps[0].is_out_lap)      # but it is not an out-lap

    def test_a_race_out_lap_is_still_flagged(self):
        laps = [_lap(1, _M, 5, 90000), _lap(2, _M, 10, 90500),
                _lap(3, _H, 1, 125000), _lap(4, _H, 5, 89500), _lap(5, _H, 9, 89800)]
        self.assertTrue(split_tyre_stints(laps)[1].laps[0].is_out_lap)


class TestStintRelativeAxis(unittest.TestCase):

    def test_every_stint_starts_at_stint_lap_one(self):
        for session in (_session_11708585(), _session_14435457(), _session_13974110()):
            for stint in split_tyre_stints(session):
                with self.subTest(stint=stint.index, first=stint.first_lap_number):
                    self.assertEqual(stint.laps[0].stint_lap, 1)

    def test_the_axis_runs_to_the_longest_stint(self):
        self.assertEqual(stint_axis_max(split_tyre_stints(_session_14435457())), 18)
        self.assertEqual(stint_axis_max(split_tyre_stints(_session_11708585())), 9)

    def test_no_stints_still_gives_a_usable_axis(self):
        self.assertEqual(stint_axis_max(()), 1)

    def test_offsets_come_from_lap_numbers_not_list_position(self):
        """Stint 3 of 11708585… starts at lap 22, so its laps must read 1-8, not 22-29."""
        stint = split_tyre_stints(_session_11708585())[2]
        self.assertEqual([lap.stint_lap for lap in stint.laps], [1, 2, 3, 4, 5, 6, 7, 8])

    def test_a_gap_inside_a_stint_stays_a_gap(self):
        """Lap 3 was never stored, so stint lap 2 is a hole - laps 4+ must not shift down into it."""
        stint = split_tyre_stints(_session_12316788())[0]
        self.assertEqual([lap.stint_lap for lap in stint.laps], [1, 3, 4, 5, 6, 7, 8, 9])
        self.assertEqual(stint.lap_count, 8)
        self.assertEqual(stint.axis_span, 9)        # the span counts the missing lap

    def test_stint_series_leaves_nan_in_the_hole(self):
        stint = split_tyre_stints(_session_12316788())[0]
        xs, ys = stint_series(stint, lambda lap: lap.tyre_life)
        self.assertEqual(xs, [float(n) for n in range(1, 10)])
        self.assertTrue(isnan(ys[1]))                                   # stint lap 2: no such lap
        self.assertEqual([i for i, y in enumerate(ys) if isnan(y)], [1])

    def test_stint_series_can_skip_a_lap_that_is_drawn_separately(self):
        """The pace chart pulls the out-lap off the line and draws it as its own clipped marker."""
        stint = split_tyre_stints(_session_12316788())[0]
        _, ys = stint_series(stint, lambda lap: lap.lap_time_ms, skip=lambda lap: lap.is_out_lap)
        self.assertTrue(isnan(ys[0]))
        self.assertEqual(ys[2], 99308)


class TestPaceYRange(unittest.TestCase):

    def test_stint_one_lap_one_sets_the_range_like_any_other_lap(self):
        """A race start is a real racing lap - a couple of seconds slow, not a pit out-lap."""
        laps = [_lap(1, _M, 5, 95000), _lap(2, _M, 10, 90000), _lap(3, _M, 15, 90500)]
        _, high = pace_y_range(split_tyre_stints(laps))
        self.assertGreater(high, 95000)

    def test_a_dropped_opening_stint_does_not_promote_the_next_to_race_start(self):
        """12316788…: reading the flag after the minimum-laps filter would call a 170.8 s post-pit
        lap a race start and stretch the axis from about 4 s to about 75 s."""
        stints = split_tyre_stints(_session_12316788())
        self.assertEqual(len(stints), 1)
        self.assertTrue(stints[0].follows_pit)
        self.assertTrue(stints[0].laps[0].is_out_lap)
        low, high = pace_y_range(stints)
        self.assertLess((high - low) / 1000.0, 10.0)

    def test_the_race_start_is_flagged_differently_from_the_pit_out_laps(self):
        stints = split_tyre_stints(_session_14435457())
        self.assertEqual([stint.follows_pit for stint in stints], [False, True, True])
        self.assertEqual([stint.laps[0].is_out_lap for stint in stints], [False, True, True])

    def test_the_two_stop_race_keeps_a_readable_spread(self):
        """Both out-laps out, 14435457… spans about 12 s rather than the 39 s they would force."""
        low, high = pace_y_range(split_tyre_stints(_session_14435457()))
        self.assertLess((high - low) / 1000.0, 15.0)
        self.assertLess(high / 1000.0, 96.0)        # below the 96.528 s stint-3 out-lap

    def test_a_single_stint_with_no_pit_stop_still_gets_a_range(self):
        laps = [_lap(n, _M, n * 4, 90000 + n * 200) for n in range(1, 8)]
        low, high = pace_y_range(split_tyre_stints(laps))
        self.assertLess(low, high)

    def test_near_identical_laps_still_get_a_span(self):
        laps = [_lap(1, _M, 5, 90000), _lap(2, _M, 10, 90000)]
        low, high = pace_y_range(split_tyre_stints(laps))
        self.assertLess(low, high)

    def test_no_stints_has_no_range(self):
        self.assertIsNone(pace_y_range(()))

    def test_the_range_is_capped_so_one_wild_lap_cannot_flatten_it(self):
        """An incident lap is a real lap, but it is not what the chart is for - and no rule can
        classify it, which is why the cap exists alongside the pit-lap exclusions."""
        laps = [_lap(n, _M, n * 3, 96000) for n in range(1, 6)]
        laps.append(_lap(6, _M, 20, 122000))        # spin, damage, traffic - genuine, and wild
        low, high = pace_y_range(split_tyre_stints(laps))
        self.assertLessEqual(high - low, 9000)      # the 8 s window plus its padding

    def test_the_cap_is_anchored_at_the_fastest_lap(self):
        """The fastest lap is what every other lap is read against, so it must never clip."""
        laps = [_lap(1, _M, 5, 90000), _lap(2, _M, 10, 91000), _lap(3, _M, 15, 130000)]
        low, high = pace_y_range(split_tyre_stints(laps))
        self.assertLess(low, 90000)
        self.assertLess(high, 100000)

    def test_padding_is_taken_from_the_capped_span_not_the_raw_one(self):
        """From the raw span a 40 s spread pads by 2 s, burning a quarter of the window on dead air
        below the fastest lap before a single degradation point is drawn."""
        laps = [_lap(1, _M, 5, 90000), _lap(2, _M, 10, 91000), _lap(3, _M, 15, 130000)]
        low, _ = pace_y_range(split_tyre_stints(laps))
        self.assertGreater(low, 90000 - 600)        # ~5% of 8 s, not ~5% of 40 s

    def test_the_cap_can_be_lifted(self):
        laps = [_lap(1, _M, 5, 90000), _lap(2, _M, 10, 91000), _lap(3, _M, 15, 130000)]
        _, high = pace_y_range(split_tyre_stints(laps), span_ms=None)
        self.assertGreater(high, 130000)

    def test_the_window_is_always_the_same_height(self):
        tight = [_lap(n, _M, n * 3, 90000 + n * 100) for n in range(1, 6)]    # 0.4 s of spread
        wide = [_lap(n, _M, n * 3, 90000 + n * 2000) for n in range(1, 6)]    # 8 s of spread
        for label, laps in (("tight", tight), ("wide", wide)):
            with self.subTest(spread=label):
                low, high = pace_y_range(split_tyre_stints(laps))
                self.assertAlmostEqual(high - low, 8000.0, places=6)

    def test_near_identical_laps_are_not_magnified(self):
        """0.3 s of spread must read as 0.3 s. Fitted to the data it filled the plot and made laps
        that were effectively identical look like a fall-off."""
        laps = [_lap(1, _M, 5, 90000), _lap(2, _M, 10, 90150), _lap(3, _M, 15, 90300)]
        low, high = pace_y_range(split_tyre_stints(laps))
        self.assertLess(300 / (high - low), 0.05)

    def test_the_window_sits_just_under_the_quickest_lap_not_centred_on_it(self):
        laps = [_lap(1, _M, 5, 95000), _lap(2, _M, 10, 90000), _lap(3, _M, 15, 90500)]
        low, high = pace_y_range(split_tyre_stints(laps))
        self.assertLess(low, 90000)
        self.assertGreater(low, 90000 - 8000 * 0.5)     # just under; centring wastes half the plot
        self.assertGreater(high, 95000)

    def test_no_lap_can_fall_below_the_window(self):
        """Suzuka P1: the quickest lap of the session is a run's first stored lap. Anchoring above
        it dropped it off the bottom of the plot, line and all."""
        laps = [_lap(1, _S, 9.93, 94701, age=0), _lap(2, _S, 14.65, 94466, age=1),
                _lap(3, _S, 7.76, 93219, age=0), _lap(4, _S, 18.71, 100483, age=1)]
        stints = split_tyre_stints(laps)
        low, _ = pace_y_range(stints)
        for stint in stints:
            for lap in stint.laps:
                with self.subTest(lap=lap.lap_number):
                    self.assertGreaterEqual(lap.lap_time_ms, low)


class TestInLapNumbers(unittest.TestCase):

    def test_a_stint_ending_right_before_the_next_gives_an_in_lap(self):
        self.assertEqual(in_lap_numbers(split_tyre_stints(_session_14435457())), frozenset({2, 20}))

    def test_a_gap_before_the_next_stint_is_not_claimed_as_an_in_lap(self):
        """11708585…: stint 2's last stored lap is 18, but the next opens at 22 — laps 19-20 are
        missing and 21 was a stale artefact, so lap 18 is not the lap into the pits."""
        self.assertEqual(in_lap_numbers(split_tyre_stints(_session_11708585())), frozenset({9}))

    def test_the_final_stint_has_no_in_lap(self):
        stints = split_tyre_stints(_session_14435457())
        self.assertNotIn(stints[-1].last_lap_number, in_lap_numbers(stints))

    def test_no_stints_no_in_laps(self):
        self.assertEqual(in_lap_numbers(()), frozenset())


class TestGarageReturns(unittest.TestCase):
    """Fuel separates a *run* from a *set*: one set can do several runs, and two fresh sets can do
    one lap each. Every fixture here is real, read out of the sessions named."""

    def test_two_fresh_sets_of_the_same_compound_split_on_the_fuel_load(self):
        """Shanghai Q3 (12303182…): two new sets of softs, one lap each. Both report age 0, the same
        compound, and wear that rises rather than resets — only the fuel shows the garage visit,
        -0.01 kg where a lap costs 1.2."""
        laps = [_lap(1, _S, 5.13, 93606, age=0, fuel=3.7992),
                _lap(2, _S, 5.50, 93309, age=0, fuel=3.7846)]
        stints = split_tyre_stints(laps, min_laps=1)
        self.assertEqual([(s.first_lap_number, s.last_lap_number) for s in stints], [(1, 1), (2, 2)])

    def test_two_one_lap_runs_are_not_charted_at_all(self):
        """The honest outcome for that session: no chart, rather than one line through two sets."""
        laps = [_lap(1, _S, 5.13, 93606, age=0, fuel=3.7992),
                _lap(2, _S, 5.50, 93309, age=0, fuel=3.7846)]
        self.assertEqual(split_tyre_stints(laps), ())

    def test_a_normal_lap_of_fuel_burn_is_not_a_garage_return(self):
        """Suzuka Q1 (17491710…), full wets, one run of three laps: -1.32 and -1.31 kg."""
        laps = [_lap(1, 8, 2.41, 109182, age=0, fuel=5.8469),
                _lap(2, 8, 4.19, 108525, age=1, fuel=4.5268),
                _lap(3, 8, 5.84, 106242, age=2, fuel=3.2184)]
        stints = split_tyre_stints(laps)
        self.assertEqual([(s.first_lap_number, s.last_lap_number) for s in stints], [(1, 3)])

    def test_a_refuel_between_runs_on_one_set_splits_them(self):
        """Suzuka Q2 (3113777…): laps 1-3 one run, lap 4 a second run on the same set of inters.
        The tyres say nothing — age climbs 0,1,2,3 and wear rises throughout — but fuel goes +1.65."""
        laps = [_lap(1, 7, 1.90, 108785, age=0, fuel=5.7675),
                _lap(2, 7, 2.87, 105374, age=1, fuel=4.4409),
                _lap(3, 7, 3.93, 105432, age=2, fuel=3.1069),
                _lap(4, 7, 6.95, 104722, age=3, fuel=4.7520)]
        stints = split_tyre_stints(laps, min_laps=1)
        self.assertEqual([(s.first_lap_number, s.last_lap_number) for s in stints], [(1, 3), (4, 4)])

    def test_a_missing_fuel_reading_is_never_a_garage_return(self):
        laps = [_lap(1, _M, 5, 90000), _lap(2, _M, 10, 90500)]      # fuel None on both
        self.assertEqual(len(split_tyre_stints(laps)), 1)


class TestStintAverage(unittest.TestCase):
    """The corrected per-stint average shown in each chart's legend entry.

    Every number here comes from the same real fixtures as the rules above, so a "simplification"
    that drops an exclusion fails against a real race rather than an invented one.
    """

    def _stints(self, laps):
        stints = split_tyre_stints(laps)
        return stints, in_lap_numbers(stints)

    def test_excludes_the_standing_start_and_the_in_lap(self):
        """``11708585...`` stint 1: lap 1 starts from the grid box, lap 9 is the lap into the pits.

        Both in one stint, and both slow for reasons that have nothing to do with the tyres - the
        uncorrected mean is 1:30.214, two thirds of a second adrift.
        """
        stints, in_laps = self._stints(_session_11708585())
        average = stint_average_ms(stints[0], in_laps, standing_start=True)
        self.assertAlmostEqual(average, 89551.571, places=2)
        self.assertEqual(stint_average_label(stints[0], in_laps, standing_start=True), "1:29.552")

    def test_excludes_the_out_lap(self):
        """``14435457...`` stint 2 opens at 119.594 s against an 82.7 s median.

        Left in, the average reads 1:24.942 - a run that never ran a lap anywhere near it.
        """
        stints, in_laps = self._stints(_session_14435457())
        self.assertEqual(stint_average_label(stints[1], in_laps, standing_start=True), "1:22.896")

    def test_a_stint_of_nothing_but_a_start_and_a_stop_has_no_average(self):
        """``14435457...`` stint 1 is lap 1 (standing start) and lap 2 (in-lap) and nothing else.

        The honest answer is "no pace to report", not the mean of the two laps that were about
        something else - and the label says so out loud rather than leaving a blank.
        """
        stints, in_laps = self._stints(_session_14435457())
        self.assertIsNone(stint_average_ms(stints[0], in_laps, standing_start=True))
        self.assertEqual(stint_average_label(stints[0], in_laps, standing_start=True), "\u2014")

    def test_the_standing_start_rule_is_race_only(self):
        """``13974110...`` is practice: its lap 1 is a flying lap and counts.

        Only the in-lap (7) comes out, which is why the flag is passed in rather than assumed -
        a practice session's opening lap is often one of its quickest.
        """
        stints, in_laps = self._stints(_session_13974110())
        self.assertEqual(stint_average_label(stints[0], in_laps, standing_start=False), "1:39.509")
        # The same laps read as a race would drop lap 1 as well - the flag is doing the work.
        self.assertEqual(stint_average_label(stints[0], in_laps, standing_start=True), "1:39.900")

    def test_a_removed_artefact_stint_cannot_promote_an_out_lap_to_a_race_start(self):
        """``12316788...``: the 170.8 s lap 2 is an out-lap, and the standing-start rule (lap 1)
        must not reach it - lap 1 belongs to the single-lap stint the minimum-laps rule removed."""
        stints, in_laps = self._stints(_session_12316788())
        self.assertEqual(stint_average_label(stints[0], in_laps, standing_start=True), "1:36.603")

    def test_a_hole_inside_a_stint_does_not_poison_the_average(self):
        """``11708585...`` stint 2 runs 10-18 with the out-lap at 10; nothing is invented for the
        laps that were never stored."""
        stints, in_laps = self._stints(_session_11708585())
        self.assertEqual(stint_average_label(stints[1], in_laps, standing_start=True), "1:29.310")

    def test_untimed_laps_are_ignored_and_the_result_is_a_lap_time(self):
        """A lap the game never timed contributes nothing - it is not a zero."""
        laps = [_lap(1, _M, 2.0, 90000), _lap(2, _M, 4.0, None),
                _lap(3, _M, 6.0, 92000), _lap(4, _M, 8.0, 94000)]
        stints, in_laps = self._stints(laps)
        self.assertEqual(stint_average_ms(stints[0], in_laps), 92000.0)
        self.assertEqual(stint_average_label(stints[0], in_laps), "1:32.000")

    def test_no_in_laps_and_no_flag_is_the_plain_mean(self):
        """The defaults have to be the uncorrected answer, so a caller that forgets an argument
        gets something wrong-but-obvious rather than something subtly filtered."""
        laps = [_lap(1, _M, 2.0, 90000), _lap(2, _M, 4.0, 92000)]
        stints = split_tyre_stints(laps)
        self.assertEqual(stint_average_ms(stints[0]), 91000.0)

    def test_a_half_millisecond_mean_rounds_up_not_to_even(self):
        """Two laps a millisecond apart average to a half-millisecond, and ``round`` is banker's:
        it would print 1:33.786 where the DB average of 93.7865 s reads 1:33.787 everywhere else."""
        laps = [_lap(1, _M, 2.0, 93786), _lap(2, _M, 4.0, 93787)]
        stints = split_tyre_stints(laps)
        self.assertEqual(stint_average_ms(stints[0]), 93786.5)
        self.assertEqual(stint_average_label(stints[0]), "1:33.787")


if __name__ == "__main__":
    unittest.main()
