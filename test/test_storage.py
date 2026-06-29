from __future__ import annotations

import os
import tempfile
import unittest

from f1telemetry.src.domain.models import (
    Classification, ClassificationEntry, SessionResult, TyreStint,
)
from f1telemetry.src.protocol.enums import (
    Formula, ResultReason, ResultStatus, SessionType, Weather,
)
from f1telemetry.src.storage.sessions import SessionStore


def make_session(uid=0x8000_0000_0000_0000, stype=SessionType.RACE, with_player=True):
    """A session whose uid deliberatly has a high bit set (>2^63)."""
    entries = (
        ClassificationEntry(
            vehicle_index=1, position=1, driver_name="Rival", team_id=0, race_number=50, is_player=False,
            grid_position=1, points=25, num_laps=5, num_pit_stops=1, best_lap_time_ms=67000,
            total_race_time_s=280.1, penalties_time_s=0, num_penalties=0,
            result_status=ResultStatus.FINISHED, result_reason=safe_reason(),
            tyre_stints=(TyreStint(actual_compound="16", visual_compound="16", end_lap=5),)),
        ClassificationEntry(
            vehicle_index=0, position=2, driver_name="Player", team_id=2, race_number=51, is_player=with_player,
            grid_position=3, points=18, num_laps=5, num_pit_stops=2, best_lap_time_ms=68000,
            total_race_time_s=282.4, penalties_time_s=5, num_penalties=1,
            result_status=ResultStatus.FINISHED, result_reason=safe_reason(),
            tyre_stints=(TyreStint(actual_compound="17", visual_compound="16", end_lap=5),
                         TyreStint(actual_compound="18", visual_compound="18", end_lap=5))),
    )
    return SessionResult(
        session_uid=uid, season_link_id=111, weekend_link_id=222, session_link_id=333,
        game_format=2026, track_id=7, session_type=stype, formula=Formula.F1_MODERN,
        weather=Weather.CLEAR, total_laps=5, game_mode=28, player_vehicle_index=0,
        classification=Classification(entries=entries)
    )


def safe_reason():
    # use whatever the "no special reason" member is; fall back to raw 0
    return getattr(ResultReason, "INVALID", None) or getattr(ResultReason, "NONE", 0)


class StorageTestBase(unittest.TestCase):
    """Base class for tests that need a temporary SQLite database."""
    def setUp(self):
        """Create a temporary SQLite database and a SessionStore for it."""
        fd, self._path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.store = SessionStore(f"sqlite:///{self._path}")
        # Cleanups run LIFO, so this registers first / runs last:
        self.addCleanup(os.unlink, self._path)
        self.addCleanup(self.store.close)


class RoundTripTest(StorageTestBase):
    """Test that a session can be saved and loaded without losing data."""
    def test_metadata_round_trips(self):
        """Test that the session metadata is preserved when saving and loading a session."""
        original = make_session()
        self.store.save(original)
        loaded = self.store.load(original.session_uid)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.session_uid, original.session_uid)    # uint64 high-bit set
        self.assertEqual(loaded.session_type, original.session_type)    # enum rehydrated
        self.assertEqual(loaded.game_format, 2026)
        self.assertEqual(
            (loaded.season_link_id, loaded.weekend_link_id, loaded.session_link_id),
            (111, 222, 333))
        

    def test_classification_round_trips(self):
        """Test that the classification data is preserved when saving and loading a session."""
        self.store.save(make_session())
        classification = self.store.load(0x8000_0000_0000_0000).classification
        self.assertEqual([entries.position for entries in classification.entries], [1, 2])
        self.assertEqual(classification.winner.driver_name, "Rival")
        self.assertEqual(classification.winner.points, 25)
        self.assertEqual(classification.player.driver_name, "Player")
        self.assertTrue(classification.player.is_player)
        self.assertEqual(classification.player.race_number, 51)
        self.assertEqual(classification.player.points, 18)
        self.assertEqual(classification.player.result_status, ResultStatus.FINISHED)
        self.assertEqual(classification.player.best_lap_time_ms, 68000)
        self.assertAlmostEqual(classification.player.total_race_time_s, 282.4, places=4)

    def test_tyre_stints_round_trip(self):
        """Test that the tyre stint data is preserved when saving and loading a session."""
        self.store.save(make_session())
        player = self.store.load(0x8000_0000_0000_0000).classification.player
        self.assertEqual(len(player.tyre_stints), 2)
        self.assertEqual(player.tyre_stints[0].actual_compound, "17")
        self.assertEqual(player.tyre_stints[0].visual_compound, "16")
        self.assertEqual(player.tyre_stints[1].end_lap, 5)


class UpsertTest(StorageTestBase):
    """Test that saving a session with the same session_uid replaces the existing entry."""
    def test_resave_replaces_without_dublicating_entries(self):
        self.store.save(make_session())
        # resave the same session_uid with a diffrent points tally for the player
        edited = make_session()
        new_entries = tuple(
            ClassificationEntry(**{**vars(entry), "points": 12}) if entry.is_player else entry
            for entry in edited.classification.entries
        )
        edited2 = SessionResult(**{**vars(edited), "classification": Classification(entries=new_entries)})
        self.store.save(edited2)
        loaded = self.store.load(0x8000_0000_0000_0000)
        self.assertEqual(len(loaded.classification.entries), 2)  # no duplicates
        self.assertEqual(loaded.classification.player.points, 12)  # original points


class ListSessionTest(StorageTestBase):
    """Test that the store can list all saved sessions."""
    def test_lists_all_saved_sessions(self):
        self.store.save(make_session(uid=1001, stype=SessionType.QUALIFYING_1))
        self.store.save(make_session(uid=1002, stype=SessionType.QUALIFYING_2))
        self.store.save(make_session(uid=1003, stype=SessionType.QUALIFYING_3))
        self.store.save(make_session(uid=1004, stype=SessionType.RACE))
        uids = {session.session_uid for session in self.store.list_sessions()}
        self.assertEqual(uids, {1001, 1002, 1003, 1004})


class NoClassificationTest(StorageTestBase):
    """Test that a session without classification can be saved and loaded."""
    def test_session_without_classification_persists_metadata(self):
        session = SessionResult(
            session_uid=555, season_link_id=1, weekend_link_id=2, session_link_id=3,
            game_format=2025, track_id=3, session_type=SessionType.PRACTICE_1,
            formula=Formula.F1_MODERN, weather=Weather.CLEAR, total_laps=0,
            game_mode=27, player_vehicle_index=0)     # classification defaults to None
        self.store.save(session)
        loaded = self.store.load(555)
        self.assertIsNotNone(loaded)
        self.assertIsNone(loaded.classification)
        self.assertEqual(loaded.session_type, SessionType.PRACTICE_1)
        self.assertEqual(loaded.game_mode, 27)


if __name__ == "__main__":
    unittest.main()