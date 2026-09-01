"""The Race control box's penalty rules, against the penalties the real captures produced.

Every fixture here is a row read out of a scratch re-ingest of all 33 captures - the vehicle
indices, types, laps and the None/0 split are what the game actually sent - and each session is
present because it carries a case the wording has to survive. The comments say which.
"""
import unittest

from f1telemetry.src.domain.models import ClassificationEntry, SessionPenalty
from f1telemetry.src.protocol.enums import ResultReason, ResultStatus
from f1telemetry.src.ui.sessions.race_control import(
    PenaltySummary,
    grid_penalty_places,
    summarise_penalties,
)


def _entry(vehicle_index, name, *, is_ai=True, is_player=False, position=1,
           num_penalties=0, penalties_time_s=0, nationality_id=1):
    return ClassificationEntry(
        vehicle_index=vehicle_index, position=position, driver_name=name, team_id=1,
        race_number=1, nationality_id=nationality_id, is_player=is_player,
        grid_position=position, points=0,
        num_laps=0, num_pit_stops=0, best_lap_time_ms=0, best_lap_num=0, total_race_time_s=0.0,
        penalties_time_s=penalties_time_s, num_penalties=num_penalties,
        result_status=ResultStatus.FINISHED, result_reason=ResultReason.INVALID, is_ai=is_ai)

def _penalty(vehicle_index, penalty_type, infringement_type, lap_number, *,
             time_s=None, places_gained=None, frame=1, other=None):
    return SessionPenalty(vehicle_index=vehicle_index, penalty_type=penalty_type,
                          infringement_type=infringement_type, lap_number=lap_number,
                          other_vehicle_index=other, time_s=time_s, places_gained=places_gained,
                          frame=frame)


# --- 12754185... (Grand Prix '23 Q2): a grid penalty, a retirement and a warning, in three rows.
# The whole type mix in one session, and the only one of these three the classification counts is
# the grid penalty.
_Q2_ENTRIES = (
    _entry(7, "Isack Hadjar", position=3),
    _entry(1, "Fernando Alonso", position=8),
    _entry(15, "LECLERC", is_ai=False, is_player=True, position=1),
)
_Q2_PENALTIES = (
    _penalty(7, 2, 4, 1, places_gained=5, frame=3014),      # Grid penalty, Small Collision
    _penalty(1, 16, 42, 2, frame=2954),                     # Retired, Retired terminally damaged
    _penalty(15, 5, 17, 2, places_gained=0, frame=6684),    # Warning, Pit lane speeding
)


class PenaltyRowTextTests(unittest.TestCase):
    """What one penalty reads as, for each of the four kinds the captures contain."""

    def test_the_three_kinds_of_row_split_into_what_and_why(self):
        """Two columns, not one string: the outcome stays narrow and the reason takes the slack."""
        rows = summarise_penalties(_Q2_PENALTIES, _Q2_ENTRIES).rows
        self.assertEqual([(row.outcome, row.reason) for row in rows], [
            ("Grid penalty, 5 places", "Small Collision"),
            ("Retired", "terminally damaged"),
            ("Warning", "Pit lane speeding"),
        ])

    def test_a_retirement_does_not_say_retired_twice(self):
        """``Retired`` + ``Retired terminally damaged`` verbatim is one statement made twice. The
        rule is a prefix test, not a table of pairs, so the whole retirement family is covered."""
        rows = summarise_penalties(_Q2_PENALTIES, _Q2_ENTRIES).rows
        self.assertEqual((rows[1].outcome, rows[1].reason), ("Retired", "terminally damaged"))
        mechanical = summarise_penalties((_penalty(4, 16, 41, 4),)).rows[0]
        self.assertEqual((mechanical.outcome, mechanical.reason),
                         ("Retired", "mechanical failure"))

    def test_an_invalidation_drops_without_reason_and_keeps_the_reason(self):
        """15062953... (career P2) invalidates a lap for corner cutting. Verbatim the game says
        "This lap invalidated without reason" - beside the reason it printed, which is a denial of
        the rest of its own row."""
        rows = summarise_penalties((_penalty(21, 12, 7, 6, frame=15711),)).rows
        self.assertEqual((rows[0].outcome, rows[0].reason),
                         ("This lap invalidated", "Corner cutting gained time"))

    def test_the_two_lap_invalidation_keeps_the_laps_it_names(self):
        """10198131... (Jeddah P1). Only the trailing clause goes; "This and next" is the fact."""
        rows = summarise_penalties((_penalty(21, 13, 28, 3),)).rows
        self.assertEqual(
            (rows[0].outcome, rows[0].reason),
            ("This and next lap invalidated", "Corner cutting ran wide gained time significant"))

    def test_an_added_time_rides_on_the_penalty_it_belongs_to(self):
        """15888071... (career race): the 3 s the classification also reports as +3s."""
        rows = summarise_penalties((_penalty(21, 4, 21, 4, time_s=3, places_gained=0, frame=0),)).rows
        self.assertEqual((rows[0].outcome, rows[0].reason),
                         ("Time penalty, +3 s", "Multiple warnings"))

    def test_one_place_is_singular(self):
        """Not in the captures - every grid penalty here costs 5 - but the string is built, so the
        arithmetic that builds it is tested rather than left to be discovered."""
        rows = summarise_penalties((_penalty(7, 2, 4, 1, places_gained=1),)).rows
        self.assertEqual(rows[0].outcome, "Grid penalty, 1 place")

    def test_an_unknown_type_keeps_the_reference_placeholder(self):
        """A game newer than our tables must render something honest, not blank."""
        rows = summarise_penalties((_penalty(3, 99, 98, 2),)).rows
        self.assertEqual((rows[0].outcome, rows[0].reason),
                         ("Unknown penalty (99)", "Unknown infringement (98)"))


