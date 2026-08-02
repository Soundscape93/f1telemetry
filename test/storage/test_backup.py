"""VACUUM INTO backups: a readable, complete copy that never overwrites by accident (C3)."""
from __future__ import annotations

import os
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine

from f1telemetry.src.storage.backup import backup_database, default_backup_name
from f1telemetry.src.storage.sessions import SessionStore

from .test_storage import make_session


class BackupDatabaseTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp()
        self.url = f"sqlite:///{os.path.join(self._dir, 'live.db')}"
        with SessionStore(self.url) as store:
            store.save(make_session())
        self.dest = Path(self._dir) / "backup.db"

    def _uids(self, url):
        with SessionStore(url) as store:
            return store.stored_uids()

    def test_backup_is_a_complete_readable_database(self):
        written = backup_database(self.url, self.dest)
        self.assertEqual(written, self.dest)
        self.assertTrue(self.dest.is_file())
        self.assertEqual(self._uids(f"sqlite:///{self.dest}"), self._uids(self.url))

    def test_backup_leaves_the_live_database_usable(self):
        backup_database(self.url, self.dest)
        with SessionStore(self.url) as store:            # still readable and writable afterwards
            self.assertEqual(len(store.stored_uids()), 1)

    def test_refuses_an_existing_destination_by_default(self):
        self.dest.write_text("not a database", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            backup_database(self.url, self.dest)
        self.assertEqual(self.dest.read_text(encoding="utf-8"), "not a database")  # untouched

    def test_overwrite_replaces_an_existing_file(self):
        self.dest.write_text("not a database", encoding="utf-8")
        backup_database(self.url, self.dest, overwrite=True)
        self.assertEqual(self._uids(f"sqlite:///{self.dest}"), self._uids(self.url))

    def test_a_path_with_awkward_characters_survives_binding(self):
        """The path is a bound parameter, not interpolated - quotes must not break the SQL."""
        odd = Path(self._dir) / "back'up (2).db"
        backup_database(self.url, odd)
        self.assertTrue(odd.is_file())


class DefaultBackupNameTest(unittest.TestCase):
    def test_is_timestamped_and_sortable(self):
        name = default_backup_name(datetime(2026, 8, 2, 16, 7, 5))
        self.assertEqual(name, "f1telemetry_backup_20260802_160705.db")

    def test_generated_name_matches_the_expected_shape(self):
        self.assertRegex(default_backup_name(), r"^f1telemetry_backup_\d{8}_\d{6}\.db$")


if __name__ == "__main__":
    unittest.main()
