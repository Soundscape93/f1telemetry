"""The archive_and_ingest orchestration - archive first, verify-by-ingest, delete-raw.

Fixture-free: synthetic captures of unparseable datagrams assemble to zero sessions, so these
ecercise the *file movement + metadata* orchestration - which codec is written, whether the raw
is deleted, whether an existing archive is left untouched - without a real capture. Session
assembly itself is covered by test_ingest_pipeline a real fixture.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from f1telemetry.src.ingest.archive import archive_capture, capture_codec
from f1telemetry.src.ingest.recording import write_header, write_packet
from f1telemetry.src.pipeline import archive_and_ingest
from f1telemetry.src.storage.captures import CaptureStore
from f1telemetry.src.storage.sessions import SessionStore


class ArchiveAndIngestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.mkdtemp(prefix="phasec_")
        self.addCleanup(lambda: shutil.rmtree(self.temp, ignore_errors=True))
        self.db_url = f"sqlite:///{os.path.join(self.temp, 'test.db')}"
        self.store = SessionStore(self.db_url)
        self.addCleanup(self.store.close)
        self.capture_store = CaptureStore(self.db_url)
        self.addCleanup(self.capture_store.close)
    
    def _write_raw(self, name: str = "race.f1cap") -> str:
        """A synthetically valid capture whose datagrams don't parse (zero sessions)."""
        path = os.path.join(self.temp, name)
        with open(path, "wb") as f:
            write_header(f)
            for i in range(3):
                write_packet(f, float(i), bytes(24))        # too short to parse -> None, no session
        return path
    
    def test_raw_capture_arhcived_to_zst_and_raw_deleted(self):
        raw = self._write_raw()
        _, archive_path, archive_error = archive_and_ingest(
            raw, self.store, capture_store=self.capture_store)
        
        self.assertEqual(archive_error, "")
        self.assertTrue(archive_path.endswith(".f1cap.zst"), "new archives should be zstd")
        self.assertTrue(os.path.exists(archive_path), "the .zst archive should be written")
        self.assertFalse(os.path.exists(raw), "the raw capture should be deleted after a succesfull ingest")

    def test_existing_gz_ingested_in_place_not_rewritten(self):
        gz = str(archive_capture(self._write_raw(), codec="gzip"))      # a pre-existing .gz archive
        self.assertTrue(gz.endswith(".f1cap.gz"))

        _, archive_path, archive_error = archive_and_ingest(
            gz, self.store, capture_store=self.capture_store)
        
        self.assertEqual(archive_path, "", "re-ingesting an archive should not report a new archive")
        self.assertEqual(archive_error, "")
        self.assertTrue(os.path.exists(gz), "an existing .gz must not be deleted or rewritten")
        self.assertEqual(capture_codec(gz), "gzip", "the .gz must stay a .gz")
    
    def test_ingest_failure_keeps_both_raw_and_archive(self):
        """If ingest raises after archiving, the raw is kept (debug) and the .zst kept (uploadable)."""
        raw = self._write_raw()

        class _BoomStore:
            def deleted_uids(self):
                raise RuntimeError("boom")
        
        with self.assertRaises(RuntimeError):
            archive_and_ingest(raw, _BoomStore())
        
        self.assertTrue(os.path.exists(raw), "the raw capture must survive an ingest failure")
        archive = Path(raw).with_name(Path(raw).name + ".zst")
        self.assertTrue(archive.exists(), "the archive must survive an ingest failure")

    def test_capture_metadata_records_the_archive(self):
        raw = self._write_raw()
        _, archive_path, _ = archive_and_ingest(
            raw, self.store, capture_store=self.capture_store)
        
        captures = self.capture_store.list_captures()
        self.assertEqual(len(captures), 1, "the capture store should have one row for the ingested capture")
        meta = captures[0]
        self.assertEqual(meta.codec, "zstd", "the capture store should record the archive's codec")
        self.assertEqual(meta.path, os.path.abspath(archive_path), "metadata should point at the archive")
        self.assertEqual(meta.packet_count, 3, "the capture store should record the number of packets in the capture")
        self.assertTrue(meta.content_hash, "a content hash should be computed during ingest")


if __name__ == "__main__":
    unittest.main()