class PlacesAndTimeTests(unittest.TestCase):
    """``places_gained = 0`` and ``places_gained = None`` are different facts and must stay so."""

    def test_neither_none_nor_zero_puts_a_clause_on_the_row(self):
        """75 of 129 rows carry 0 and 47 carry None. Either as a clause would fill the box with
        "0 places" on a warning that never involved a position."""
        zero = summarise_penalties((_penalty(15, 5, 17, 2, places_gained=0),)).rows[0]
        none = summarise_penalties((_penalty(1, 16, 41, 4, places_gained=None),)).rows[0]
        self.assertEqual(zero.outcome, "Warning")
        self.assertEqual(none.outcome, "Retired")

    def test_the_tooltip_spells_both_out_and_never_merges_them(self):
        zero = summarise_penalties((_penalty(15, 5, 17, 2, places_gained=0),)).rows[0]
        none = summarise_penalties((_penalty(1, 16, 41, 4, places_gained=None),)).rows[0]
        self.assertIn("Places gained: 0", zero.tooltip)
        self.assertIn("Places gained: not applicable", none.tooltip)
        self.assertIn("Added time: not applicable", zero.tooltip)

    def test_the_tooltip_keeps_the_game_s_own_wording_for_a_row_the_display_tidied(self):
        """The row is where the wording is made to read; nothing tidied there is lost here."""
        row = summarise_penalties((_penalty(21, 12, 7, 6),), (_entry(21, "Kevin Fust",
                                                                    is_ai=False),)).rows[0]
        self.assertEqual(row.tooltip, "\n".join((
            "Lap 6 · Kevin Fust",
            "This lap invalidated without reason — Corner cutting gained time",
            "Other car: not applicable",
            "Places gained: not applicable",
            "Added time: not applicable",
            "Counted towards the classification: no",
        )))

    def test_a_time_penalty_states_its_seconds_in_the_tooltip_too(self):
        row = summarise_penalties((_penalty(21, 4, 21, 4, time_s=3, places_gained=0),)).rows[0]
        self.assertIn("Added time: 3 s", row.tooltip)
        self.assertIn("Places gained: 0", row.tooltip)
        self.assertIn("Counted towards the classification: yes", row.tooltip)


class DriverJoinTests(unittest.TestCase):
    """Naming the car a penalty belongs to, and saying which of them is a person."""

    def test_every_row_is_named_from_the_classification_by_vehicle_index(self):
        rows = summarise_penalties(_Q2_PENALTIES, _Q2_ENTRIES).rows
        self.assertEqual([row.driver for row in rows],
                         ["Isack Hadjar", "Fernando Alonso", "LECLERC"])

    def test_a_car_with_no_classification_entry_still_gets_a_row(self):
        """0 of 129 rows need this, and dropping the row instead would be the silent loss the
        whole feature exists to undo."""
        rows = summarise_penalties((_penalty(14, 5, 4, 3),), _Q2_ENTRIES).rows
        self.assertEqual(rows[0].driver, "Car 14")
        self.assertFalse(rows[0].is_human)

    def test_a_blank_shown_name_falls_back_rather_than_rendering_an_empty_cell(self):
        rows = summarise_penalties((_penalty(9, 5, 4, 1),), (_entry(9, "  "),)).rows
        self.assertEqual(rows[0].driver, "Car 9")

    def test_humans_are_marked_and_ai_cars_are_not(self):
        """972807263... (league Q1): Fabibyte's rows are a person's, the Alonso and Sainz rows are
        the game's. ``is_ai`` comes off the Participants packet, so a league whose members hide
        their online names still marks them - the name is what privacy costs, not this."""
        entries = (_entry(9, "Carlos Sainz"), _entry(13, "Fernando Alonso"),
                   _entry(21, "Fabibyte", is_ai=False))
        penalties = (_penalty(9, 2, 0, 2, places_gained=5),
                     _penalty(13, 2, 0, 2, places_gained=5),
                     _penalty(21, 5, 7, 3, places_gained=0),
                     _penalty(21, 2, 4, 3, places_gained=5))
        rows = summarise_penalties(penalties, entries).rows
        self.assertEqual([row.is_human for row in rows], [False, False, True, True])

    def test_a_privacy_on_league_row_is_still_marked_human(self):
        """11708585... (Online Custom race): every human in the lobby reads "Player". The bold is
        the only thing left that says this row is not an AI's."""
        rows = summarise_penalties((_penalty(3, 5, 4, 1, places_gained=0),),
                                   (_entry(3, "Player", is_ai=False),)).rows
        self.assertEqual(rows[0].driver, "Player")
        self.assertTrue(rows[0].is_human)


