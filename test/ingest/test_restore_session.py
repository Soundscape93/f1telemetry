"""``pipeline.restore_session`` - bringing a deleted session back, or refusing honestly.

Restore is a *single-capture re-ingest*, not a cleared tombstone: ``ingest_capture`` replaces by
uid, so ingesting one file that holds the uid is sufficient and idempotent. The risk is entirely
in the ordering. ``ingest_capture`` reads ``deleted_uids()`` at the start, so the tombstone has to
be cleared **before** the ingest - which opens a window where the uid is un-tombstoned with no
session row, the state in which the next *full* re-ingest silently resurrects a session the user
believes is deleted. The rollback tests are therefore the point of this file: a restore either
completes or leaves the database exactly as it found it.

Fixture-free: ``ingest`` is injected (the same style as ``reingest_all``'s), so the ordering, the
verification and the rollback are exercised without a real multi-hundred-MB archive. Real parse ->
assemble -> persist is covered by test_ingest_pipeline and test_archive_and_ingest.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone

from f1telemetry.src.domain.captures import CaptureMeta
from f1telemetry.src.domain.models import SessionResult
from f1telemetry.src.pipeline import (RestoreOutcome, RestoreProblem, restorable_captures,
                                      restore_session)
from f1telemetry.src.protocol.enums import Formula, SessionType, Weather
from f1telemetry.src.storage.captures import CaptureStore
from f1telemetry.src.storage.sessions import SessionStore


def _session(uid: int, track_id: int = 7,
             stype: SessionType = SessionType.RACE) -> SessionResult:
    """A minimal stored session - identity and the fields a tombstone describes."""
    return SessionResult(
        session_uid=uid, season_link_id=1, weekend_link_id=1, session_link_id=1,
        game_format=2026, track_id=track_id, session_type=stype,
        formula=Formula.F1_26, weather=Weather.CLEAR, total_laps=5,
        game_mode=19, player_vehicle_index=0,
        recorded_at=datetime(2026, 8, 9, 21, 2, tzinfo=timezone.utc),
    )


def _utc(value: datetime | None) -> datetime | None:
    """SQLite hands datetimes back naive; compare them as the UTC they were written as."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


class _FakeIngest:
    """A stand-in for ``ingest_capture``: saves what a capture "holds", and can fall over.

    It saves through the real store rather than only returning sessions, so "was the session
    actually restored?" and "was the row rolled back?" are read from the database, not from the
    double. ``fails_late`` is the case a naive rollback misses: a capture holding several sessions
    where ours was saved before a later one raised, leaving a resurrected row *and* a cleared
    tombstone.
    """

    def __init__(self, holdings: dict[str, list[SessionResult]], *,
                 fails: set[str] = frozenset(), fails_late: set[str] = frozenset()) -> None:
        self.holdings = holdings
        self.fails = fails
        self.fails_late = fails_late
        self.calls: list[tuple[str, str | None]] = []

    def __call__(self, path, store, lap_store=None, capture_store=None, recorded_by=None):
        name = os.path.basename(path)
        self.calls.append((path, recorded_by))
        if name in self.fails:
            raise RuntimeError("corrupt archive")      # blew up before anything was written
        saved = []
        for session in self.holdings.get(name, []):
            store.save(session)
            if lap_store is not None:
                lap_store.save_laps(session.session_uid, ())
            saved.append(session)
        if name in self.fails_late:
            raise RuntimeError("a later session in this capture failed")
        return saved


class _FakeLapStore:
    """Records the lap writes and deletes a restore drives, without pyarrow or Parquet."""

    def __init__(self) -> None:
        self.saved: list[str] = []
        self.deleted: list[str] = []

    def save_laps(self, session_uid, laps) -> None:
        self.saved.append(str(session_uid))

    def delete(self, session_uid) -> int:
        self.deleted.append(str(session_uid))
        return 0


