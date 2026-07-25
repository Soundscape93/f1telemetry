"""MetaStore: the pipeline-version stamp that gates the Phase-2 guided re-ingest."""
from __future__ import annotations

import unittest

from f1telemetry.src.storage.meta import LEGACY_PIPELINE_VERSION, MetaStore
from f1telemetry.src.version import PIPELINE_VERSION


class MetaStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MetaStore("sqlite://")     # in-memory
        self.addCleanup(self.store.close)

    def test_unset_reads_as_none(self):
        self.assertIsNone(self.store.get("nothing"))
        self.assertIsNone(self.store.pipeline_version())

    def test_value_round_trips(self):
        self.store.set("greeting", "hello")
        self.assertEqual(self.store.get("greeting"), "hello")

    def test_set_replaces_rather_than_duplicating(self):
        """The stamp is written on every completed re-ingest - it must never accumulate rows."""
        self.store.set_pipeline_version(1)
        self.store.set_pipeline_version(2)
        self.store.set_pipeline_version(2)
        self.assertEqual(self.store.pipeline_version(), 2)

    def test_unparseable_stamp_reads_as_unstamped(self):
        """A hand-edited or corrupt value must not crash the start-up path."""
        for bad in ("banana", "", "1.0"):
            with self.subTest(value=bad):
                self.store.set("pipeline_version", bad)
                self.assertIsNone(self.store.pipeline_version())

    def test_legacy_is_older_than_any_shipped_pipeline(self):
        """The invariant that makes an unstamped, populated database offer the re-ingest."""
        self.assertLess(LEGACY_PIPELINE_VERSION, PIPELINE_VERSION)


if __name__ == "__main__":
    unittest.main()
