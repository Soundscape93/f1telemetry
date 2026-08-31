"""``pipeline.delete_session`` - the one write point for removing a stored session.

Covers the guard (an assigned session is refused, and the refusal says where it is placed), the
happy path (session row, lap rows and Parquet traces all go together) and the no-op. The guard
is why this function exists at all: ``SessionStore.delete`` will delete an assigned session
happily, and the weekend picker used to let it.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from f1telemetry.src.domain.calendars import official_calendar
from f1telemetry.src.domain.models import Classification, ClassificationEntry, SessionResult
from f1telemetry.src.domain.season import SeasonMode
from f1telemetry.src.pipeline import delete_session
from f1telemetry.src.protocol.enums import (
    Formula, ResultReason, ResultStatus, SessionType, Weather,
)
from f1telemetry.src.storage.seasons import SeasonStore
from f1telemetry.src.storage.sessions import SessionStore

try:
    import pyarrow  # noqa: F401
    from f1telemetry.src.storage.laps import LapStore
    from f1telemetry.test.storage.test_lap_perstistance import make_lap
    _HAS_PYARROW = True
except ImportError:
    _HAS_PYARROW = False


def _reason():
    return getattr(ResultReason, "INVALID", None) or getattr(ResultReason, "NONE", 0)


def _session(uid: int) -> SessionResult:
    """A minimal stored session - identity plus a one-entry classification."""
    entry = ClassificationEntry(
        vehicle_index=0, position=1, driver_name="Driver", team_id=0, race_number=1,
        nationality_id=0, is_player=True, grid_position=1, points=25, num_laps=5,
        num_pit_stops=1, best_lap_time_ms=68000, best_lap_num=3, total_race_time_s=280.0,
        penalties_time_s=0, num_penalties=0, result_status=ResultStatus.FINISHED,
        result_reason=_reason(), tyre_stints=(),
    )
    return SessionResult(
        session_uid=uid, season_link_id=1, weekend_link_id=1, session_link_id=1,
        game_format=2026, track_id=7, session_type=SessionType.RACE,
        formula=Formula.F1_MODERN, weather=Weather.CLEAR, total_laps=5, game_mode=19,
        player_vehicle_index=0, classification=Classification(entries=(entry,)),
    )


class DeleteSessionTestBase(unittest.TestCase):
    """One temp database behind a SessionStore and a SeasonStore, as the app runs them."""

    def setUp(self) -> None:
        fd, self._db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        url = f"sqlite:///{self._db}"
        self.sessions = SessionStore(url)
        self.seasons = SeasonStore(url)
        self.addCleanup(os.unlink, self._db)      # cleanups run LIFO: unlink last
        self.addCleanup(self.seasons.close)
        self.addCleanup(self.sessions.close)

    def _season(self, number: int = 1):
        return self.seasons.create_season(SeasonMode.LEAGUE, number, 2026,
                                          rounds=official_calendar(2026))


class DeleteGuardTest(DeleteSessionTestBase):
    def test_refuses_an_assigned_session_and_names_where(self):
        """Core invariant #4 cuts both ways: a delete must not orphan a round placement either."""
        self.sessions.save(_session(1001))
        season = self._season()
        self.seasons.assign_session(1001, season.season_id, 11)

        outcome = delete_session(1001, self.sessions, self.seasons)

        self.assertFalse(outcome.deleted)
        self.assertTrue(outcome.refused_assigned)
        self.assertEqual((outcome.season_id, outcome.round_number), (season.season_id, 11))
        self.assertIsNotNone(self.sessions.load(1001), "a refused delete leaves the session")
        self.assertFalse(self.sessions.is_deleted(1001), "and must not tombstone it")
        self.assertEqual(self.seasons.assignment_for(1001), (season.season_id, 11),
                         "and must leave the placement exactly where it was")

    def test_deletes_once_unassigned(self):
        """The refusal is one Unassign click away from working - not a dead end."""
        self.sessions.save(_session(1002))
        season = self._season()
        self.seasons.assign_session(1002, season.season_id, 4)
        self.assertFalse(delete_session(1002, self.sessions, self.seasons).deleted)

        self.seasons.unassign_session(1002)
        outcome = delete_session(1002, self.sessions, self.seasons)

        self.assertTrue(outcome.deleted)
        self.assertIsNone(self.sessions.load(1002))
        self.assertTrue(self.sessions.is_deleted(1002), "delete still tombstones")

    def test_deletes_an_unassigned_session(self):
        self.sessions.save(_session(1003))
        outcome = delete_session(1003, self.sessions, self.seasons)
        self.assertTrue(outcome.deleted)
        self.assertFalse(outcome.refused_assigned)
        self.assertEqual(outcome.session_uid, 1003)
        self.assertIsNone(self.sessions.load(1003))

    def test_unknown_uid_is_a_clean_no_op(self):
        """Not deleted, not refused, and nothing tombstoned for a uid that was never stored."""
        outcome = delete_session(4242, self.sessions, self.seasons)
        self.assertFalse(outcome.deleted)
        self.assertFalse(outcome.refused_assigned)
        self.assertIsNone(outcome.season_id)
        self.assertEqual(self.sessions.deleted_uids(), set())

    def test_assignment_in_another_season_still_refuses(self):
        """The exact regression: the picker only knew the current round's assignments."""
        self.sessions.save(_session(1004))
        first = self._season(1)
        second = self._season(2)
        self.seasons.assign_session(1004, second.season_id, 2)

        outcome = delete_session(1004, self.sessions, self.seasons)

        self.assertTrue(outcome.refused_assigned)
        self.assertEqual(outcome.season_id, second.season_id)
        self.assertNotEqual(outcome.season_id, first.season_id)