class RestoreTestBase(unittest.TestCase):
    """One temp database behind a SessionStore and a CaptureStore, plus a captures folder."""

    def setUp(self) -> None:
        self.temp = tempfile.mkdtemp(prefix="restore_")
        self.addCleanup(lambda: shutil.rmtree(self.temp, ignore_errors=True))
        self.captures_dir = os.path.join(self.temp, "captures")
        os.makedirs(self.captures_dir)

        url = f"sqlite:///{os.path.join(self.temp, 'test.db')}"
        self.sessions = SessionStore(url)
        self.captures = CaptureStore(url)
        self.addCleanup(self.captures.close)
        self.addCleanup(self.sessions.close)
        self.laps = _FakeLapStore()

    # --- fixtures ----------------------------------------------------------
    def _capture(self, name: str, uids: tuple[int, ...], *, on_disk: bool = True,
                 recorded_by: str | None = None, ingested_at: datetime | None = None) -> CaptureMeta:
        """Record a capture holding ``uids``, optionally writing its (empty) archive to disk."""
        path = os.path.join(self.captures_dir, name)
        if on_disk:
            with open(path, "wb") as fh:
                fh.write(b"")
        meta = CaptureMeta(
            content_hash=name.ljust(64, "0"), path=path, file_name=name,
            file_size=1_000, payload_size=10_000, codec="zstd", packet_count=42,
            session_uids=tuple(str(uid) for uid in uids), recorded_by=recorded_by,
            ingested_at=ingested_at or datetime(2026, 7, 25, tzinfo=timezone.utc),
        )
        self.captures.record(meta)
        return meta

    def _deleted(self, uid: int, **kwargs) -> None:
        """Store a session and delete it, so the uid starts the test genuinely tombstoned."""
        self.sessions.save(_session(uid, **kwargs))
        self.assertTrue(self.sessions.delete(uid))

    def _tombstone(self, uid: int):
        return next((row for row in self.sessions.deleted_sessions()
                     if row.session_uid == uid), None)


class RestoreHappyPathTest(RestoreTestBase):
    """The whole point: the session comes back and the tombstone goes."""

    def test_restores_from_the_one_capture_that_holds_it(self):
        self._deleted(1001)
        self._capture("cap_a.f1cap.zst", (1001,), recorded_by="Alex")
        ingest = _FakeIngest({"cap_a.f1cap.zst": [_session(1001)]})

        outcome = restore_session(1001, self.sessions, self.captures, lap_store=self.laps,
                                  captures_dir=self.captures_dir, ingest=ingest)

        self.assertIsInstance(outcome, RestoreOutcome)
        self.assertTrue(outcome.restored)
        self.assertEqual(outcome.session_uid, 1001)
        self.assertEqual(outcome.capture_name, "cap_a.f1cap.zst")
        self.assertIsNone(outcome.reason)
        self.assertIsNotNone(self.sessions.load(1001), "the session is back")
        self.assertFalse(self.sessions.is_deleted(1001), "and its tombstone is gone")
        self.assertEqual(self.sessions.deleted_sessions(), [])

    def test_rebuilds_the_laps_and_feeds_recorded_by_back(self):
        """``recorded_by`` isn't in the capture file, so passing it back is the only thing that
        keeps a restore from erasing it - the same rule as a re-ingest."""
        self._deleted(1002)
        self._capture("cap_b.f1cap.zst", (1002,), recorded_by="Sam")
        ingest = _FakeIngest({"cap_b.f1cap.zst": [_session(1002)]})

        restore_session(1002, self.sessions, self.captures, lap_store=self.laps,
                        captures_dir=self.captures_dir, ingest=ingest)

        self.assertEqual(self.laps.saved, ["1002"])
        self.assertEqual(ingest.calls[0][1], "Sam")

    def test_finds_the_archive_through_the_captures_folder_when_the_path_is_stale(self):
        """``CaptureRow.path`` is advisory - a data root that moved is the case that happens."""
        self._deleted(1003)
        meta = self._capture("cap_c.f1cap.zst", (1003,))
        self.captures.relocate(meta.content_hash, "/gone/cap_c.f1cap.zst", 1_000, "zstd")
        ingest = _FakeIngest({"cap_c.f1cap.zst": [_session(1003)]})

        outcome = restore_session(1003, self.sessions, self.captures,
                                  captures_dir=self.captures_dir, ingest=ingest)

        self.assertTrue(outcome.restored)

    def test_restores_a_uint64_high_bit_uid(self):
        big = 0x8000_0000_0000_0000
        self._deleted(big)
        self._capture("cap_big.f1cap.zst", (big,))
        ingest = _FakeIngest({"cap_big.f1cap.zst": [_session(big)]})

        outcome = restore_session(big, self.sessions, self.captures,
                                  captures_dir=self.captures_dir, ingest=ingest)

        self.assertTrue(outcome.restored)
        self.assertIsNotNone(self.sessions.load(big))


