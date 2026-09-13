"""One session as its share image - every string the builder decides, without a QApplication.

The fixtures are this database's own rows, trimmed to the cars each rule needs and read from the
sessions that force those rules:

* ``12316788...`` - Shanghai's **Sprint Race** (a RACE, 15, on a sprint weekend whose Grand Prix is
  RACE_2, 16): the fastest lap, a finisher with a time penalty, a car that did not finish, and the
  collision whose other car the penalty names.
* ``97280726...`` - Mittwoch League's Shanghai **Q1**: grid penalties issued one at a time, two cars
  taking two 5-place penalties each, so places have to be summed.
* ``11708585...`` - the old league's **Abu Dhabi** race, raced with online-name sharing off: every
  human captured as ``Player``, named only through ``rosters/season_4.json``.
* ``11108882...`` - Suzuka **Practice 2**, whose classification was **reconstructed** from telemetry.
"""
import unittest
from dataclasses import replace
from datetime import datetime

from f1telemetry.src.domain.models import (
    Classification,
    ClassificationEntry,
    SessionPenalty,
    SessionResult,
    TyreStint,
)
from f1telemetry.src.domain.roster import LeagueMember, LeagueRoster, league_display_name
from f1telemetry.src.domain.season import WeekendSlot, slot_for_session
from f1telemetry.src.protocol.enums import Formula, ResultReason, ResultStatus, SessionType, Weather
from f1telemetry.src.ui.components.share_document import Icon, IconKind, Notes, Table, Tone
from f1telemetry.src.ui.formatting import MIXED_WEATHER_LABEL
from f1telemetry.src.ui.sessions.session_share import session_document
from f1telemetry.src.version import __version__

_SPRINT_WEEKEND = (1, 10, 11, 12, 15, 5, 6, 7, 16)
_SOFT, _MEDIUM = 16, 17
_ON_SOFTS = (TyreStint(17, _SOFT, 255),)
_ON_MEDIUMS = (TyreStint(18, _MEDIUM, 255),)
# A first stint that ends on lap 0, so a lap-1 best was set on the second.
_SOFTS_FROM_LAP_1 = (TyreStint(17, _SOFT, 0), TyreStint(17, _SOFT, 255))


def _entry(vehicle_index, position, name, *, team_id, race_number, nationality_id, grid=0,
           points=0, laps=10, stops=1, best_ms=0, best_lap=0, time_s=0.0, penalties_s=0,
           penalties=0, status=ResultStatus.FINISHED, stints=(), is_ai=True, is_player=False):
    return ClassificationEntry(
        vehicle_index=vehicle_index, position=position, driver_name=name, team_id=team_id,
        race_number=race_number, nationality_id=nationality_id, is_player=is_player,
        grid_position=grid, points=points, num_laps=laps, num_pit_stops=stops,
        best_lap_time_ms=best_ms, best_lap_num=best_lap, total_race_time_s=time_s,
        penalties_time_s=penalties_s, num_penalties=penalties, result_status=status,
        result_reason=ResultReason.FINISHED, tyre_stints=stints, is_ai=is_ai)


def _session(entries, *, uid, track_id, session_type, session_link, total_laps, weather,
             weather_seen, temperatures, recorded_at, structure, reconstructed=False):
    return SessionResult(
        session_uid=uid, season_link_id=0, weekend_link_id=3602001984, session_link_id=session_link,
        game_format=2026, track_id=track_id, session_type=session_type, formula=Formula.F1_MODERN,
        weather=weather, total_laps=total_laps, game_mode=78, player_vehicle_index=21,
        weekend_structure=structure, weather_seen=weather_seen,
        track_temperature=temperatures[0], air_temperature=temperatures[1],
        classification=Classification(entries=tuple(entries), is_reconstructed=reconstructed),
        recorded_at=recorded_at)


