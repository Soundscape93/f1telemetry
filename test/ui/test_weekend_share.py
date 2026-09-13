"""A whole weekend as its folder of share images - the naming and the ordering, without a QApplication.

The fixture is this database's round 5 at Jeddah: seven slots, one of them - Practice 2 - recorded
twice, which is the case core invariant #5 exists for. Nothing here numbers the attempts as first
and second; they are two files told apart by the time in their names, in the order they were
driven.

The per-session content is ``session_share``'s and is asserted there. What is asserted here is
everything that only exists because the sessions are exported *together*: which rows become files,
what those files are called, and what the folder holding them is called.
"""
import unittest
from datetime import datetime

from f1telemetry.src.domain.models import Classification, ClassificationEntry, SessionResult
from f1telemetry.src.protocol.enums import (
    Formula,
    ResultReason,
    ResultStatus,
    SessionType,
    Weather,
)
from f1telemetry.src.ui.components.share_document import Cell, Notes, ShareDocument
from f1telemetry.src.ui.sessions.weekend_share import WeekendExport, weekend_documents
from f1telemetry.src.ui.sessions.weekend_view import weekend_rows

_JEDDAH, _SHANGHAI = 29, 2
_FERRARI = 1
# Jeddah's own weekend: three practices, three qualifying segments, then the race.
_STRUCTURE = (1, 2, 3, 5, 6, 7, 15)
_SPRINT_STRUCTURE = (1, 10, 11, 12, 15, 5, 6, 7, 16)


def _entry(position, name, race_number):
    return ClassificationEntry(
        vehicle_index=position - 1, position=position, driver_name=name, team_id=_FERRARI,
        race_number=race_number, nationality_id=79, is_player=False, grid_position=position,
        points=0, num_laps=10, num_pit_stops=1, best_lap_time_ms=90000 + position, best_lap_num=5,
        total_race_time_s=1800.0, penalties_time_s=0, num_penalties=0,
        result_status=ResultStatus.FINISHED, result_reason=ResultReason.FINISHED,
        tyre_stints=(), is_ai=True)


def _session(uid, session_type, recorded, *, track_id=_JEDDAH, structure=_STRUCTURE,
             session_link=None):
    """One stored session. ``recorded`` is "HH:MM" on 2026-08-23 unless it carries a date."""
    when = (None if recorded is None else
            datetime.strptime(recorded if " " in recorded else f"2026-08-23 {recorded}",
                              "%Y-%m-%d %H:%M"))
    return SessionResult(
        session_uid=uid, season_link_id=1, weekend_link_id=7, session_link_id=session_link or uid,
        game_format=2026, track_id=track_id, session_type=session_type,
        formula=Formula.F1_MODERN, weather=Weather.CLEAR, total_laps=10, game_mode=19,
        player_vehicle_index=0, weekend_structure=structure, recorded_at=when,
        classification=Classification(entries=(_entry(1, "soundscape93", 50),
                                               _entry(2, "Fabibyte", 11))))


# Practice 2 driven twice - the one slot this weekend holds two attempts at (invariant #5).
_WEEKEND = (
    _session(1, SessionType.PRACTICE_1, "11:21"),
    _session(2, SessionType.PRACTICE_2, "11:59"),
    _session(3, SessionType.PRACTICE_2, "12:07", session_link=2),
    _session(4, SessionType.PRACTICE_3, "15:27"),
    _session(5, SessionType.QUALIFYING_1, "15:59"),
    _session(6, SessionType.QUALIFYING_2, "16:08"),
    _session(7, SessionType.QUALIFYING_3, "16:18"),
    _session(8, SessionType.RACE, "16:55"),
)

_STANDINGS = ShareDocument(title="Season 1 — Standings after round 5 (Jeddah)",
                           name="Season-1_Standings-round-5",
                           blocks=(Notes((Cell("the championship"),)),))


def _export(sessions=_WEEKEND, round_number=5, season_name="Season 1", **kwargs):
    return weekend_documents(weekend_rows(sessions), round_number, season_name, **kwargs)


class FolderTests(unittest.TestCase):
    """What the folder a weekend lands in is called."""

    def test_it_leads_with_the_day_the_weekend_was_driven(self):
        """Date-led like a session's own file, so a folder of exports sorts chronologically."""
        self.assertEqual("2026-08-23_Jeddah_Round-5", _export().folder)

    def test_the_date_is_the_earliest_session_s_not_the_first_row_s(self):
        """A re-driven session is recorded after the ones that follow it in the weekend."""
        late = (_session(9, SessionType.PRACTICE_1, "2026-08-24 09:00"),) + _WEEKEND[1:]
        self.assertEqual("2026-08-23_Jeddah_Round-5", _export(sessions=late).folder)

    def test_a_weekend_with_no_recorded_times_is_still_named(self):
        sessions = tuple(_session(s.session_uid, s.session_type, None) for s in _WEEKEND)
        self.assertEqual("Jeddah_Round-5", _export(sessions=sessions).folder)

    def test_a_round_holding_nothing_is_named_by_its_round_alone(self):
        self.assertEqual(WeekendExport("Round-5", ()), _export(sessions=()))