class RestoreRollbackTest(RestoreTestBase):
    """The failure this design exists to prevent: a cleared tombstone with no session row.

    The tombstone has to be cleared before the ingest (``ingest_capture`` reads ``deleted_uids()``
    up front), so every failure after that point must put it back - otherwise the next *full*
    re-ingest silently resurrects a session the user believes is deleted, and nothing in the UI
    ever says so.
    """

    def test_ingest_failure_re_tombstones_the_uid(self):
        self._deleted(2001)
        self._capture("bad.f1cap.zst", (2001,))
        ingest = _FakeIngest({}, fails={"bad.f1cap.zst"})

        with self.assertLogs("f1telemetry.src.pipeline", level="ERROR"):
            outcome = restore_session(2001, self.sessions, self.captures, lap_store=self.laps,
                                      captures_dir=self.captures_dir, ingest=ingest)

        self.assertFalse(outcome.restored)
        self.assertIs(outcome.reason, RestoreProblem.INGEST_FAILED)
        self.assertEqual(outcome.capture_name, "bad.f1cap.zst")
        self.assertIn("corrupt archive", outcome.error)
        self.assertTrue(self.sessions.is_deleted(2001), "the tombstone must come back")
        self.assertIn(2001, self.sessions.deleted_uids(), "or a full re-ingest resurrects it")
        self.assertIsNone(self.sessions.load(2001), "and no half-restored row is left behind")

    def test_the_rolled_back_tombstone_is_the_one_that_was_there(self):
        """Field-for-field, ``deleted_at`` included: a failed restore is not a new deletion, and
        the deleted-sessions view must not re-date it."""
        self._deleted(2002, track_id=12, stype=SessionType.QUALIFYING_2)
        before = self._tombstone(2002)
        self._capture("bad2.f1cap.zst", (2002,))
        ingest = _FakeIngest({}, fails={"bad2.f1cap.zst"})

        with self.assertLogs("f1telemetry.src.pipeline", level="ERROR"):
            restore_session(2002, self.sessions, self.captures, captures_dir=self.captures_dir,
                            ingest=ingest)

        after = self._tombstone(2002)
        self.assertEqual(after.track_id, before.track_id)
        self.assertEqual(after.session_type, before.session_type)
        self.assertEqual(_utc(after.recorded_at), _utc(before.recorded_at))
        self.assertEqual(_utc(after.deleted_at), _utc(before.deleted_at))

    def test_a_row_saved_before_the_failure_is_taken_back_out(self):
        """One capture, several sessions: ours saved, a later one raised. The tombstone alone
        wouldn't be enough here - a resurrected row would sit in Sessions *and* in the deleted
        list at the same time."""
        self._deleted(2003)
        self._capture("late.f1cap.zst", (2003,))
        ingest = _FakeIngest({"late.f1cap.zst": [_session(2003)]}, fails_late={"late.f1cap.zst"})

        with self.assertLogs("f1telemetry.src.pipeline", level="ERROR"):
            outcome = restore_session(2003, self.sessions, self.captures, lap_store=self.laps,
                                      captures_dir=self.captures_dir, ingest=ingest)

        self.assertFalse(outcome.restored)
        self.assertIs(outcome.reason, RestoreProblem.INGEST_FAILED)
        self.assertIsNone(self.sessions.load(2003), "the resurrected row goes back out")
        self.assertTrue(self.sessions.is_deleted(2003))
        self.assertEqual(self.laps.deleted, ["2003"], "and its laps go with it, as a delete does")

    def test_a_capture_that_does_not_hold_the_uid_rolls_back(self):
        """``capture_sessions`` rows go stale - pruned, re-recorded, or written by an older
        ingest. Trusting the row that pointed here would leave a cleared tombstone and no
        session, which is exactly the half-state the rollback exists for."""
        self._deleted(2004)
        self._capture("stale.f1cap.zst", (2004,))          # the row claims it; the file doesn't
        ingest = _FakeIngest({"stale.f1cap.zst": [_session(9999)]})

        outcome = restore_session(2004, self.sessions, self.captures, lap_store=self.laps,
                                  captures_dir=self.captures_dir, ingest=ingest)

        self.assertFalse(outcome.restored)
        self.assertIs(outcome.reason, RestoreProblem.NOT_IN_CAPTURE)
        self.assertEqual(outcome.capture_name, "stale.f1cap.zst")
        self.assertTrue(self.sessions.is_deleted(2004))
        self.assertIsNone(self.sessions.load(2004))
        self.assertEqual(self.laps.deleted, [], "nothing of ours was written, so nothing to undo")

    def test_other_sessions_from_the_same_capture_are_left_alone(self):
        """The rollback is for the uid being restored, not for the capture: sessions the ingest
        legitimately refreshed on the way past are not collateral."""
        self._deleted(2005)
        self._capture("shared.f1cap.zst", (2005, 8888))
        ingest = _FakeIngest({"shared.f1cap.zst": [_session(8888)]})   # ours is missing from it

        restore_session(2005, self.sessions, self.captures, captures_dir=self.captures_dir,
                        ingest=ingest)

        self.assertTrue(self.sessions.is_deleted(2005))
        self.assertIsNotNone(self.sessions.load(8888), "the capture's other session stays")
        self.assertFalse(self.sessions.is_deleted(8888))