# --- 12316788... Shanghai, Sprint Race --------------------------------------------------------------
_SPRINT_ENTRIES = (
    _entry(21, 1, "Kevin Fust", team_id=477, race_number=50, nationality_id=79, grid=2, points=8,
           best_ms=95435, best_lap=6, time_s=2628.815185546875, stints=_ON_MEDIUMS, is_ai=False,
           is_player=True),
    _entry(6, 2, "Charles Leclerc", team_id=477, race_number=16, nationality_id=53, grid=1, points=7,
           best_ms=95587, best_lap=6, time_s=2630.673583984375, stints=_ON_MEDIUMS),
    _entry(3, 6, "Andra-Kimi Antonelli", team_id=476, race_number=12, nationality_id=41, grid=3,
           points=3, best_ms=97031, best_lap=10, time_s=2636.417724609375, stints=_ON_SOFTS),
    _entry(13, 19, "Oliver Bearman", team_id=483, race_number=87, nationality_id=10, grid=21,
           best_ms=97527, best_lap=7, time_s=2660.26123046875, stints=_ON_MEDIUMS),
    _entry(10, 21, "Arvid Lindblad", team_id=482, race_number=41, nationality_id=10, grid=22,
           best_ms=98037, best_lap=5, time_s=2658.009521484375, penalties_s=5, penalties=1,
           stints=_ON_MEDIUMS),
    _entry(4, 22, "Max Verstappen", team_id=478, race_number=3, nationality_id=22, grid=5, laps=3,
           best_ms=102485, best_lap=1, time_s=2010.9356689453125,
           status=ResultStatus.DID_NOT_FINISH, stints=_ON_SOFTS),
)
_SPRINT_PENALTIES = (
    SessionPenalty(vehicle_index=21, penalty_type=5, infringement_type=4, lap_number=1,
                   other_vehicle_index=3, places_gained=0, frame=3697),           # Warning
    SessionPenalty(vehicle_index=10, penalty_type=4, infringement_type=3, lap_number=2,
                   other_vehicle_index=13, time_s=5, places_gained=0, frame=6321),  # +5 s
    SessionPenalty(vehicle_index=4, penalty_type=16, infringement_type=41, lap_number=4,
                   frame=7829),                                                    # Retired
)
_SPRINT = _session(_SPRINT_ENTRIES, uid=12316788787714930067, track_id=2,
                   session_type=SessionType.RACE, session_link=3602002024, total_laps=10,
                   weather=Weather.LIGHT_CLOUD, weather_seen=(Weather.CLEAR, Weather.LIGHT_CLOUD),
                   temperatures=(31, 21), recorded_at=datetime(2026, 7, 5, 12, 46, 41),
                   structure=_SPRINT_WEEKEND)
# The same weekend's Grand Prix, which the game reports as RACE_2 (16).
_GRAND_PRIX = replace(_SPRINT, session_uid=14036667092197666810, session_link_id=3602002064,
                      session_type=SessionType.RACE_2, recorded_at=datetime(2026, 7, 9, 16, 22, 10))
# The Sprint as it would be stored had no Final Classification packet arrived.
_REBUILT_SPRINT = replace(_SPRINT, classification=replace(_SPRINT.classification,
                                                          is_reconstructed=True))

# --- 97280726... Shanghai, Q1 (Mittwoch League) ----------------------------------------------------
_Q1_ENTRIES = (
    _entry(3, 1, "soundscape93", team_id=477, race_number=50, nationality_id=79, laps=1, stops=0,
           best_ms=94205, best_lap=1, stints=_ON_SOFTS, is_ai=False, is_player=True),
    _entry(21, 7, "Fabibyte", team_id=477, race_number=11, nationality_id=41, laps=6, stops=0,
           best_ms=95483, best_lap=4, penalties=2, stints=_ON_SOFTS, is_ai=False),
    _entry(13, 10, "Fernando Alonso", team_id=480, race_number=14, nationality_id=77, laps=2,
           stops=0, best_ms=95700, best_lap=1, penalties=2, stints=_SOFTS_FROM_LAP_1),
    _entry(9, 11, "Carlos Sainz", team_id=479, race_number=55, nationality_id=77, laps=2, stops=0,
           best_ms=95778, best_lap=1, penalties=1, stints=_SOFTS_FROM_LAP_1),
)
_Q1_PENALTIES = (
    SessionPenalty(vehicle_index=9, penalty_type=2, infringement_type=0, lap_number=2,
                   other_vehicle_index=8, places_gained=5, frame=18494),
    SessionPenalty(vehicle_index=13, penalty_type=2, infringement_type=0, lap_number=2,
                   other_vehicle_index=4, places_gained=5, frame=18853),
    SessionPenalty(vehicle_index=13, penalty_type=2, infringement_type=0, lap_number=2,
                   other_vehicle_index=4, places_gained=5, frame=19027),
    SessionPenalty(vehicle_index=21, penalty_type=2, infringement_type=4, lap_number=3,
                   other_vehicle_index=5, places_gained=5, frame=8941),
    SessionPenalty(vehicle_index=21, penalty_type=2, infringement_type=4, lap_number=3,
                   other_vehicle_index=4, places_gained=5, frame=9022),
)
_Q1 = _session(_Q1_ENTRIES, uid=972807263249683142, track_id=2,
               session_type=SessionType.QUALIFYING_1, session_link=458523011, total_laps=2,
               weather=Weather.CLEAR, weather_seen=(Weather.CLEAR,), temperatures=(28, 20),
               recorded_at=datetime(2026, 8, 12, 18, 25, 18), structure=(5, 6, 7, 15))