@unittest.skipUnless(_HAS_PYARROW, "pyarrow required for Parquet trace storage")
class DeleteRemovesLapsTest(DeleteSessionTestBase):
    """Nothing else calls ``LapStore.delete``, so a deleted session used to leave its lap rows
    and its Parquet traces behind forever - invisible, because the laps overview iterates
    *stored* sessions, but still in the database and still on disk."""

    def setUp(self) -> None:
        super().setUp()
        self._traces = tempfile.mkdtemp(suffix="_traces")
        self.laps = LapStore(f"sqlite:///{self._db}", trace_dir=self._traces)
        self.addCleanup(shutil.rmtree, self._traces, True)
        self.addCleanup(self.laps.close)

    def test_removes_lap_rows_and_trace_files(self):
        self.sessions.save(_session(1005))
        self.laps.save_laps("1005", (make_lap(1), make_lap(2)))
        trace_dir = Path(self._traces) / "1005"
        self.assertTrue(trace_dir.exists(), "fixture should have written trace files")

        outcome = delete_session(1005, self.sessions, self.seasons, lap_store=self.laps)

        self.assertTrue(outcome.deleted)
        self.assertEqual(outcome.laps_removed, 2)
        self.assertEqual(self.laps.list("1005"), ())
        self.assertFalse(trace_dir.exists(), "traces must not outlive their session")

    def test_refusal_leaves_the_laps_alone(self):
        """The guard runs before anything is removed, so a refusal touches nothing at all."""
        self.sessions.save(_session(1006))
        self.laps.save_laps("1006", (make_lap(1),))
        season = self._season()
        self.seasons.assign_session(1006, season.season_id, 1)

        outcome = delete_session(1006, self.sessions, self.seasons, lap_store=self.laps)

        self.assertTrue(outcome.refused_assigned)
        self.assertEqual(len(self.laps.list("1006")), 1)
        self.assertTrue((Path(self._traces) / "1006").exists())

    def test_delete_without_a_lap_store_still_works(self):
        """lap_store is optional; a caller that has none still gets the session removed."""
        self.sessions.save(_session(1007))
        outcome = delete_session(1007, self.sessions, self.seasons)
        self.assertTrue(outcome.deleted)
        self.assertEqual(outcome.laps_removed, 0)