class RestoreRefusalTest(RestoreTestBase):
    """The refusals that happen *before* the tombstone is touched - it must survive all of them."""

    def test_a_missing_archive_is_refused_and_names_the_file(self):
        """Fail honestly: the row stays in the manager and the user can go looking for the file
        (Help -> Find moved captures...) rather than being told a lie either way.

        Wrapped in ``assertLogs`` on purpose. ``logging`` swallows a format-string/argument
        mismatch and prints it to stderr, so a broken log call on this path stayed invisible to the
        suite until a user found it in their log file; ``assertLogs`` renders each record, which
        raises on the mismatch instead.
        """
        self._deleted(3001)
        self._capture("gone.f1cap.zst", (3001,), on_disk=False)
        ingest = _FakeIngest({"gone.f1cap.zst": [_session(3001)]})

        with self.assertLogs("f1telemetry.src.pipeline", level="INFO") as logged:
            outcome = restore_session(3001, self.sessions, self.captures,
                                      captures_dir=self.captures_dir, ingest=ingest)

        self.assertFalse(outcome.restored)
        self.assertIs(outcome.reason, RestoreProblem.ARCHIVE_MISSING)
        self.assertEqual(outcome.capture_name, "gone.f1cap.zst")
        self.assertEqual(ingest.calls, [], "nothing was ingested")
        self.assertTrue(self.sessions.is_deleted(3001), "and the tombstone was never touched")
        self.assertTrue(any("gone.f1cap.zst" in line and "3001" in line for line in logged.output),
                        f"the log line must name both the file and the session: {logged.output}")

    def test_no_capture_row_at_all_is_a_different_answer(self):
        """Pruned, or ingested before ``capture_store`` was wired: restore is impossible *ever*,
        so the manager has to offer Forget instead of a retry that cannot work."""
        self._deleted(3002)
        ingest = _FakeIngest({})

        outcome = restore_session(3002, self.sessions, self.captures,
                                  captures_dir=self.captures_dir, ingest=ingest)

        self.assertIs(outcome.reason, RestoreProblem.NO_CAPTURE_ROW)
        self.assertEqual(outcome.capture_name, "", "there is no file to name")
        self.assertEqual(ingest.calls, [])
        self.assertTrue(self.sessions.is_deleted(3002))

    def test_a_session_that_is_not_deleted_is_left_alone(self):
        """The early-out. Nothing to restore, and - more to the point - a live session must not
        be re-ingested behind the user's back by a stale button."""
        self.sessions.save(_session(3003))
        ingest = _FakeIngest({"anything.f1cap.zst": [_session(3003)]})
        self._capture("anything.f1cap.zst", (3003,))

        outcome = restore_session(3003, self.sessions, self.captures,
                                  captures_dir=self.captures_dir, ingest=ingest)

        self.assertFalse(outcome.restored)
        self.assertIs(outcome.reason, RestoreProblem.NOT_DELETED)
        self.assertEqual(ingest.calls, [])
        self.assertIsNotNone(self.sessions.load(3003))

    def test_an_unknown_uid_is_refused_as_not_deleted(self):
        outcome = restore_session(4242, self.sessions, self.captures,
                                  captures_dir=self.captures_dir, ingest=_FakeIngest({}))
        self.assertIs(outcome.reason, RestoreProblem.NOT_DELETED)