# --- 11708585... Abu Dhabi, Race (old league, online names off) ------------------------------------
_ABU_DHABI_ENTRIES = (
    _entry(2, 1, "Player", team_id=4, race_number=97, nationality_id=65, grid=1, points=25,
           laps=29, stops=2, best_ms=86938, best_lap=24, time_s=2614.111328125, is_ai=False),
    _entry(1, 2, "Player", team_id=8, race_number=11, nationality_id=41, grid=3, points=18,
           laps=29, stops=2, best_ms=87757, best_lap=14, time_s=2627.83154296875, is_ai=False),
    _entry(4, 3, "Player", team_id=1, race_number=50, nationality_id=79, grid=2, points=15,
           laps=29, stops=3, best_ms=87455, best_lap=12, time_s=2659.952392578125, is_ai=False,
           is_player=True),
    _entry(3, 4, "Player", team_id=4, race_number=2, nationality_id=31, grid=20, points=12,
           laps=29, stops=2, best_ms=87055, best_lap=22, time_s=2661.924560546875, penalties_s=3,
           penalties=1, is_ai=False),
    _entry(0, 5, "Player", team_id=9, race_number=24, nationality_id=79, grid=4, points=10,
           laps=29, stops=2, best_ms=89150, best_lap=24, time_s=2665.845458984375, is_ai=False),
)
_ABU_DHABI_PENALTIES = (
    SessionPenalty(vehicle_index=3, penalty_type=4, infringement_type=7, lap_number=7, time_s=3,
                   places_gained=0, frame=16232),
)
_ABU_DHABI = _session(_ABU_DHABI_ENTRIES, uid=11708585607616380307, track_id=14,
                      session_type=SessionType.RACE, session_link=845505725, total_laps=29,
                      weather=Weather.CLEAR, weather_seen=(Weather.CLEAR,), temperatures=(32, 25),
                      recorded_at=datetime(2026, 6, 22, 18, 52, 24), structure=(5, 6, 7, 15))
# rosters/season_4.json, as saved.
_SEASON_4 = LeagueRoster(members=(
    LeagueMember(name="Kevin", race_number=50, online_names=("soundscape93",)),
    LeagueMember(name="Remo", race_number=97, online_names=("basejumper6969",)),
    LeagueMember(name="Patrick", race_number=2, online_names=("patrickstein12",)),
    LeagueMember(name="Fabian", race_number=11, online_names=("Fabibyte",)),
    LeagueMember(name="Roli", race_number=24, online_names=("RoliMei",)),
))

# --- 11108882... Suzuka, Practice 2 (reconstructed) ------------------------------------------------
_PRACTICE = _session(
    (_entry(21, 1, "Kevin Fust", team_id=477, race_number=50, nationality_id=79, laps=11, stops=0,
            best_ms=90377, best_lap=11, is_ai=False, is_player=True),
     _entry(6, 2, "Charles Leclerc", team_id=477, race_number=16, nationality_id=53, laps=12,
            best_ms=92212, best_lap=5)),
    uid=11108882740745056196, track_id=13, session_type=SessionType.PRACTICE_2,
    session_link=3602002094, total_laps=6, weather=Weather.LIGHT_CLOUD,
    weather_seen=(Weather.CLEAR, Weather.LIGHT_CLOUD), temperatures=(22, 16),
    recorded_at=datetime(2026, 7, 19, 11, 47, 24), structure=(1, 2, 3, 5, 6, 7, 15),
    reconstructed=True)