class FileNameTests(unittest.TestCase):
    """What the files inside it are called, and why they are numbered."""

    def test_every_session_is_numbered_from_its_place_in_the_weekend(self):
        self.assertEqual(
            ["01_1121_Practice-1", "02_1159_Practice-2", "03_1207_Practice-2",
             "04_1527_Practice-3", "05_1559_Qualifying-1", "06_1608_Qualifying-2",
             "07_1618_Qualifying-3", "08_1655_Race"],
            [document.name for document in _export().documents])

    def test_two_attempts_at_one_slot_are_two_files_and_neither_is_called_the_real_one(self):
        """Core invariant #5: which attempt counts is a judgement, so nothing here makes it."""
        names = [d.name for d in _export().documents if d.name.endswith("Practice-2")]
        self.assertEqual(["02_1159_Practice-2", "03_1207_Practice-2"], names)

    def test_the_number_orders_the_folder_even_when_the_times_do_not(self):
        """A re-driven Practice 1 is recorded last, and still sorts first - it ran first."""
        redriven = (_session(1, SessionType.PRACTICE_1, "2026-08-24 20:00"),) + _WEEKEND[1:]
        names = [d.name for d in _export(sessions=redriven).documents]
        self.assertEqual("01_2000_Practice-1", names[0])
        self.assertEqual(names, sorted(names))

    def test_a_session_with_no_recorded_time_drops_that_part_rather_than_leaving_a_gap(self):
        sessions = (_session(1, SessionType.PRACTICE_1, None),) + _WEEKEND[1:]
        self.assertEqual("01_Practice-1", _export(sessions=sessions).documents[0].name)

    def test_a_sprint_race_is_named_by_its_slot_and_not_its_session_type(self):
        """Both races report RACE (15); only the weekend position tells them apart (#5)."""
        sprint = (
            _session(1, SessionType.PRACTICE_1, "11:21", structure=_SPRINT_STRUCTURE),
            _session(2, SessionType.RACE, "12:46", structure=_SPRINT_STRUCTURE),
            _session(3, SessionType.RACE_2, "16:22", structure=_SPRINT_STRUCTURE),
        )
        self.assertEqual(["01_1121_Practice-1", "02_1246_Sprint-Race", "03_1622_Race"],
                         [d.name for d in _export(sessions=sprint).documents])


class WhatIsExportedTests(unittest.TestCase):
    """Which rows become files, and what each one says about where it belongs."""

    def test_a_slot_holding_no_session_is_not_a_file(self):
        """It is a row on the page - Skipped, or not captured yet - but there is nothing to draw."""
        without_p3 = tuple(s for s in _WEEKEND if s.session_type is not SessionType.PRACTICE_3)
        rows = weekend_rows(without_p3)
        self.assertEqual(8, len(rows))          # seven sessions plus the empty Practice 3 row
        self.assertEqual(["01_1121_Practice-1", "02_1159_Practice-2", "03_1207_Practice-2",
                          "04_1559_Qualifying-1", "05_1608_Qualifying-2", "06_1618_Qualifying-3",
                          "07_1655_Race"],
                         [d.name for d in _export(sessions=without_p3).documents])

    def test_every_image_says_which_season_and_round_it_is_from(self):
        for document in _export().documents:
            with self.subTest(name=document.name):
                self.assertTrue(document.meta.startswith("Season 1  ·  Round 5"), document.meta)

    def test_each_image_is_the_session_s_own_result(self):
        """The content is ``session_share``'s; only the name is decided here."""
        titles = [d.title for d in _export().documents]
        self.assertEqual(["Jeddah — Practice 1", "Jeddah — Practice 2", "Jeddah — Practice 2",
                          "Jeddah — Practice 3", "Jeddah — Qualifying 1", "Jeddah — Qualifying 2",
                          "Jeddah — Qualifying 3", "Jeddah — Race"], titles)

    def test_the_page_s_own_resolver_names_the_drivers(self):
        """Handed in per session, so a league's members are named here as they are on the page."""
        export = _export(name_of_for=lambda session: (lambda entry: f"#{entry.race_number}"))
        drivers = export.documents[0].blocks[1]
        column = [c.header for c in drivers.columns].index("DRIVER")
        self.assertEqual(["#50", "#11"], [row[column].text for row in drivers.rows])

    def test_the_session_s_stored_penalties_are_asked_for_per_session(self):
        asked = []
        _export(penalties_of=lambda session: asked.append(session.session_uid) or ())
        self.assertEqual([1, 2, 3, 4, 5, 6, 7, 8], asked)


class StandingsTests(unittest.TestCase):
    """The championship goes in the folder too, and goes in last."""

    def test_it_is_the_last_file_and_numbered_after_the_sessions(self):
        documents = _export(standings=_STANDINGS).documents
        self.assertEqual(9, len(documents))
        self.assertEqual("09_Standings-round-5", documents[-1].name)

    def test_it_keeps_everything_but_its_name(self):
        """Renamed for the folder, never rebuilt - the caller decided what it says."""
        last = _export(standings=_STANDINGS).documents[-1]
        self.assertEqual(_STANDINGS.title, last.title)
        self.assertEqual(_STANDINGS.blocks, last.blocks)
        self.assertNotEqual(_STANDINGS.name, last.name)

    def test_a_weekend_exported_without_standings_is_just_its_sessions(self):
        self.assertEqual(8, len(_export().documents))

    def test_a_round_with_no_sessions_still_exports_the_standings(self):
        export = _export(sessions=(), standings=_STANDINGS)
        self.assertEqual(("Round-5", "01_Standings-round-5"),
                         (export.folder, export.documents[0].name))


class ShapeTests(unittest.TestCase):
    """What the caller gets back."""

    def test_it_is_a_plain_pair_so_the_delivery_need_not_import_this_module(self):
        """``components/`` must not import a surface package, and ``ShareControl`` takes this."""
        export = _export()
        folder, documents = export
        self.assertIsInstance(export, tuple)
        self.assertEqual((export.folder, export.documents), (folder, documents))

    def test_no_two_files_in_a_folder_share_a_name(self):
        names = [d.name for d in _export(standings=_STANDINGS).documents]
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
