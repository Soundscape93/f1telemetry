"""CaptureStore: replace-by-hash, the uid -> capture lookup, and the folder-scan pre-filter."""
from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone

from f1telemetry.src.domain.captures import CaptureMeta
from f1telemetry.src.storage.captures import CaptureStore


def _meta(**overrides) -> CaptureMeta:
    base = dict(
        content_hash="a" * 64,
        path="/captures/monza.f1cap.zst",
        file_name="monza.f1cap.zst",
        file_size=1_000,
        payload_size=10_000,
        codec="zstd",
        packet_count=42,
        session_uids=("111", "222"),
        recorded_by="kevin",
        ingested_at=datetime(2026, 7, 17, tzinfo=timezone.utc),
    )
    return CaptureMeta(**{**base, **overrides})


class CaptureStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = CaptureStore("sqlite://")      # in-memory
        self.addCleanup(self.store.close)
    
    def test_record_round_trips(self):
        self.store.record(meta :=_meta())
        loaded = self.store.get(meta.content_hash)
        self.assertEqual(loaded.file_name, meta.file_name)
        self.assertEqual(loaded.codec, "zstd")
        self.assertEqual(set(loaded.session_uids), {"111", "222"})
    
    def test_record_replaces_by_hash_without_duplicating_sessions(self):
        """Re-ingesting the same capture refreshes the row; it never accumulates child rows."""
        self.store.record(meta :=_meta())
        self.store.record(replace(meta, path="/elswhere/monza.f1cap.zst"))

        self.assertEqual(len(self.store.list_captures()), 1)
        loaded = self.store.get(meta.content_hash)
        self.assertEqual(loaded.path, "/elswhere/monza.f1cap.zst")
        self.assertEqual(sorted(loaded.session_uids), ["111", "222"])
    
    def test_same_recording_under_two_names_is_one_capture(self):
        """The hash is the identity: a league member's file renamed on import is not a dupe."""
        self.store.record(_meta())
        self.store.record(_meta(file_name="R05-monza-kevin.f1cap.zst"))
        self.assertEqual(len(self.store.list_captures()), 1)
    
    def test_for_session_finds_the_capture_to_reingest(self):
        self.store.record(_meta())
        self.store.record(_meta(content_hash="b" * 64, file_name="spa.f1cap.zst",
                                session_uids=("333",)))
    
        self.assertEqual([c.file_name for c in self.store.for_session("111")], ["monza.f1cap.zst"])
        self.assertEqual([c.file_name for c in self.store.for_session("333")], ["spa.f1cap.zst"])
        self.assertEqual(self.store.for_session("999"), [])
    
    def test_known_files_is_the_scan_prefilter(self):
        self.store.record(_meta())
        self.assertEqual(self.store.known_files(), {("monza.f1cap.zst", 1_000)})

    def test_relocate_updates_path_after_archiving(self):
        self.store.record(meta := _meta(path="/captures/monza.f1cap.zst", codec="none", file_size=99_000))
        self.assertTrue(self.store.relocate(meta.content_hash, "/captures/monza.f1cap.zst", 1_000, "zstd"))

        loaded = self.store.get(meta.content_hash)
        self.assertEqual((loaded.path, loaded.codec, loaded.file_size),
                         ("/captures/monza.f1cap.zst", "zstd", 1_000))
        self.assertEqual(loaded.file_name, "monza.f1cap.zst")  # unchanged

    def test_set_recorded_by_can_correct_an_imported_capture(self):
        """The only way to fix provenance later - a re-import, not a re-ingest (DECISIONS)."""
        self.store.record(meta := _meta(recorded_by=None))
        self.assertTrue(self.store.set_recorded_by(meta.content_hash, "anna"))

        self.assertEqual(self.store.get(meta.content_hash).recorded_by, "anna")
        self.assertFalse(self.store.set_recorded_by("z" * 64, "anna"))
    
    def test_delete_forgets_a_capture(self):
        self.store.record(meta := _meta())
        self.assertTrue(self.store.delete(meta.content_hash))
        self.assertFalse(self.store.has(meta.content_hash))
        self.assertFalse(self.store.delete(meta.content_hash))


if __name__ == "__main__":
    unittest.main()