def _slot(session, *, sprint=False):
    return WeekendSlot(order=0, session_type=session.session_type, sessions=(session,),
                       is_sprint_race=sprint)


def _sprint(session=_SPRINT, penalties=_SPRINT_PENALTIES, **kwargs):
    return session_document(session, _slot(session, sprint=True), penalties, **kwargs)


def _q1(session=_Q1, penalties=_Q1_PENALTIES):
    return session_document(session, _slot(session), penalties)


def _classification(document) -> Table:
    return document.blocks[1]


def _column(table: Table, header: str) -> list:
    index = [column.header for column in table.columns].index(header)
    return [row[index] for row in table.rows]


def _texts(table: Table, header: str) -> list[str]:
    return [cell.text for cell in _column(table, header)]


class TitleTests(unittest.TestCase):
    """What the image calls the session - by its place in the weekend, never its raw type."""

    def test_a_sprint_race_and_its_grand_prix_are_named_by_their_place_in_the_weekend(self):
        """Core invariant #5, through the real slot resolver: the Sprint reports RACE (15) and the
        Grand Prix RACE_2 (16), and neither is read off its number."""
        weekend = [_SPRINT, _GRAND_PRIX]
        sprint = session_document(_SPRINT, slot_for_session(_SPRINT, weekend), _SPRINT_PENALTIES)
        grand_prix = session_document(_GRAND_PRIX, slot_for_session(_GRAND_PRIX, weekend))
        self.assertEqual("Shanghai — Sprint Race", sprint.title)
        self.assertEqual("Shanghai — Race", grand_prix.title)

    def test_the_classification_is_titled_as_the_page_titles_it(self):
        """Repeating the slot, as the page's box does: a cropped image still says which session."""
        self.assertEqual("Final classification · Sprint Race", _classification(_sprint()).title)


class MetaTests(unittest.TestCase):
    """The line under the title, the file name and the footer."""

    def test_an_assigned_session_names_its_season_and_round_then_when_it_was_recorded(self):
        document = _sprint(placement=("Season 1 (“Ferrari”)", 2))
        self.assertEqual("Season 1 (“Ferrari”)  ·  Round 2  ·  2026-07-05 12:46", document.meta)

    def test_an_unassigned_session_says_only_when_it_was_recorded(self):
        self.assertEqual("2026-07-05 12:46", _sprint().meta)

    def test_the_file_is_named_by_when_where_and_which_session(self):
        """The recorded time is what tells two attempts at a slot apart - no attempt numbers."""
        self.assertEqual("2026-07-05_1246_Shanghai_Sprint-Race", _sprint().name)
        self.assertEqual("2026-08-12_1825_Shanghai_Qualifying-1", _q1().name)

    def test_a_session_with_no_recorded_time_leaves_it_out_of_both(self):
        document = _sprint(replace(_SPRINT, recorded_at=None))
        self.assertEqual(("", "Shanghai_Sprint-Race"), (document.meta, document.name))

    def test_the_footer_names_the_app_and_its_version(self):
        self.assertEqual(f"f1telemetry v{__version__}", _sprint().footer)


class FactsTests(unittest.TestCase):
    """The header facts are the session's, and a fact never captured is left out."""

    def test_a_race_states_its_fastest_lap_distance_weather_and_temperatures(self):
        facts = _sprint().blocks[0]
        self.assertEqual([("Fastest lap", "Kevin Fust — 1:35.435"), ("Laps", "10"),
                          ("Weather", "Light cloud"), ("Track / air", "31 °C / 21 °C")],
                         [(key, cell.text) for key, cell in facts.pairs])
        self.assertIs(Tone.FASTEST, facts.pairs[0][1].tone)

    def test_a_race_distance_is_never_stated_outside_a_race(self):
        """``total_laps`` is 2 in this Q1 and means nothing there."""
        self.assertNotIn("Laps", [key for key, _ in _q1().blocks[0].pairs])

    def test_a_session_that_ran_dry_and_wet_says_so(self):
        mixed = replace(_SPRINT, weather_seen=(Weather.LIGHT_CLOUD, Weather.LIGHT_RAIN))
        pairs = dict(_sprint(mixed).blocks[0].pairs)
        self.assertEqual(MIXED_WEATHER_LABEL, pairs["Weather"].text)

    def test_what_was_never_captured_is_left_out_rather_than_printed(self):
        """No temperatures (ingested before PIPELINE_VERSION 5), and nobody set a lap time."""
        untimed = replace(_SPRINT, track_temperature=None, air_temperature=None,
                          classification=Classification(entries=tuple(
                              replace(entry, best_lap_time_ms=0) for entry in _SPRINT_ENTRIES)))
        self.assertEqual(["Laps", "Weather"], [key for key, _ in _sprint(untimed).blocks[0].pairs])


