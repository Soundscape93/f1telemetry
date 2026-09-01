"""The Phase-2 guided re-ingest, locating captures that moved, and the missing prune: the
version gate, capture resolution, the rebuild pass, the search, and forgetting archives that
are gone.

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
from f1telemetry.src.pipeline import (PipelineState, PruneSummary, ReingestSummary,
                                      RelocateSummary, check_pipeline_version,
                                      find_missing_captures, prune_missing_captures,
                                      reingest_all, relocate_moved_captures, resolve_capture_path)
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
        self.stores: list[tuple[object, object]] = []   # what each call was handed to write into

    def __call__(self, path, store, lap_store=None, event_store=None, capture_store=None,
                 recorded_by=None):
        self.calls.append((path, recorded_by))
        self.stores.append((lap_store, event_store))
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

    def test_the_event_store_reaches_every_ingest(self):
        """A re-ingest is how an existing database picks up PIPELINE_VERSION 5's events, so the
        store has to be handed down - a pass that forwarded only the laps would rebuild every
        session and still leave the penalties and passes unwritten."""
        self.sessions.save(_session(111))
        self._capture("monza.f1cap.zst", ("111",))
        ingest = _Recorder({"monza.f1cap.zst": [_session(111)]})
        events = object()

        reingest_all(self.captures, self.sessions, captures_dir=self.temp,
                     event_store=events, ingest=ingest)

        self.assertEqual([store for _, store in ingest.stores], [events])

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


class PruneMissingCapturesTest(unittest.TestCase):
    """Forgetting rows whose archive is gone: metadata only, re-checked, never a file."""

    def setUp(self) -> None:
        self.temp = tempfile.mkdtemp(prefix="prune_")
        self.addCleanup(lambda: shutil.rmtree(self.temp, ignore_errors=True))
        self.db_url = f"sqlite:///{os.path.join(self.temp, 'test.db')}"
        self.sessions = SessionStore(self.db_url)
        self.addCleanup(self.sessions.close)
        self.captures = CaptureStore(self.db_url)
        self.addCleanup(self.captures.close)

    def _capture(self, name: str, uids: tuple[str, ...], *, on_disk: bool = True) -> CaptureMeta:
        path = os.path.join(self.temp, name)
        if on_disk:
            with open(path, "wb") as fh:
                fh.write(b"x")
        self.captures.record(meta := _meta(name, path, uids))
        return meta

    def test_finds_only_the_captures_whose_archive_is_gone(self):
        self._capture("monza.f1cap.zst", ("111",))
        self._capture("spa.f1cap.zst", ("222",), on_disk=False)

        missing = find_missing_captures(self.captures, self.temp)

        self.assertEqual([meta.file_name for meta in missing], ["spa.f1cap.zst"])

    def test_prune_forgets_the_row_and_its_capture_sessions(self):
        gone = self._capture("spa.f1cap.zst", ("222",), on_disk=False)

        summary = prune_missing_captures(self.captures, [gone.content_hash],
                                         captures_dir=self.temp)

        self.assertEqual(summary.pruned, ("spa.f1cap.zst",))
        self.assertFalse(self.captures.has(gone.content_hash))
        self.assertEqual(self.captures.for_session("222"), [],
                         "the capture_sessions children go with the row")

    def test_prune_leaves_the_stored_session_alone(self):
        """Metadata cleanup, not data deletion - nothing behind the standings may move."""
        self.sessions.save(_session(222))
        gone = self._capture("spa.f1cap.zst", ("222",), on_disk=False)

        prune_missing_captures(self.captures, [gone.content_hash], captures_dir=self.temp)

        self.assertIn(222, self.sessions.stored_uids())

    def test_a_capture_that_turned_up_again_is_kept(self):
        """The caller's list can be minutes old - a drive reconnects while the dialog waits."""
        here = self._capture("monza.f1cap.zst", ("111",))

        summary = prune_missing_captures(self.captures, [here.content_hash],
                                         captures_dir=self.temp)

        self.assertEqual((summary.pruned, summary.kept), ((), ("monza.f1cap.zst",)))
        self.assertTrue(self.captures.has(here.content_hash))

    def test_an_unknown_hash_is_skipped_so_a_prune_can_be_repeated(self):
        gone = self._capture("spa.f1cap.zst", ("222",), on_disk=False)
        prune_missing_captures(self.captures, [gone.content_hash], captures_dir=self.temp)

        again = prune_missing_captures(self.captures, [gone.content_hash], captures_dir=self.temp)

        self.assertEqual(again, PruneSummary())

    def test_a_pruned_capture_stops_being_reported_as_missing(self):
        """The point of the feature: the re-ingest noise goes, the pass still completes."""
        self.sessions.save(_session(111))
        self._capture("monza.f1cap.zst", ("111",))
        gone = self._capture("spa.f1cap.zst", ("222",), on_disk=False)
        prune_missing_captures(self.captures, [gone.content_hash], captures_dir=self.temp)

        summary = reingest_all(self.captures, self.sessions, captures_dir=self.temp,
                               ingest=_Recorder({"monza.f1cap.zst": [_session(111)]}))

        self.assertEqual(summary.missing, ())
        self.assertEqual(summary.captures_total, 1)