class RestoreCaptureChoiceTest(RestoreTestBase):
    """Two captures can hold one session - a member's original and an imported copy. They can
    differ in completeness (someone stopped recording early) and nothing here can tell which is
    better without decompressing both, so a silent guess would quietly pick the worse recording."""

    def _two_captures(self, uid: int) -> tuple[CaptureMeta, CaptureMeta]:
        older = self._capture("older.f1cap.zst", (uid,), recorded_by="Alex",
                              ingested_at=datetime(2026, 7, 1, tzinfo=timezone.utc))
        newer = self._capture("newer.f1cap.zst", (uid,), recorded_by="Sam",
                              ingested_at=datetime(2026, 8, 1, tzinfo=timezone.utc))
        return older, newer

    def test_two_findable_captures_are_refused_rather_than_guessed(self):
        self._deleted(5001)
        self._two_captures(5001)
        ingest = _FakeIngest({"older.f1cap.zst": [_session(5001)],
                              "newer.f1cap.zst": [_session(5001)]})

        outcome = restore_session(5001, self.sessions, self.captures,
                                  captures_dir=self.captures_dir, ingest=ingest)

        self.assertIs(outcome.reason, RestoreProblem.AMBIGUOUS_CAPTURE)
        self.assertEqual(ingest.calls, [], "the caller has to choose first")
        self.assertTrue(self.sessions.is_deleted(5001), "and the tombstone is untouched")

    def test_a_content_hash_picks_one(self):
        self._deleted(5002)
        older, _newer = self._two_captures(5002)
        ingest = _FakeIngest({"older.f1cap.zst": [_session(5002)],
                              "newer.f1cap.zst": [_session(5002)]})

        outcome = restore_session(5002, self.sessions, self.captures,
                                  captures_dir=self.captures_dir,
                                  content_hash=older.content_hash, ingest=ingest)

        self.assertTrue(outcome.restored)
        self.assertEqual(outcome.capture_name, "older.f1cap.zst")
        self.assertEqual([os.path.basename(path) for path, _ in ingest.calls],
                         ["older.f1cap.zst"], "only the chosen file is read")

    def test_only_one_findable_capture_needs_no_choosing(self):
        """The chooser is for real choices: if the other copy's archive is gone there is one
        answer, and asking would be noise."""
        self._deleted(5003)
        self._capture("here.f1cap.zst", (5003,))
        self._capture("elsewhere.f1cap.zst", (5003,), on_disk=False)
        ingest = _FakeIngest({"here.f1cap.zst": [_session(5003)]})

        outcome = restore_session(5003, self.sessions, self.captures,
                                  captures_dir=self.captures_dir, ingest=ingest)

        self.assertTrue(outcome.restored)
        self.assertEqual(outcome.capture_name, "here.f1cap.zst")

    def test_a_chosen_capture_whose_archive_is_gone_says_so(self):
        """The chooser can go stale between listing and confirming - the file may be renamed while
        the dialog is open. That is the missing-archive answer, not an ambiguity."""
        self._deleted(5004)
        self._capture("here2.f1cap.zst", (5004,))
        gone = self._capture("gone2.f1cap.zst", (5004,), on_disk=False)
        ingest = _FakeIngest({"here2.f1cap.zst": [_session(5004)]})

        outcome = restore_session(5004, self.sessions, self.captures,
                                  captures_dir=self.captures_dir,
                                  content_hash=gone.content_hash, ingest=ingest)

        self.assertIs(outcome.reason, RestoreProblem.ARCHIVE_MISSING)
        self.assertEqual(outcome.capture_name, "gone2.f1cap.zst")
        self.assertEqual(ingest.calls, [])
        self.assertTrue(self.sessions.is_deleted(5004))

    def test_a_content_hash_no_capture_holds_is_refused(self):
        """A hash from a row that has since been pruned: there is no file, so this is the
        no-capture answer rather than a silent fall-back to the other copy."""
        self._deleted(5005)
        self._capture("kept.f1cap.zst", (5005,))
        ingest = _FakeIngest({"kept.f1cap.zst": [_session(5005)]})

        outcome = restore_session(5005, self.sessions, self.captures,
                                  captures_dir=self.captures_dir,
                                  content_hash="f" * 64, ingest=ingest)

        self.assertIs(outcome.reason, RestoreProblem.NO_CAPTURE_ROW)
        self.assertEqual(ingest.calls, [])
        self.assertTrue(self.sessions.is_deleted(5005))