class NameTests(unittest.TestCase):
    """Every driver named by the one resolver the page uses (E1c)."""

    def test_the_resolver_reaches_every_name_the_image_prints(self):
        """The table, the penalised drivers, the other car in an incident and the fastest lap."""
        document = _sprint(name_of=lambda entry: entry.driver_name.upper())
        self.assertEqual(["KEVIN FUST", "CHARLES LECLERC", "ANDRA-KIMI ANTONELLI", "OLIVER BEARMAN",
                          "ARVID LINDBLAD", "MAX VERSTAPPEN"],
                         _texts(_classification(document), "DRIVER"))
        race_control = document.blocks[2]
        self.assertEqual(["KEVIN FUST", "ARVID LINDBLAD", "MAX VERSTAPPEN"],
                         _texts(race_control, "DRIVER"))
        self.assertIn("Big Collision with OLIVER BEARMAN", _texts(race_control, "REASON"))
        self.assertEqual("KEVIN FUST — 1:35.435", dict(document.blocks[0].pairs)["Fastest lap"].text)

    def test_a_league_raced_with_online_names_off_reads_as_its_members(self):
        """Every human here captured as "Player"; the saved roster names them, by race number."""
        document = session_document(_ABU_DHABI, _slot(_ABU_DHABI), _ABU_DHABI_PENALTIES,
                                    lambda entry: league_display_name(entry, _SEASON_4))
        self.assertEqual(["basejumper6969", "Fabibyte", "soundscape93", "patrickstein12", "RoliMei"],
                         _texts(_classification(document), "DRIVER"))
        self.assertEqual(["patrickstein12"], _texts(document.blocks[2], "DRIVER"))
        self.assertEqual("basejumper6969 — 1:26.938",
                         dict(document.blocks[0].pairs)["Fastest lap"].text)

    def test_every_driver_carries_their_nationality_flag(self):
        self.assertEqual([Icon(IconKind.FLAG, n) for n in (79, 53, 41, 10, 10, 22)],
                         [cell.icon for cell in _column(_classification(_sprint()), "DRIVER")])