class OtherCarTests(unittest.TestCase):
    """The second car in an incident, named from the same index the row's own driver comes from."""

    def test_a_collision_names_the_other_car(self):
        """12316788... lap 1: the game files one collision as two rows, one per car, each naming
        the other. ``other_vehicle_index`` is set on 44 of 44 Small Collisions."""
        entries = (_entry(21, "Kevin Fust", is_ai=False, is_player=True),
                   _entry(3, "Andra-Kimi Antonelli", position=6))
        rows = summarise_penalties((_penalty(21, 5, 4, 1, places_gained=0, other=3),
                                    _penalty(3, 5, 4, 1, places_gained=0, other=21)), entries).rows
        self.assertEqual([row.reason for row in rows],
                         ["Small Collision with Andra-Kimi Antonelli",
                          "Small Collision with Kevin Fust"])

    def test_a_reason_with_no_other_car_is_left_alone(self):
        """No infringement test decides this - the packet's own 255 sentinel does, and it is absent
        on all 81 rows that are not a collision or a blocking call."""
        row = summarise_penalties((_penalty(21, 5, 17, 2, places_gained=0),)).rows[0]
        self.assertEqual(row.reason, "Pit lane speeding")

    def test_an_unresolvable_other_car_falls_back_the_same_way_the_driver_does(self):
        row = summarise_penalties((_penalty(21, 5, 4, 1, other=9),),
                                  (_entry(21, "Kevin Fust", is_ai=False),)).rows[0]
        self.assertEqual(row.reason, "Small Collision with Car 9")

    def test_the_tooltip_names_the_other_car_too(self):
        entries = (_entry(21, "Kevin Fust", is_ai=False), _entry(3, "Andra-Kimi Antonelli"))
        row = summarise_penalties((_penalty(21, 5, 4, 1, places_gained=0, other=3),), entries).rows[0]
        self.assertIn("Other car: Andra-Kimi Antonelli", row.tooltip)

    def test_the_row_carries_the_nationality_the_flag_needs(self):
        rows = summarise_penalties((_penalty(21, 5, 4, 1),),
                                   (_entry(21, "Kevin Fust", nationality_id=79),)).rows
        self.assertEqual(rows[0].nationality_id, 79)

    def test_an_unresolved_car_has_no_nationality_to_show(self):
        rows = summarise_penalties((_penalty(14, 5, 4, 3),)).rows
        self.assertIsNone(rows[0].nationality_id)


class GridPenaltyPlacesTests(unittest.TestCase):
    """What the classification table's grid badge is built from."""

    def test_a_car_s_grid_penalties_are_summed_into_places(self):
        """972807263... (league Q1): Fabibyte and Alonso each took two 5-place penalties and start
        ten places back; Sainz took one. `num_penalties` records 2, 2 and 1 - not the places."""
        penalties = (_penalty(9, 2, 0, 2, places_gained=5),      # Sainz
                     _penalty(13, 2, 0, 2, places_gained=5),     # Alonso
                     _penalty(13, 2, 0, 2, places_gained=5),
                     _penalty(21, 5, 7, 3, places_gained=0),     # Fabibyte, a warning - not counted
                     _penalty(21, 2, 4, 3, places_gained=5),     # Fabibyte
                     _penalty(21, 2, 4, 3, places_gained=5))
        self.assertEqual(grid_penalty_places(penalties), {9: 5, 13: 10, 21: 10})

    def test_only_grid_penalties_count(self):
        """A time penalty costs seconds, not places, and the classification already shows those."""
        penalties = (_penalty(21, 4, 21, 4, time_s=3, places_gained=0),
                     _penalty(21, 5, 17, 2, places_gained=0),
                     _penalty(21, 16, 41, 6))
        self.assertEqual(grid_penalty_places(penalties), {})

    def test_a_session_with_no_penalties_maps_nothing(self):
        self.assertEqual(grid_penalty_places(()), {})