class RestorableCapturesTest(RestoreTestBase):
    """The shared resolution rule: what the chooser offers *is* what restore will accept."""

    def test_lists_findable_captures_newest_ingest_first(self):
        self._capture("old.f1cap.zst", (6001,), ingested_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
        self._capture("new.f1cap.zst", (6001,), ingested_at=datetime(2026, 8, 1, tzinfo=timezone.utc))
        self._capture("mid.f1cap.zst", (6001,), ingested_at=datetime(2026, 7, 1, tzinfo=timezone.utc))

        found = restorable_captures(6001, self.captures, self.captures_dir)

        self.assertEqual([meta.file_name for meta, _path in found],
                         ["new.f1cap.zst", "mid.f1cap.zst", "old.f1cap.zst"])
        self.assertTrue(all(os.path.isfile(path) for _meta, path in found))

    def test_leaves_out_the_ones_whose_archive_is_gone(self):
        self._capture("present.f1cap.zst", (6002,))
        self._capture("absent.f1cap.zst", (6002,), on_disk=False)

        found = restorable_captures(6002, self.captures, self.captures_dir)

        self.assertEqual([meta.file_name for meta, _path in found], ["present.f1cap.zst"])

    def test_is_empty_for_a_session_no_capture_mentions(self):
        self.assertEqual(restorable_captures(6003, self.captures, self.captures_dir), [])

    def test_an_unstamped_row_sorts_last_rather_than_crashing(self):
        """``ingested_at`` is nullable; a row written before it was recorded must not blow up the
        chooser it appears in."""
        self._capture("stamped.f1cap.zst", (6004,), ingested_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        self._capture("unstamped.f1cap.zst", (6004,), ingested_at=None)
        # CaptureStore stamps a missing ingested_at at write time, so blank one out directly
        with self.captures._Session.begin() as db:      # a state no writer of ours produces
            from f1telemetry.src.storage.schema import CaptureRow
            db.get(CaptureRow, "unstamped.f1cap.zst".ljust(64, "0")).ingested_at = None

        found = restorable_captures(6004, self.captures, self.captures_dir)

        self.assertEqual([meta.file_name for meta, _path in found],
                         ["stamped.f1cap.zst", "unstamped.f1cap.zst"])


if __name__ == "__main__":
    unittest.main()