class ClassificationTests(unittest.TestCase):
    """The table itself, column for column the page's."""

    def test_a_race_reads_like_the_pages_race_table_plus_a_penalty_column(self):
        self.assertEqual(["POS", "", "DRIVER", "TEAM", "GRID", "STOPS", "BEST", "TIME", "PEN", "PTS"],
                         [c.header for c in _classification(_sprint()).columns])

    def test_a_qualifying_session_reads_like_the_pages_plus_a_grid_penalty_column(self):
        self.assertEqual(["POS", "DRIVER", "TEAM", "TYRE", "BEST", "GAP", "GRID PENALTY"],
                         [c.header for c in _classification(_q1()).columns])

    def test_the_race_cells_are_the_pages_own(self):
        table = _classification(_sprint())
        self.assertEqual(["Ferrari", "Ferrari", "Mercedes", "Haas", "RB", "Red Bull Racing"],
                         _texts(table, "TEAM"))
        self.assertEqual(["2", "1", "3", "21", "22", "5"], _texts(table, "GRID"))
        self.assertEqual(["43:48.815", "+1.858", "+7.603", "+31.446", "+34.194", "DNF"],
                         _texts(table, "TIME"))

    def test_the_position_change_is_a_bold_triangle_coloured_by_direction(self):
        """Up green, down red, unchanged in the ink colour - bold throughout, as on the page."""
        changes = _column(_classification(_sprint()), "")
        self.assertEqual([("▲", Tone.GAIN), ("▼", Tone.LOSS), ("▼", Tone.LOSS), ("▲", Tone.GAIN),
                          ("▲", Tone.GAIN), ("▼", Tone.LOSS)],
                         [(cell.text, cell.tone) for cell in changes])
        self.assertTrue(all(cell.strong for cell in changes))
        unchanged = _classification(_sprint(replace(_SPRINT, classification=Classification(entries=(
            replace(_SPRINT_ENTRIES[0], grid_position=1),))))).rows[0][1]
        self.assertEqual(("—", Tone.PLAIN), (unchanged.text, unchanged.tone))

    def test_the_session_fastest_lap_is_blue_on_that_row_alone(self):
        bests = _column(_classification(_sprint()), "BEST")
        self.assertEqual([Tone.FASTEST] + [Tone.PLAIN] * 5, [cell.tone for cell in bests])

    def test_a_qualifying_tyre_is_the_compound_the_best_lap_was_set_on(self):
        """Alonso's and Sainz's first stints end on lap 0, so their lap-1 bests are on the second."""
        tyres = _column(_classification(_q1()), "TYRE")
        self.assertEqual([Icon(IconKind.TYRE, _SOFT)] * 4, [cell.icon for cell in tyres])

    def test_a_car_with_no_stint_for_its_best_lap_has_an_empty_tyre_cell(self):
        """84 of this database's practice and qualifying rows have no compound for their best lap;
        the page gives them an empty cell, and so does the image."""
        no_stints = replace(_Q1, classification=Classification(
            entries=_Q1_ENTRIES[:3] + (replace(_Q1_ENTRIES[3], tyre_stints=()),)))
        tyre = _column(_classification(_q1(no_stints)), "TYRE")[3]
        self.assertEqual(("", None), (tyre.text, tyre.icon))


class PointsTests(unittest.TestCase):
    """Points only where they mean something."""

    def test_a_race_shows_the_points_the_game_awarded(self):
        self.assertEqual(["8", "7", "3", "0", "0", "0"], _texts(_classification(_sprint()), "PTS"))

    def test_a_reconstructed_sprint_is_estimated_on_the_sprint_scale_and_muted(self):
        """No Final Classification, so no official points: the page's ``~N``, blank for a DNF."""
        points = _column(_classification(_sprint(_REBUILT_SPRINT)), "PTS")
        self.assertEqual(["~8", "~7", "~3", "~0", "~0", ""], [cell.text for cell in points])
        self.assertTrue(all(cell.tone is Tone.MUTED for cell in points))

    def test_a_reconstructed_grand_prix_is_estimated_on_the_grand_prix_scale(self):
        document = session_document(_REBUILT_SPRINT, _slot(_REBUILT_SPRINT), _SPRINT_PENALTIES)
        self.assertEqual(["~25", "~18"], _texts(_classification(document), "PTS")[:2])

    def test_a_qualifying_session_carries_no_points_even_when_the_game_sent_some(self):
        """The game leaves the last race's points in a non-race classification - real Q1 rows carry
        25 - and a number that is simply untrue must not reach the chat."""
        stale = replace(_Q1, classification=Classification(entries=tuple(
            replace(entry, points=25) for entry in _Q1_ENTRIES)))
        table = _classification(_q1(stale))
        self.assertNotIn("PTS", [c.header for c in table.columns])
        self.assertNotIn("25", [cell.text for row in table.rows for cell in row])


class ReconstructedTests(unittest.TestCase):
    """A classification rebuilt from telemetry says so, under its title."""

    def test_a_reconstructed_race_says_so_and_that_its_points_are_estimates(self):
        self.assertEqual("Rebuilt from telemetry: the game sent no final classification for this "
                         "session, so the order may differ from the game's and points marked ~ are "
                         "estimates.", _classification(_sprint(_REBUILT_SPRINT)).note)

    def test_a_reconstructed_practice_says_so_without_mentioning_points(self):
        document = session_document(_PRACTICE, _slot(_PRACTICE))
        self.assertEqual("Rebuilt from telemetry: the game sent no final classification for this "
                         "session, so the order may differ from the game's.",
                         _classification(document).note)
        self.assertEqual("Suzuka — Practice 2", document.title)

    def test_a_classification_the_game_sent_carries_no_note(self):
        self.assertEqual("", _classification(_sprint()).note)