class OrderAndCountsTests(unittest.TestCase):
    """The store's order is the box's order, and every count is a len() over the rows shown."""

    def test_the_store_s_lap_then_frame_order_is_kept_as_given(self):
        """15888071... (career race). Its lap-4 pair is replay-recovered - frame 0 - and sorts
        ahead of the lap-11 row, which is the only ordering a replayed row can offer."""
        penalties = (_penalty(21, 5, 27, 1, places_gained=0, frame=4388),
                     _penalty(7, 16, 41, 2, frame=5251),
                     _penalty(21, 5, 27, 4, places_gained=0, frame=0),
                     _penalty(21, 4, 21, 4, time_s=3, places_gained=0, frame=0),
                     _penalty(21, 5, 27, 11, places_gained=0, frame=19886))
        rows = summarise_penalties(penalties).rows
        self.assertEqual([row.lap_number for row in rows], [1, 2, 4, 4, 11])
        self.assertEqual(rows[2].outcome, "Warning")
        self.assertEqual(rows[3].outcome, "Time penalty, +3 s")

    def test_the_heading_counts_the_rows_beneath_it(self):
        summary = summarise_penalties(_Q2_PENALTIES, _Q2_ENTRIES)
        self.assertEqual(summary.heading, "Penalties (3)")
        self.assertEqual(summary.total, 3)

    def test_only_the_sporting_subset_is_counted_towards_the_classification(self):
        """The box lists three and the table's badge says one. The note is what explains that, and
        the subset is ``SessionPenalty.is_sporting`` - the one that reproduces num_penalties."""
        summary = summarise_penalties(_Q2_PENALTIES, _Q2_ENTRIES)
        self.assertEqual(summary.sporting_count, 1)
        self.assertEqual(summary.note, "1 counted towards the classification.")
        self.assertEqual([row.is_sporting for row in summary.rows], [True, False, False])

    def test_a_session_of_nothing_but_warnings_says_none_are_counted(self):
        """11108882... (career P2) is five rows and no sporting penalty - the common shape, since
        70 of the 129 rows in this database are warnings."""
        warnings = tuple(_penalty(21, 5, 17, 6, places_gained=0, frame=f)
                         for f in (16031, 21178, 23866))
        summary = summarise_penalties(warnings)
        self.assertEqual(summary.note, "0 counted towards the classification.")
        self.assertEqual(summary.sporting_count, 0)


class ThreeStatesTests(unittest.TestCase):
    """A session with rows never falls through, and an empty read never claims a clean session."""

    def test_stored_rows_are_listed_and_no_aggregate_is_shown(self):
        summary = summarise_penalties(_Q2_PENALTIES, _Q2_ENTRIES)
        self.assertEqual(summary.total, 3)
        self.assertEqual(summary.aggregates, ())

    def test_no_rows_but_a_penalised_classification_says_the_detail_is_unread(self):
        """The state every session in a database stamped 4 lands in until the re-ingest: the game's
        own aggregate survives, the per-penalty detail does not."""
        entries = (_entry(21, "Kevin Fust", is_ai=False, is_player=True,
                          num_penalties=1, penalties_time_s=3),
                   _entry(7, "Isack Hadjar", position=4))
        summary = summarise_penalties((), entries)
        self.assertEqual(summary.rows, ())
        self.assertEqual(summary.aggregates, ("Kevin Fust — ⚑ ×1 (+3s)",))
        self.assertEqual(summary.note,
                         "Penalty detail hasn't been read from this session's capture yet.")

    def test_a_time_only_penalty_still_raises_the_unread_state(self):
        """num_penalties and penalties_time_s are separate fields and either alone is evidence."""
        summary = summarise_penalties((), (_entry(3, "Player", is_ai=False, penalties_time_s=5),))
        self.assertEqual(summary.aggregates, ("Player — ⚑ (+5s)",))

    def test_nothing_stored_and_nothing_recorded_speaks_about_the_store(self):
        """Not "no penalties were issued": a session ingested before PIPELINE_VERSION 5 holds no
        rows and cannot be told apart from a genuinely clean one."""
        summary = summarise_penalties((), (_entry(21, "Kevin Fust", is_ai=False),))
        self.assertEqual(summary.note, "No penalties are stored for this session.")
        self.assertEqual(summary.heading, "Penalties")
        self.assertEqual((summary.rows, summary.aggregates), ((), ()))

    def test_a_session_with_no_classification_at_all_still_lists_its_rows(self):
        summary = summarise_penalties(_Q2_PENALTIES)
        self.assertEqual(summary.total, 3)
        self.assertEqual([row.driver for row in summary.rows], ["Car 7", "Car 1", "Car 15"])

    def test_nothing_anywhere_is_the_empty_state_not_a_crash(self):
        self.assertEqual(
            summarise_penalties((), ()),
            PenaltySummary(note="No penalties are stored for this session."))


if __name__ == "__main__":
    unittest.main()
