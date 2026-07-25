"""The Phase-2 guided re-ingest: the version gate, capture resolution, and the rebuild pass.

Fixture-free: ``reingest_all``'s ``ingest`` hook is injected (the same style as
``check_for_update``'s ``urlopen``), so the *accounting* - which captures were re-read, which
archives are gone, what a cancel or a failure does to the stamp - is exercised without a real
multi-hundred-MB capture. Real parse -> assemble -> persist is covered by test_ingest_pipeline
and test_archive_and_ingest.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone

from f1telemetry.src.domain.captures import CaptureMeta
from f1telemetry.src.domain.models import SessionResult
from f1telemetry.src.pipeline import (PipelineState, ReingestSummary, check_pipeline_version,
                                      reingest_all, resolve_capture_path)
from f1telemetry.src.protocol.enums import Formula, SessionType, Weather
from f1telemetry.src.storage.captures import CaptureStore
from f1telemetry.src.storage.meta import LEGACY_PIPELINE_VERSION, MetaStore
from f1telemetry.src.storage.sessions import SessionStore


def _session(uid: int) -> SessionResult:
    """A minimal stored session - only the identity matters for the accounting."""
    return SessionResult(
        session_uid=uid, season_link_id=1, weekend_link_id=1, session_link_id=1,
        game_format=2026, track_id=7, session_type=SessionType.RACE,
        formula=Formula.F1_26, weather=Weather.CLEAR, total_laps=5,
        game_mode=19, player_vehicle_index=0,
    )


def _meta(name: str, path: str, uids: tuple[str, ...], **overrides) -> CaptureMeta:
    base = dict(
        content_hash=name.ljust(64, "0"), path=path, file_name=name,
        file_size=1_000, payload_size=10_000, codec="zstd", packet_count=42,
        session_uids=uids, ingested_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
    )
    return CaptureMeta(**{**base, **overrides})


class _Recorder:
    """A stand-in for ``ingest_capture`` that records its calls and returns fixed sessions."""

    def __init__(self, by_path: dict[str, list[SessionResult]], boom: set[str] = frozenset()):
        self.by_path = by_path
        self.boom = boom
        self.calls: list[tuple[str, str | None]] = []

    def __call__(self, path, store, lap_store=None, capture_store=None, recorded_by=None):
        self.calls.append((path, recorded_by))
        if os.path.basename(path) in self.boom:
            raise RuntimeError("corrupt archive")
        return self.by_path.get(os.path.basename(path), [])


class PipelineVersionGateTest(unittest.TestCase):
    """check_pipeline_version: what a stamp (or its absence) means."""

    def setUp(self) -> None:
        self.temp = tempfile.mkdtemp(prefix="reingest_")
        self.addCleanup(lambda: shutil.rmtree(self.temp, ignore_errors=True))
        self.db_url = f"sqlite:///{os.path.join(self.temp, 'test.db')}"
        self.sessions = SessionStore(self.db_url)
        self.addCleanup(self.sessions.close)
        self.meta = MetaStore(self.db_url)
        self.addCleanup(self.meta.close)

    def test_fresh_database_is_adopted_silently(self):
        """No sessions, no stamp -> nothing to re-derive, so a first launch never prompts."""
        check = check_pipeline_version(self.meta, self.sessions, current=3)
        self.assertIs(check.state, PipelineState.CURRENT)
        self.assertEqual(self.meta.pipeline_version(), 3, "a fresh database is stamped at once")

    def test_populated_database_without_a_stamp_is_offered_the_upgrade(self):
        """Rows saved before the stamp existed were derived by an unknown older pipeline."""
        self.sessions.save(_session(111))
        check = check_pipeline_version(self.meta, self.sessions, current=1)

        self.assertIs(check.state, PipelineState.UPGRADE_AVAILABLE)
        self.assertEqual(check.stored, LEGACY_PIPELINE_VERSION)
        self.assertIsNone(self.meta.pipeline_version(),
                          "only a completed rebuild may stamp it - not the check")

    def test_states_by_stored_version(self):
        self.sessions.save(_session(111))
        cases = [(1, PipelineState.UPGRADE_AVAILABLE), (2, PipelineState.CURRENT),
                 (3, PipelineState.AHEAD)]
        for stored, expected in cases:
            with self.subTest(stored=stored):
                self.meta.set_pipeline_version(stored)
                self.assertIs(check_pipeline_version(self.meta, self.sessions, current=2).state,
                              expected)


class ResolveCapturePathTest(unittest.TestCase):
    """The recorded path is advisory; the captures dir is the fallback."""

    def setUp(self) -> None:
        self.temp = tempfile.mkdtemp(prefix="reingest_")
        self.addCleanup(lambda: shutil.rmtree(self.temp, ignore_errors=True))

    def _touch(self, name: str) -> str:
        path = os.path.join(self.temp, name)
        with open(path, "wb") as fh:
            fh.write(b"x")
        return path

    def test_recorded_path_wins_when_it_exists(self):
        path = self._touch("monza.f1cap.zst")
        meta = _meta("monza.f1cap.zst", path, ("111",))
        self.assertEqual(resolve_capture_path(meta, self.temp), path)

    def test_falls_back_to_the_captures_dir(self):
        """The data root moved (dev checkout -> %LOCALAPPDATA%), the file name did not."""
        self._touch("monza.f1cap.zst")
        meta = _meta("monza.f1cap.zst", "/gone/monza.f1cap.zst", ("111",))
        self.assertEqual(resolve_capture_path(meta, self.temp),
                         os.path.join(self.temp, "monza.f1cap.zst"))

    def test_none_when_the_archive_is_gone(self):
        meta = _meta("spa.f1cap.zst", "/gone/spa.f1cap.zst", ("222",))
        self.assertIsNone(resolve_capture_path(meta, self.temp))


class ReingestAllTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.mkdtemp(prefix="reingest_")
        self.addCleanup(lambda: shutil.rmtree(self.temp, ignore_errors=True))
        self.db_url = f"sqlite:///{os.path.join(self.temp, 'test.db')}"
        self.sessions = SessionStore(self.db_url)
        self.addCleanup(self.sessions.close)
        self.captures = CaptureStore(self.db_url)
        self.addCleanup(self.captures.close)

    def _capture(self, name: str, uids: tuple[str, ...], *, on_disk: bool = True,
                 recorded_by: str | None = None) -> str:
        path = os.path.join(self.temp, name)
        if on_disk:
            with open(path, "wb") as fh:
                fh.write(b"x")
        self.captures.record(_meta(name, path, uids, recorded_by=recorded_by))
        return path

    def test_rebuilds_every_capture_and_counts_sessions(self):
        self.sessions.save(_session(111))
        self.sessions.save(_session(222))
        self._capture("monza.f1cap.zst", ("111",))
        self._capture("spa.f1cap.zst", ("222",))
        ingest = _Recorder({"monza.f1cap.zst": [_session(111)], "spa.f1cap.zst": [_session(222)]})

        summary = reingest_all(self.captures, self.sessions, captures_dir=self.temp,
                               ingest=ingest)

        self.assertEqual((summary.captures_total, summary.captures_ingested), (2, 2))
        self.assertEqual((summary.sessions_rebuilt, summary.sessions_total), (2, 2))
        self.assertEqual(summary.missing, ())
        self.assertTrue(summary.is_complete, "a clean pass may stamp the new version")

    def test_missing_archive_is_reported_not_fatal(self):
        """Only captures still on disk can be rebuilt - the rest keep their old data."""
        self.sessions.save(_session(111))
        self.sessions.save(_session(222))
        self._capture("monza.f1cap.zst", ("111",))
        self._capture("spa.f1cap.zst", ("222",), on_disk=False)
        ingest = _Recorder({"monza.f1cap.zst": [_session(111)]})

        summary = reingest_all(self.captures, self.sessions, captures_dir=self.temp,
                               ingest=ingest)

        self.assertEqual(summary.missing, ("spa.f1cap.zst",))
        self.assertEqual((summary.sessions_rebuilt, summary.sessions_total), (1, 2))
        self.assertTrue(summary.is_complete,
                        "a missing archive can never be rebuilt, so it must not re-offer forever")

    def test_one_bad_archive_does_not_abort_the_pass(self):
        self.sessions.save(_session(111))
        self.sessions.save(_session(222))
        self._capture("bad.f1cap.zst", ("111",))
        self._capture("good.f1cap.zst", ("222",))
        ingest = _Recorder({"good.f1cap.zst": [_session(222)]}, boom={"bad.f1cap.zst"})

        with self.assertLogs("f1telemetry.src.pipeline", level="ERROR"): 
            summary = reingest_all(self.captures, self.sessions, captures_dir=self.temp,
                                   ingest=ingest)

        self.assertEqual(summary.captures_ingested, 1)
        self.assertEqual(len(summary.errors), 1)
        self.assertIn("bad.f1cap.zst", summary.errors[0])
        self.assertFalse(summary.is_complete, "a real failure must be retried next launch")

    def test_cancel_stops_between_captures_and_blocks_the_stamp(self):
        self.sessions.save(_session(111))
        self._capture("monza.f1cap.zst", ("111",))
        self._capture("spa.f1cap.zst", ("222",))
        ingest = _Recorder({"monza.f1cap.zst": [_session(111)]})

        summary = reingest_all(self.captures, self.sessions, captures_dir=self.temp,
                               cancelled=lambda: True, ingest=ingest)

        self.assertTrue(summary.cancelled)
        self.assertEqual(ingest.calls, [], "cancel is polled before a capture is opened")
        self.assertFalse(summary.is_complete)

    def test_recorded_by_survives_a_reingest(self):
        """It isn't in the capture file - feeding it back is the only thing that keeps it."""
        self.sessions.save(_session(111))
        self._capture("monza.f1cap.zst", ("111",), recorded_by="kevin")
        ingest = _Recorder({"monza.f1cap.zst": [_session(111)]})

        reingest_all(self.captures, self.sessions, captures_dir=self.temp, ingest=ingest)

        self.assertEqual([by for _, by in ingest.calls], ["kevin"])

    def test_progress_is_reported_per_capture(self):
        self._capture("monza.f1cap.zst", ("111",))
        self._capture("spa.f1cap.zst", ("222",))
        seen: list[tuple[int, int, str]] = []

        reingest_all(self.captures, self.sessions, captures_dir=self.temp,
                     on_progress=lambda i, n, name: seen.append((i, n, name)),
                     ingest=_Recorder({}))

        self.assertEqual([(i, n) for i, n, _ in seen], [(1, 2), (2, 2)])

    def test_empty_database_is_a_no_op(self):
        summary = reingest_all(self.captures, self.sessions, captures_dir=self.temp,
                               ingest=_Recorder({}))
        self.assertEqual(summary, ReingestSummary(0, 0, 0, 0))
        self.assertTrue(summary.is_complete)


if __name__ == "__main__":
    unittest.main()