class PenaltyColumnTests(unittest.TestCase):
    """What the page flips a cell to, the image puts in a column - and only when it is needed."""

    def test_a_penalised_finisher_carries_the_pages_badge(self):
        self.assertEqual(["", "", "", "", "⚑ ×1 (+5s)", ""],
                         _texts(_classification(_sprint()), "PEN"))

    def test_a_car_that_did_not_finish_carries_no_badge_as_on_the_page(self):
        penalised_dnf = replace(_SPRINT_ENTRIES[5], num_penalties=1, penalties_time_s=5)
        session = replace(_SPRINT, classification=Classification(
            entries=_SPRINT_ENTRIES[:5] + (penalised_dnf,)))
        self.assertEqual("", _texts(_classification(_sprint(session)), "PEN")[5])

    def test_a_race_nobody_was_penalised_in_has_no_penalty_column(self):
        clean = replace(_SPRINT, classification=Classification(entries=tuple(
            replace(entry, num_penalties=0, penalties_time_s=0) for entry in _SPRINT_ENTRIES)))
        table = _classification(_sprint(clean))
        self.assertNotIn("PEN", [c.header for c in table.columns])
        self.assertTrue(all(len(row) == 9 for row in table.rows))

    def test_grid_penalties_are_summed_into_the_places_the_car_drops(self):
        """Alonso and Fabibyte each took two 5-place penalties: ten places, not "×2"."""
        self.assertEqual(["", "⚑ 10-place grid", "⚑ 10-place grid", "⚑ 5-place grid"],
                         _texts(_classification(_q1()), "GRID PENALTY"))

    def test_a_session_without_grid_penalties_has_no_grid_penalty_column(self):
        self.assertNotIn("GRID PENALTY",
                         [c.header for c in _classification(_q1(penalties=())).columns])


class RaceControlTests(unittest.TestCase):
    """The Race control box, in each of its three states, worded by ``race_control``."""

    def test_stored_penalties_are_listed_under_their_count(self):
        race_control = _sprint().blocks[2]
        self.assertEqual(("Race control · Penalties (3)", "1 counted towards the classification."),
                         (race_control.title, race_control.note))
        self.assertEqual(
            [("1", "Kevin Fust", "Warning", "Small Collision with Andra-Kimi Antonelli"),
             ("2", "Arvid Lindblad", "Time penalty, +5 s", "Big Collision with Oliver Bearman"),
             ("4", "Max Verstappen", "Retired", "mechanical failure")],
            [tuple(cell.text for cell in row) for row in race_control.rows])

    def test_a_human_driver_and_a_penalty_that_counts_are_bold(self):
        rows = _sprint().blocks[2].rows
        self.assertEqual([True, False, False], [row[1].strong for row in rows])     # Kevin Fust
        self.assertEqual([False, True, False], [row[2].strong for row in rows])     # the +5 s

    def test_a_car_the_classification_cannot_name_is_car_n_with_no_flag(self):
        unknown = (SessionPenalty(vehicle_index=19, penalty_type=5, infringement_type=4,
                                  lap_number=9, frame=18620),)
        row = _sprint(penalties=unknown).blocks[2].rows[0]
        self.assertEqual(("Car 19", None), (row[1].text, row[1].icon))

    def test_detail_not_yet_read_lists_the_totals_then_says_so(self):
        """No stored rows but a classification that counts a penalty: the page's middle state."""
        race_control = _sprint(penalties=()).blocks[2]
        self.assertIsInstance(race_control, Notes)
        self.assertEqual("Race control · Penalties", race_control.title)
        self.assertEqual([("Arvid Lindblad — ⚑ ×1 (+5s)", Tone.PLAIN),
                          ("Penalty detail hasn't been read from this session's capture yet.",
                           Tone.MUTED)],
                         [(cell.text, cell.tone) for cell in race_control.lines])

    def test_nothing_stored_speaks_about_the_store_and_not_the_session(self):
        clean = replace(_SPRINT, classification=Classification(entries=tuple(
            replace(entry, num_penalties=0, penalties_time_s=0) for entry in _SPRINT_ENTRIES)))
        race_control = _sprint(clean, penalties=()).blocks[2]
        self.assertEqual([("No penalties are stored for this session.", Tone.MUTED)],
                         [(cell.text, cell.tone) for cell in race_control.lines])


if __name__ == "__main__":
    unittest.main()
