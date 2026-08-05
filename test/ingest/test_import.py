"""League capture import: what a shared folder scan proposes, and what importing it does.

Fixture-free in the same style as ``test_reingest``: ``hash_file`` and ``ingest`` are injected,
so the *decision table* - new / already held / missing locally / only the name changed - is
exercised on byte-sized files instead of real multi-hundred-megabyte archives. The fake hash is
taken over a file's contents, so a renamed copy hashes the same, which is the property the whole
feature rests on. Real parse -> assemble -> persist is covered by test_ingest_pipeline.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone

from f1telemetry.src.domain.captures import CaptureMeta
from f1telemetry.src.domain.models import SessionResult
from f1telemetry.src.pipeline import (ImportCandidate, ImportSummary, find_importable_captures,
                                      import_captures)
from f1telemetry.src.protocol.enums import Formula, SessionType, Weather
from f1telemetry.src.storage.captures import CaptureStore
from f1telemetry.src.storage.sessions import SessionStore


def _session(uid: int) -> SessionResult:
    return SessionResult(
        session_uid=uid, season_link_id=1, weekend_link_id=1, session_link_id=1,
        game_format=2026, track_id=7, session_type=SessionType.RACE,
        formula=Formula.F1_26, weather=Weather.CLEAR, total_laps=5,
        game_mode=19, player_vehicle_index=0,
    )


class _Ingest:
    """Stands in for ``ingest_capture``; records the path and recorded_by it was called with."""

    def __init__(self, sessions=(), boom: set[str] = frozenset()):
        self._sessions = list(sessions)
        self.boom = boom
        self.calls: list[tuple[str, str | None]] = []

    def __call__(self, path, store, lap_store=None, capture_store=None, recorded_by=None):
        self.calls.append((path, recorded_by))
        if os.path.basename(path) in self.boom:
            raise RuntimeError("corrupt archive")
        for session in self._sessions:
            store.save(session)
        return list(self._sessions)


class _ImportTestCase(unittest.TestCase):
    """A source folder (the shared drive), a captures folder (home), and a database."""

    def setUp(self) -> None:
        self.temp = tempfile.mkdtemp(prefix="import_")
        self.addCleanup(lambda: shutil.rmtree(self.temp, ignore_errors=True))
        self.db_url = f"sqlite:///{os.path.join(self.temp, 'test.db')}"
        self.sessions = SessionStore(self.db_url)
        self.addCleanup(self.sessions.close)
        self.captures = CaptureStore(self.db_url)
        self.addCleanup(self.captures.close)
        self.source = os.path.join(self.temp, "shared")
        self.home = os.path.join(self.temp, "captures")
        os.makedirs(self.source)
        os.makedirs(self.home)
        self.hashed: list[str] = []

    def _hash(self, path: str) -> str:
        """Hash a file by its *contents*, so a renamed copy keeps its identity."""
        self.hashed.append(os.path.basename(path))
        with open(path, "rb") as fh:
            return fh.read().decode().ljust(64, "0")

    def _file(self, folder: str, name: str, content: str = "monza") -> str:
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        with open(path, "wb") as fh:
            fh.write(content.encode())
        return path

    def _candidate(self, path: str) -> ImportCandidate:
        return ImportCandidate(path=path, file_name=os.path.basename(path),
                               file_size=os.path.getsize(path))

    def _record(self, name: str, path: str, content: str = "monza", **overrides) -> CaptureMeta:
        meta = CaptureMeta(**{
            "content_hash": content.ljust(64, "0"), "path": path, "file_name": name,
            "file_size": len(content), "payload_size": 10_000, "codec": "zstd",
            "packet_count": 42, "session_uids": ("111",),
            "ingested_at": datetime(2026, 7, 25, tzinfo=timezone.utc), **overrides})
        self.captures.record(meta)
        return meta

    def _import(self, *candidates, **kwargs):
        kwargs.setdefault("hash_file", self._hash)
        kwargs.setdefault("ingest", _Ingest())
        return import_captures(list(candidates), self.captures, self.sessions,
                               captures_dir=self.home, **kwargs)


class FindImportableCapturesTest(_ImportTestCase):
    """The cheap scan the user is shown before anything is copied."""

    def test_finds_capture_files_recursively_and_ignores_everything_else(self):
        self._file(self.source, "monza.f1cap.zst")
        self._file(os.path.join(self.source, "2026", "01-Melbourne"), "spa.f1cap.gz")
        self._file(self.source, "readme.txt")

        found = find_importable_captures(self.source, self.captures)

        self.assertEqual(sorted(c.file_name for c in found),
                         ["monza.f1cap.zst", "spa.f1cap.gz"])
        self.assertEqual(self.hashed, [], "the scan must not open a single archive")

    def test_a_known_name_and_size_is_pre_filtered_out(self):
        path = self._file(self.source, "monza.f1cap.zst", content="monza")
        self._record("monza.f1cap.zst", path)

        self.assertEqual(find_importable_captures(self.source, self.captures), [])

    def test_a_renamed_copy_is_proposed_because_only_the_hash_can_rule(self):
        """The pre-filter is a hint. A renamed capture costs one wasted read, never a duplicate."""
        self._record("monza.f1cap.zst", os.path.join(self.home, "monza.f1cap.zst"))
        self._file(self.source, "kevins-monza.f1cap.zst", content="monza")

        found = find_importable_captures(self.source, self.captures)

        self.assertEqual([c.file_name for c in found], ["kevins-monza.f1cap.zst"])

    def test_an_empty_folder_proposes_nothing(self):
        self.assertEqual(find_importable_captures(self.source, self.captures), [])


class ImportCapturesTest(_ImportTestCase):
    """The decision table: new, already held, missing locally, or only recorded_by differs."""

    def test_a_new_capture_is_copied_home_and_ingested(self):
        source = self._file(self.source, "monza.f1cap.zst")
        ingest = _Ingest([_session(111)])

        summary = self._import(self._candidate(source), ingest=ingest)

        self.assertEqual(summary.imported, ("monza.f1cap.zst",))
        self.assertEqual(summary.sessions_stored, 1)
        landed = os.path.join(self.home, "monza.f1cap.zst")
        self.assertTrue(os.path.isfile(landed), "the capture must be copied into the home folder")
        self.assertEqual([path for path, _ in ingest.calls], [landed],
                         "ingest must read the local copy, never the shared original")
        self.assertTrue(os.path.isfile(source), "the shared original is never moved or deleted")

    def test_recorded_by_is_passed_through_to_ingest(self):
        source = self._file(self.source, "monza.f1cap.zst")
        ingest = _Ingest([_session(111)])

        self._import(self._candidate(source), recorded_by="kevin", ingest=ingest)

        self.assertEqual([by for _, by in ingest.calls], ["kevin"])

    def test_blank_recorded_by_is_fine(self):
        source = self._file(self.source, "monza.f1cap.zst")
        ingest = _Ingest([_session(111)])

        self._import(self._candidate(source), recorded_by=None, ingest=ingest)

        self.assertEqual([by for _, by in ingest.calls], [None])

    def test_a_capture_already_held_is_skipped_without_copying(self):
        """Re-syncing a shared folder must be a no-op - the point of keying on a content hash."""
        home_copy = self._file(self.home, "monza.f1cap.zst")
        self._record("monza.f1cap.zst", home_copy)
        source = self._file(self.source, "renamed.f1cap.zst", content="monza")
        ingest = _Ingest([_session(111)])

        summary = self._import(self._candidate(source), ingest=ingest)

        self.assertEqual(summary.skipped, ("renamed.f1cap.zst",))
        self.assertEqual(summary.imported, ())
        self.assertEqual(ingest.calls, [])
        self.assertFalse(os.path.exists(os.path.join(self.home, "renamed.f1cap.zst")))

    def test_a_capture_already_in_the_captures_folder_is_ingested_in_place(self):
        """Importing from a folder that *contains* the data root must not copy an archive
        beside itself under a "-2" name."""
        already_home = self._file(self.home, "monza.f1cap.zst")
        ingest = _Ingest([_session(111)])

        summary = self._import(self._candidate(already_home), ingest=ingest)

        self.assertEqual(summary.imported, ("monza.f1cap.zst",))
        self.assertEqual([path for path, _ in ingest.calls], [already_home])
        self.assertEqual(sorted(os.listdir(self.home)), ["monza.f1cap.zst"],
                         "no second copy of a capture that was already home")


    def test_recorded_by_can_be_corrected_by_re_importing(self):
        """Otherwise "already imported" would mean the value could never be fixed."""
        home_copy = self._file(self.home, "monza.f1cap.zst")
        meta = self._record("monza.f1cap.zst", home_copy, recorded_by=None)
        source = self._file(self.source, "monza.f1cap.zst", content="monza")

        summary = self._import(self._candidate(source), recorded_by="anna")

        self.assertEqual(summary.updated, ("monza.f1cap.zst",))
        self.assertEqual(self.captures.get(meta.content_hash).recorded_by, "anna")

    def test_a_matching_recorded_by_is_just_a_skip(self):
        home_copy = self._file(self.home, "monza.f1cap.zst")
        self._record("monza.f1cap.zst", home_copy, recorded_by="anna")
        source = self._file(self.source, "monza.f1cap.zst", content="monza")

        summary = self._import(self._candidate(source), recorded_by="anna")

        self.assertEqual((summary.updated, summary.skipped), ((), ("monza.f1cap.zst",)))

    def test_a_capture_missing_locally_is_recovered_from_the_shared_folder(self):
        """The one path that treats the league folder as a backup of last resort."""
        meta = self._record("monza.f1cap.zst", "/gone/monza.f1cap.zst")
        source = self._file(self.source, "monza.f1cap.zst", content="monza")
        ingest = _Ingest([_session(111)])

        summary = self._import(self._candidate(source), ingest=ingest)

        landed = os.path.join(self.home, "monza.f1cap.zst")
        self.assertEqual(summary.recovered, ("monza.f1cap.zst",))
        self.assertTrue(os.path.isfile(landed))
        self.assertEqual(self.captures.get(meta.content_hash).path, landed)
        self.assertEqual(ingest.calls, [],
                         "the derived rows are already there - rebuilding them is Re-read's job")

    def test_a_name_clash_between_two_different_recordings_is_numbered(self):
        """Not a duplicate - the hash already said this is a recording we don't hold."""
        self._file(self.home, "monza.f1cap.zst", content="mine")
        source = self._file(self.source, "monza.f1cap.zst", content="theirs")

        summary = self._import(self._candidate(source), ingest=_Ingest([_session(111)]))

        self.assertEqual(summary.imported, ("monza-2.f1cap.zst",))
        self.assertTrue(os.path.isfile(os.path.join(self.home, "monza-2.f1cap.zst")))
        with open(os.path.join(self.home, "monza.f1cap.zst"), "rb") as fh:
            self.assertEqual(fh.read(), b"mine", "the file already there must not be overwritten")

    def test_one_bad_capture_does_not_abort_the_folder(self):
        bad = self._file(self.source, "bad.f1cap.zst", content="bad")
        good = self._file(self.source, "good.f1cap.zst", content="good")
        ingest = _Ingest([_session(111)], boom={"bad.f1cap.zst"})

        with self.assertLogs("f1telemetry.src.pipeline", level="ERROR"):
            summary = self._import(self._candidate(bad), self._candidate(good), ingest=ingest)

        self.assertEqual(summary.imported, ("good.f1cap.zst",))
        self.assertEqual(len(summary.errors), 1)
        self.assertIn("bad.f1cap.zst", summary.errors[0])

    def test_a_capture_that_fails_to_ingest_keeps_its_local_copy(self):
        """The one most worth having locally to look at - and the shared original is untouched."""
        bad = self._file(self.source, "bad.f1cap.zst", content="bad")

        with self.assertLogs("f1telemetry.src.pipeline", level="ERROR"):
            self._import(self._candidate(bad), ingest=_Ingest(boom={"bad.f1cap.zst"}))

        self.assertTrue(os.path.isfile(os.path.join(self.home, "bad.f1cap.zst")))
        self.assertTrue(os.path.isfile(bad))

    def test_an_unreadable_source_is_reported_not_fatal(self):
        source = self._file(self.source, "monza.f1cap.zst")

        def hash_file(path):
            raise RuntimeError("cannot decompress")

        with self.assertLogs("f1telemetry.src.pipeline", level="ERROR"):
            summary = self._import(self._candidate(source), hash_file=hash_file)

        self.assertEqual(len(summary.errors), 1)
        self.assertEqual(summary.imported, ())
        self.assertFalse(os.path.exists(os.path.join(self.home, "monza.f1cap.zst")),
                         "nothing is copied for a capture that could not even be read")

    def test_cancel_stops_between_captures(self):
        source = self._file(self.source, "monza.f1cap.zst")

        summary = self._import(self._candidate(source), cancelled=lambda: True)

        self.assertTrue(summary.cancelled)
        self.assertEqual(self.hashed, [], "cancel is polled before a capture is opened")
        self.assertEqual(summary.imported, ())

    def test_progress_is_reported_per_capture(self):
        first = self._file(self.source, "a.f1cap.zst", content="a")
        second = self._file(self.source, "b.f1cap.zst", content="b")
        seen: list[tuple[int, int, str]] = []

        self._import(self._candidate(first), self._candidate(second),
                     on_progress=lambda i, n, name: seen.append((i, n, name)))

        self.assertEqual([(i, n) for i, n, _ in seen], [(1, 2), (2, 2)])

    def test_importing_nothing_is_a_no_op(self):
        self.assertEqual(self._import(), ImportSummary())


if __name__ == "__main__":
    unittest.main()
