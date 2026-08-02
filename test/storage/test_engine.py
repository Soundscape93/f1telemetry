"""The shared engine factory: the SQLite pragmas every store must open the database with (C2)."""
from __future__ import annotations

import os
import tempfile
import unittest

from sqlalchemy import create_engine

from f1telemetry.src.storage.engine import create_db_engine
from f1telemetry.src.storage.sessions import SessionStore


class SqlitePragmaTest(unittest.TestCase):
    def setUp(self):
        fd, self._path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self._path)                       # let SQLite create it fresh
        self.url = f"sqlite:///{self._path}"
        self.addCleanup(lambda: os.path.exists(self._path) and os.unlink(self._path))

    def test_pragmas_are_applied_to_a_connection(self):
        engine = create_db_engine(self.url)
        self.addCleanup(engine.dispose)
        with engine.connect() as conn:
            self.assertEqual(conn.exec_driver_sql("PRAGMA journal_mode").scalar(), "wal")
            self.assertEqual(conn.exec_driver_sql("PRAGMA synchronous").scalar(), 1)  # NORMAL
            self.assertEqual(conn.exec_driver_sql("PRAGMA busy_timeout").scalar(), 10_000)

    def test_a_store_leaves_the_database_in_wal_mode(self):
        """The property that matters: WAL is in the file header, so it outlives the connection.

        Asserted through a *plain* engine with no pragmas of its own - if this passes, a database
        touched by any store is in WAL for every later reader, however it was opened.
        """
        with SessionStore(self.url):
            pass
        plain = create_engine(self.url)
        self.addCleanup(plain.dispose)
        with plain.connect() as conn:
            self.assertEqual(conn.exec_driver_sql("PRAGMA journal_mode").scalar(), "wal")

    def test_a_reader_is_not_blocked_by_an_open_write_transaction(self):
        """The actual point of WAL here: the GUI keeps reading while an ingest writes."""
        writer = create_db_engine(self.url)
        reader = create_db_engine(self.url)
        self.addCleanup(writer.dispose)
        self.addCleanup(reader.dispose)
        with writer.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE t (a INTEGER)")
            conn.exec_driver_sql("INSERT INTO t VALUES (1)")

        write_conn = writer.connect()
        self.addCleanup(write_conn.close)
        trans = write_conn.begin()
        write_conn.exec_driver_sql("INSERT INTO t VALUES (2)")   # uncommitted, lock held
        with reader.connect() as read_conn:                      # must not raise or hang
            self.assertEqual(read_conn.exec_driver_sql("SELECT count(*) FROM t").scalar(), 1)
        trans.rollback()


if __name__ == "__main__":
    unittest.main()
