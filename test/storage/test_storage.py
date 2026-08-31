from __future__ import annotations

import dataclasses
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from f1telemetry.src.domain.models import (
    Classification, ClassificationEntry, SessionResult, TyreStint,
)
from f1telemetry.src.protocol.enums import (
    Formula, ResultReason, ResultStatus, SessionType, Weather,
)
from f1telemetry.src.storage.sessions import DeletedSession, SessionStore


def make_session(uid=0x8000_0000_0000_0000, stype=SessionType.RACE, with_player=True):
    """A session whose uid deliberatly has a high bit set (>2^63)."""
    entries = (
        ClassificationEntry(
            vehicle_index=1, position=1, driver_name="Rival", team_id=0, race_number=50,
            nationality_id=10, is_player=False,
            grid_position=1, points=25, num_laps=5, num_pit_stops=1, best_lap_time_ms=67000,
            best_lap_num=4, total_race_time_s=280.1, penalties_time_s=0, num_penalties=0,
            result_status=ResultStatus.FINISHED, result_reason=safe_reason(),
            tyre_stints=(TyreStint(actual_compound="16", visual_compound="16", end_lap=5),),
            is_ai=True),
        ClassificationEntry(
            vehicle_index=0, position=2, driver_name="Player", team_id=2, race_number=51,
            nationality_id=8, is_player=with_player,
            grid_position=3, points=18, num_laps=5, num_pit_stops=2, best_lap_time_ms=68000,
            best_lap_num=7, total_race_time_s=282.4, penalties_time_s=5, num_penalties=1,
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


def _utc(value: datetime | None) -> datetime | None:
    """SQLite hands datetimes back naive; compare them as the UTC they were written as."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


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
        self.assertEqual(classification.player.nationality_id, 8)
        self.assertEqual(classification.winner.nationality_id, 10)
        self.assertEqual(classification.player.points, 18)
        self.assertEqual(classification.player.result_status, ResultStatus.FINISHED)
        self.assertEqual(classification.player.best_lap_time_ms, 68000)
        self.assertEqual(classification.player.best_lap_num, 7)
        self.assertAlmostEqual(classification.player.total_race_time_s, 282.4, places=4)

    def test_tyre_stints_round_trip(self):
        """Test that the tyre stint data is preserved when saving and loading a session."""
        self.store.save(make_session())
        player = self.store.load(0x8000_0000_0000_0000).classification.player
        self.assertEqual(len(player.tyre_stints), 2)
        self.assertEqual(player.tyre_stints[0].actual_compound, "17")
        self.assertEqual(player.tyre_stints[0].visual_compound, "16")
        self.assertEqual(player.tyre_stints[1].end_lap, 5)

    def test_weekend_structure_round_trips(self):
        """The weekend structure survives save/load as a tuple (empty stays empty)."""
        structure = (1, 10, 11, 12, 15, 5, 6, 7, 15)
        with_structure = SessionResult(**{**vars(make_session()), "weekend_structure": structure})
        self.store.save(with_structure)
        loaded = self.store.load(0x8000_0000_0000_0000)
        self.assertEqual(loaded.weekend_structure, structure)
        self.assertIsInstance(loaded.weekend_structure, tuple)

        self.store.save(make_session(uid=0x1234))   # default: no structure captured
        self.assertEqual(self.store.load(0x1234).weekend_structure, ())

    def test_weather_seen_round_trips(self):
        """The conditions a session ran through survive save/load, and drive `is_mixed_weather`.

        Stored as raw ints and read back through safe_enum, like every other enum (invariant #9).
        A row saved without one comes back with an empty tuple - "not captured", not "not mixed".
        """
        seen = (Weather.LIGHT_RAIN, Weather.OVERCAST)
        mixed = SessionResult(**{**vars(make_session()), "weather_seen": seen})
        self.store.save(mixed)
        loaded = self.store.load(0x8000_0000_0000_0000)
        self.assertEqual(loaded.weather_seen, seen)
        self.assertIsInstance(loaded.weather_seen, tuple)
        self.assertTrue(loaded.is_mixed_weather)
        self.assertEqual(loaded.weather, Weather.CLEAR)     # the snapshot is untouched

        self.store.save(make_session(uid=0x1234))   # default: no set captured
        again = self.store.load(0x1234)
        self.assertEqual(again.weather_seen, ())
        self.assertFalse(again.is_mixed_weather)

    def test_track_geometry_round_trip(self):
        """The track length + sector start-distances survive save/load; absent stays None."""
        with_sectors = SessionResult(**{**vars(make_session()), "track_length_m": 5891,
                                         "sector2_start_m": 1200.0, "sector3_start_m": 3400.0})
        self.store.save(with_sectors)
        loaded = self.store.load(0x8000_0000_0000_0000)
        self.assertEqual(loaded.track_length_m, 5891)
        self.assertEqual((loaded.sector2_start_m, loaded.sector3_start_m), (1200.0, 3400.0))
        self.store.save(make_session(uid=0x1234))   # default: no sector info captured
        again = self.store.load(0x1234)
        self.assertEqual((again.sector2_start_m, again.sector3_start_m), (None, None))

    def test_is_ai_round_trips(self):
        """AI-vs-human must survive storage: league standings key on it (PIPELINE_VERSION 2)."""
        self.store.save(make_session())
        entries = self.store.load(0x8000_0000_0000_0000).classification.entries
        self.assertEqual([entry.is_ai for entry in entries], [True, False])



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


class DeleteTest(StorageTestBase):
    """Test that a saved session (and its entries) can be deleted by uid."""
    def test_delete_removes_session_and_entries(self):
        self.store.save(make_session(uid=1001, stype=SessionType.PRACTICE_1))
        self.store.save(make_session(uid=1002, stype=SessionType.RACE))
        self.assertTrue(self.store.delete(1001))
        self.assertIsNone(self.store.load(1001))                 # gone
        self.assertIsNotNone(self.store.load(1002))              # sibling untouched
        self.assertEqual({s.session_uid for s in self.store.list_sessions()}, {1002})

    def test_delete_missing_uid_returns_false(self):
        self.assertFalse(self.store.delete(4242))


class TombstoneTest(StorageTestBase):
    """Deleting a session records a tombstone so re-saving/re-ingesting can skip it."""

    def test_delete_tombstones_the_uid(self):
        self.store.save(make_session(uid=1001))
        self.assertFalse(self.store.is_deleted(1001))
        self.store.delete(1001)
        self.assertTrue(self.store.is_deleted(1001))
        self.assertIn(1001, self.store.deleted_uids())

    def test_deleting_missing_uid_leaves_no_tombstone(self):
        self.assertFalse(self.store.delete(4242))
        self.assertEqual(self.store.deleted_uids(), set())

    def test_restore_clears_the_tombstone(self):
        self.store.save(make_session(uid=1001))
        self.store.delete(1001)
        self.assertTrue(self.store.restore(1001))
        self.assertFalse(self.store.is_deleted(1001))
        self.assertFalse(self.store.restore(1001))    # already cleared -> False

    def test_tombstone_survives_uint64_high_bit(self):
        big = 0x8000_0000_0000_0000
        self.store.save(make_session(uid=big))
        self.store.delete(big)
        self.assertIn(big, self.store.deleted_uids())

    def test_delete_records_what_the_session_was(self):
        """The tombstone is descriptive on purpose: the deleted-sessions view has no capture to
        read, so whatever it shows has to have been copied off the row as it went."""
        recorded = datetime(2026, 8, 9, 21, 2, tzinfo=timezone.utc)
        session = dataclasses.replace(
            make_session(uid=1001, stype=SessionType.QUALIFYING_1), recorded_at=recorded)
        self.store.save(session)

        before = datetime.now(timezone.utc)
        self.store.delete(1001)

        tomb = self.store.deleted_sessions()[0]
        self.assertEqual(tomb.session_uid, 1001)
        self.assertEqual(tomb.track_id, 7)
        self.assertEqual(tomb.session_type, SessionType.QUALIFYING_1)
        self.assertEqual(_utc(tomb.recorded_at), recorded)
        self.assertGreaterEqual(_utc(tomb.deleted_at), before - timedelta(seconds=5))

    def test_tombstone_writes_without_a_session_row(self):
        """The primitive ``delete`` cannot be: it writes nothing when the row is already gone,
        which is exactly the state a rolled-back restore has to recover from."""
        self.assertFalse(self.store.delete(2001), "no row to delete")

        self.store.tombstone(2001, track_id=3, session_type=SessionType.RACE)

        self.assertTrue(self.store.is_deleted(2001))
        self.assertIn(2001, self.store.deleted_uids())
        tomb = self.store.deleted_sessions()[0]
        self.assertEqual((tomb.track_id, tomb.session_type), (3, SessionType.RACE))
        self.assertIsNone(tomb.recorded_at, "a tombstone may know nothing but the uid")

    def test_tombstone_is_idempotent_and_overwrites_the_description(self):
        """A merge, so re-tombstoning a uid refreshes it rather than failing on the primary key."""
        self.store.tombstone(2002, track_id=3, session_type=SessionType.RACE)
        self.store.tombstone(2002, track_id=9, session_type=SessionType.PRACTICE_2)

        self.assertEqual(len(self.store.deleted_sessions()), 1)
        tomb = self.store.deleted_sessions()[0]
        self.assertEqual((tomb.track_id, tomb.session_type), (9, SessionType.PRACTICE_2))

    def test_tombstone_can_put_the_original_deletion_time_back(self):
        """``deleted_at`` is settable so a failed restore doesn't re-date the deletion - the
        view must not read "deleted just now" because a restore fell over."""
        original = datetime(2026, 8, 10, 9, 14, tzinfo=timezone.utc)
        self.store.tombstone(2003, track_id=1, session_type=SessionType.RACE,
                             deleted_at=original)

        self.assertEqual(_utc(self.store.deleted_sessions()[0].deleted_at), original)

    def test_tombstone_keeps_a_session_type_newer_than_our_enum(self):
        """Enums are stored raw and read via safe_enum (core invariant #9), so a title update
        that adds a session type doesn't crash the deleted-sessions view."""
        self.store.tombstone(2004, track_id=1, session_type=250)
        self.assertEqual(self.store.deleted_sessions()[0].session_type, 250)


class DeletedSessionsTest(StorageTestBase):
    """``deleted_sessions()`` - the descriptive read ``deleted_uids()`` cannot feed."""

    def test_lists_nothing_when_nothing_was_deleted(self):
        self.assertEqual(self.store.deleted_sessions(), [])

    def test_lists_most_recently_deleted_first(self):
        self.store.tombstone(1, deleted_at=datetime(2026, 8, 1, tzinfo=timezone.utc))
        self.store.tombstone(2, deleted_at=datetime(2026, 8, 20, tzinfo=timezone.utc))
        self.store.tombstone(3, deleted_at=datetime(2026, 8, 10, tzinfo=timezone.utc))

        self.assertEqual([tomb.session_uid for tomb in self.store.deleted_sessions()], [2, 3, 1])

    def test_rows_are_the_read_model_not_the_orm_row(self):
        self.store.save(make_session(uid=1001))
        self.store.delete(1001)
        self.assertIsInstance(self.store.deleted_sessions()[0], DeletedSession)

    def test_restoring_removes_the_row(self):
        self.store.save(make_session(uid=1001))
        self.store.delete(1001)
        self.store.restore(1001)

        self.assertEqual(self.store.deleted_sessions(), [])
        self.assertFalse(self.store.is_deleted(1001))

    def test_reads_a_uint64_high_bit_uid_back_as_an_int(self):
        big = 0x8000_0000_0000_0000
        self.store.tombstone(big, track_id=1)
        self.assertEqual(self.store.deleted_sessions()[0].session_uid, big)


class EnsureSchemaLapsTest(unittest.TestCase):
    """The lap-context columns arrive on an existing database the same additive way.

    Separate from the entries case above because the *back-fill* differs and the difference is the
    point: ``nationality_id`` carries a DEFAULT so old rows get 0, while these are nullable with no
    default, so an old lap reads back NULL. That is what lets the charts tell "the game said the car
    was on track" from "this lap predates the field" (domain ``Lap.has_lap_context``).
    """

    def test_adds_the_lap_context_columns_and_leaves_old_rows_null(self):
        from sqlalchemy import create_engine, inspect, text

        from f1telemetry.src.storage.migrations import ensure_schema

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(os.unlink, path)
        engine = create_engine(f"sqlite:///{path}")
        self.addCleanup(engine.dispose)

        # a pre-E17 database: the laps table exactly as PIPELINE_VERSION 3 left it
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE laps ("
                "id INTEGER PRIMARY KEY, session_uid TEXT, lap_number INTEGER, lap_time_ms INTEGER, "
                "sector1_ms INTEGER, sector2_ms INTEGER, sector3_ms INTEGER, is_valid BOOLEAN, "
                "trace_path TEXT, tyre_actual_compound INTEGER, tyre_visual_compound INTEGER, "
                "tyre_age_laps INTEGER, tyre_wear JSON, tyre_damage JSON, tyre_blisters JSON, "
                "tyre_surface_temp JSON, tyre_carcass_temp JSON, damage JSON, fuel_in_tank FLOAT)"))
            conn.execute(text(
                "INSERT INTO laps (id, session_uid, lap_number, is_valid) VALUES (1, '7', 1, 1)"))

        ensure_schema(engine)
        ensure_schema(engine)   # idempotent: a second run is a no-op, not an error

        added = ("driver_status", "pit_status", "preceded_by_garage", "is_out_lap",
                 "is_in_lap", "safety_car", "red_flagged")
        cols = {c["name"] for c in inspect(engine).get_columns("laps")}
        for column in added:
            with self.subTest(column=column):
                self.assertIn(column, cols)
        with engine.begin() as conn:
            row = conn.execute(
                text(f"SELECT {', '.join(added)} FROM laps WHERE id = 1")).one()
        for column, value in zip(added, row):
            with self.subTest(column=column):
                self.assertIsNone(value)    # never captured - not a coerced 0 or False


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