class RelocateMovedCapturesTest(unittest.TestCase):
    """Finding a capture whose file moved: name+size pre-filter, the content hash decides.

    ``hash_file`` is injected the way ``reingest_all``'s ``ingest`` is, so the *matching* is
    exercised on byte-sized files instead of real archives. ``_meta`` derives a capture's hash
    from its name, so the fake hasher only has to read a file's basename to agree with the store.
    """

    def setUp(self) -> None:
        self.temp = tempfile.mkdtemp(prefix="relocate_")
        self.addCleanup(lambda: shutil.rmtree(self.temp, ignore_errors=True))
        self.db_url = f"sqlite:///{os.path.join(self.temp, 'test.db')}"
        self.sessions = SessionStore(self.db_url)
        self.addCleanup(self.sessions.close)
        self.captures = CaptureStore(self.db_url)
        self.addCleanup(self.captures.close)
        # Where the app looks (empty), and where the files actually are.
        self.home = os.path.join(self.temp, "captures")
        self.elsewhere = os.path.join(self.temp, "elsewhere")
        os.makedirs(self.home)
        os.makedirs(self.elsewhere)
        self.hashed: list[str] = []

    def _hash(self, path: str) -> str:
        """Stand in for ``hash_capture``: the name is the identity, as in ``_meta``."""
        self.hashed.append(os.path.basename(path))
        return os.path.basename(path).ljust(64, "0")

    def _known(self, name: str, uids: tuple[str, ...] = ("111",), size: int = 1_000):
        """A capture the store knows about, whose file is not where it was recorded."""
        meta = _meta(name, os.path.join("/gone", name), uids, file_size=size)
        self.captures.record(meta)
        return meta

    def _file(self, folder: str, name: str, size: int = 1_000) -> str:
        path = os.path.join(folder, name)
        os.makedirs(folder, exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"x" * size)
        return path

    def test_a_moved_capture_is_found_and_relocated(self):
        meta = self._known("monza.f1cap.zst")
        moved_to = self._file(self.elsewhere, "monza.f1cap.zst")

        summary = relocate_moved_captures(self.captures, self.elsewhere,
                                          captures_dir=self.home, hash_file=self._hash)

        self.assertEqual(summary.relocated, (("monza.f1cap.zst", moved_to),))
        self.assertEqual(summary.still_missing, ())
        self.assertEqual(self.captures.get(meta.content_hash).path, moved_to)

    def test_a_relocated_capture_stops_being_missing_and_can_be_reingested(self):
        """The payoff: the row is usable again, so the session behind it is rebuildable."""
        self.sessions.save(_session(111))
        self._known("monza.f1cap.zst")
        self._file(self.elsewhere, "monza.f1cap.zst")

        relocate_moved_captures(self.captures, self.elsewhere, captures_dir=self.home,
                                hash_file=self._hash)

        self.assertEqual(find_missing_captures(self.captures, self.home), [])
        summary = reingest_all(self.captures, self.sessions, captures_dir=self.home,
                               ingest=_Recorder({"monza.f1cap.zst": [_session(111)]}))
        self.assertEqual(summary.missing, ())
        self.assertEqual(summary.sessions_rebuilt, 1)

    def test_only_name_and_size_matches_are_ever_read(self):
        """The pre-filter is the whole point - decompressing a stranger costs seconds."""
        self._known("monza.f1cap.zst", size=1_000)
        # A second capture that is never found, so `wanted` never empties and the walk is not
        # cut short by the found-everything break (pinned separately below).
        self._known("imola.f1cap.zst", uids=("222",), size=1_000)
        self._file(self.elsewhere, "monza.f1cap.zst", size=1_000)
        self._file(self.elsewhere, "spa.f1cap.zst", size=1_000)         # wrong name
        self._file(self.elsewhere, "monza.f1cap.gz", size=1_000)        # wrong name
        self._file(self.elsewhere, "notes.txt", size=1_000)             # not a capture at all

        summary = relocate_moved_captures(self.captures, self.elsewhere,
                                          captures_dir=self.home, hash_file=self._hash)

        self.assertEqual(self.hashed, ["monza.f1cap.zst"])
        self.assertEqual(summary.hashed, 1)
        self.assertEqual(summary.scanned, 3, "the .txt is rejected by suffix, never counted")

    def test_the_walk_stops_once_everything_wanted_is_found(self):
        """A search that is already done must not keep stat-ing the rest of a large drive."""
        self._known("aaa.f1cap.zst")
        self._file(self.elsewhere, "aaa.f1cap.zst")     # sorts first
        self._file(self.elsewhere, "zzz.f1cap.zst")     # never reached

        summary = relocate_moved_captures(self.captures, self.elsewhere,
                                          captures_dir=self.home, hash_file=self._hash)

        self.assertEqual(len(summary.relocated), 1)
        self.assertEqual(summary.scanned, 1, "the walk breaks as soon as nothing is still wanted")

    def test_a_different_size_is_never_read(self):
        self._known("monza.f1cap.zst", size=1_000)
        self._file(self.elsewhere, "monza.f1cap.zst", size=2_000)

        summary = relocate_moved_captures(self.captures, self.elsewhere,
                                          captures_dir=self.home, hash_file=self._hash)

        self.assertEqual(self.hashed, [])
        self.assertEqual(summary.still_missing, ("monza.f1cap.zst",))

    def test_a_name_and_size_twin_with_another_hash_is_not_relocated(self):
        """Why the hash is not optional: name+size is a hint, never an identity."""
        meta = self._known("monza.f1cap.zst")
        impostor = self._file(self.elsewhere, "monza.f1cap.zst")

        summary = relocate_moved_captures(
            self.captures, self.elsewhere, captures_dir=self.home,
            hash_file=lambda path: "f" * 64)

        self.assertEqual(summary.relocated, ())
        self.assertEqual(summary.still_missing, ("monza.f1cap.zst",))
        self.assertEqual(self.captures.get(meta.content_hash).path, "/gone/monza.f1cap.zst",
                         "a row must never be re-pointed at bytes that aren't its own")
        self.assertNotEqual(impostor, "")   # the impostor file is left exactly where it was

    def test_the_search_is_recursive(self):
        """The league folder is a tree, and a moved captures folder lands inside one."""
        self._known("monza.f1cap.zst")
        buried = self._file(os.path.join(self.elsewhere, "2026", "01-Melbourne"),
                            "monza.f1cap.zst")

        summary = relocate_moved_captures(self.captures, self.elsewhere,
                                          captures_dir=self.home, hash_file=self._hash)

        self.assertEqual(summary.relocated, (("monza.f1cap.zst", buried),))

    def test_captures_that_are_not_missing_are_left_alone(self):
        """A row that resolves is already right; a second copy on a stick must not steal it."""
        home_copy = self._file(self.home, "monza.f1cap.zst")
        self.captures.record(_meta("monza.f1cap.zst", home_copy, ("111",)))
        self._file(self.elsewhere, "monza.f1cap.zst")

        summary = relocate_moved_captures(self.captures, self.elsewhere,
                                          captures_dir=self.home, hash_file=self._hash)

        self.assertEqual(summary, RelocateSummary(), "nothing missing means nothing to search")
        self.assertEqual(self.hashed, [], "the folder is not even walked")

    def test_what_no_folder_had_is_reported_still_missing(self):
        self._known("monza.f1cap.zst")
        self._known("spa.f1cap.zst", uids=("222",))
        self._file(self.elsewhere, "monza.f1cap.zst")

        summary = relocate_moved_captures(self.captures, self.elsewhere,
                                          captures_dir=self.home, hash_file=self._hash)

        self.assertEqual([name for name, _ in summary.relocated], ["monza.f1cap.zst"])
        self.assertEqual(summary.still_missing, ("spa.f1cap.zst",))

    def test_an_unreadable_candidate_is_reported_not_fatal(self):
        self._known("bad.f1cap.zst")
        self._known("good.f1cap.zst", uids=("222",))
        self._file(self.elsewhere, "bad.f1cap.zst")
        good = self._file(self.elsewhere, "good.f1cap.zst")

        def hash_file(path):
            if os.path.basename(path) == "bad.f1cap.zst":
                raise RuntimeError("corrupt archive")
            return self._hash(path)

        with self.assertLogs("f1telemetry.src.pipeline", level="ERROR"):
            summary = relocate_moved_captures(self.captures, self.elsewhere,
                                              captures_dir=self.home, hash_file=hash_file)

        self.assertEqual(len(summary.errors), 1)
        self.assertIn("bad.f1cap.zst", summary.errors[0])
        self.assertEqual(summary.relocated, (("good.f1cap.zst", good),),
                         "one unreadable file must not cost the others their relocation")

    def test_cancel_stops_the_walk(self):
        self._known("monza.f1cap.zst")
        self._file(self.elsewhere, "monza.f1cap.zst")

        summary = relocate_moved_captures(self.captures, self.elsewhere,
                                          captures_dir=self.home, cancelled=lambda: True,
                                          hash_file=self._hash)

        self.assertTrue(summary.cancelled)
        self.assertEqual(self.hashed, [], "cancel is polled before a file is opened")
        self.assertEqual(summary.still_missing, ("monza.f1cap.zst",))

    def test_progress_reports_found_against_wanted(self):
        self._known("monza.f1cap.zst")
        self._known("spa.f1cap.zst", uids=("222",))
        self._file(self.elsewhere, "monza.f1cap.zst")
        self._file(self.elsewhere, "spa.f1cap.zst")
        seen: list[tuple[int, int, str]] = []

        relocate_moved_captures(self.captures, self.elsewhere, captures_dir=self.home,
                                on_progress=lambda f, t, n: seen.append((f, t, n)),
                                hash_file=self._hash)

        self.assertEqual([(f, t) for f, t, _ in seen], [(0, 2), (1, 2)])



if __name__ == "__main__":
    unittest.main()
