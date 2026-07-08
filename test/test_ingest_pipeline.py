"""End-to-End ingest test against a real capture file. This is a regression test to ensure
that the pipeline continues to work as expected.

This runs the *actual* pipeline (parse -> assemble -> persist -> load) over a real .f1cap, so
it exercises the full struct set against real game bytes and the real SQLite round trip -
things a sandboc with synthetic structs cannot. It is skipped unless a fixture is provided.

Point it at a capture by setting the F1_FIXTURE environment variable, eg::

    F1_FIXTURE=my_race.f1cap python -m unittest f1telemetry.test.test_ingest_pipeline

or drop a file at one of the default paths below. Keep both a 2025 and a 2026 capture around
and run it against each; the assertions are invariants, so they hold for any real session.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from f1telemetry.src.protocol.enums import SessionType
from f1telemetry.src.storage.sessions import SessionStore

_DEFAULT_FIXTURES = ("captures/fixture.f1cap", "test/fixtures/sample.f1cap")


def _find_fixture() -> str | None:
    """Return a path to a capture file to use as a fixture, or None if none is found."""
    env = os.environ.get("F1_FIXTURE")
    if env and Path(env).is_file():
        return env
    for candidate in _DEFAULT_FIXTURES:
        if Path(candidate).is_file():
            return candidate
    return None


_FIXTURE = _find_fixture()


@unittest.skipUnless(_FIXTURE, "set F1_FIXTURE to a real capture file to run this test")
class IngestPipelineTest(unittest.TestCase):
    """Test the parse -> assemble -> persist pipeline against a real capture file."""
    def setUp(self):
        """Set up a temporary SQLite database for the test."""
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.store = SessionStore(f"sqlite:///{self.db_path}")
        from f1telemetry.src.storage.laps import LapStore
        self.trace_dir = tempfile.mkdtemp(prefix="_traces")
        self.lap_store = LapStore(f"sqlite:///{self.db_path}", trace_dir=self.trace_dir)

    def tearDown(self):
        """Clean up the temporary SQLite database."""
        self.lap_store.close()
        os.unlink(self.db_path)
        shutil.rmtree(self.trace_dir, ignore_errors=True)

    def test_capture_ingest_and_round_trips(self):
        """Test that a capture can be ingested and its sessions round-trip through the store."""
        from f1telemetry.src.pipeline import ingest_capture
        sessions = ingest_capture(_FIXTURE, self.store)
        self.assertTrue(sessions, "The capture produced no sessions")

        for original in sessions:
            # recorded_at is stamped from the capture's per-packet recv_time, not ingest time,
            # so two attempts of one session get distinct chronological timestamps.
            self.assertIsInstance(original.recorded_at, datetime,
                                  "session was not stamped with a capture recorded_at")
            loaded = self.store.load(original.session_uid)
            self.assertIsNotNone(loaded, f"Session {original.session_uid} not in the store")
            self.assertEqual(loaded.session_uid, original.session_uid, "Loaded session does not match original")
            self.assertEqual(loaded.game_format, original.game_format, "Loaded session game format does not match original")
            self.assertEqual(loaded.session_type, original.session_type, "Loaded session type does not match original")
            # Classification presence must survive the round trip.
            self.assertEqual(loaded.classification is None, original.classification is None,
                             "Loaded session classification does not match Original")
            
        # the pipeline should have produced some conteent: at least one session with laps,
        # or a classification wiht a properly named winner.
        produced_content = any(session.laps for session in sessions) or any(
            session.classification and session.classification.winner and session.classification.winner.driver_name 
            for session in sessions
        )
        self.assertTrue(produced_content, "no laps or classification were assembled")

    def test_race_sessions_have_a_classification(self):
        """Test that race sessions have a classification after ingest. This is a regression test for a bug where
        the assembler would emit a race session without a classification if the capture was missing a
        classification packet. The assembler should always produce a classification for a race session, even if
        it is empty.
        """
        from f1telemetry.src.pipeline import ingest_capture
        sessions = ingest_capture(_FIXTURE, self.store)
        races = [s for s in sessions if s.session_type == SessionType.RACE]
        for race in races:
            loaded = self.store.load(race.session_uid)
            self.assertIsNotNone(loaded.classification, "a race should persist a classification")
            self.assertTrue(loaded.classification.entries, "race classification has no entries")

    def test_reingest_skips_a_deleted_session(self):
        """A session deleted from the store is not resurrected by re-ingesting its capture."""
        from f1telemetry.src.pipeline import ingest_capture
        first = ingest_capture(_FIXTURE, self.store)
        self.assertTrue(first, "The capture produced no sessions")

        victim = first[0].session_uid
        self.store.delete(victim)
        self.assertIsNone(self.store.load(victim))

        resaved = ingest_capture(_FIXTURE, self.store)
        self.assertNotIn(victim, {s.session_uid for s in resaved})   # skipped, not returned
        self.assertIsNone(self.store.load(victim))                   # still gone from the store
        # a sibling from the same capture is re-stored as normal
        if len(first) > 1:
            self.assertIsNotNone(self.store.load(first[1].session_uid))

    def test_ingest_with_lap_store_persists_laps_and_traces(self):
        """With a LapStore supplied, ingest writes the player's laps + their traces (the app path).

        Mirrors what the IngestWorker now does: pass a LapStore to ingest_capture, then confirm a
        session that assembled laps has them (with a dense trace) readable back out of the store.
        """
        from f1telemetry.src.pipeline import ingest_capture
        sessions = ingest_capture(_FIXTURE, self.store, lap_store=self.lap_store)
        self.assertTrue(sessions, "The capture produced no sessions")

        with_laps = [s for s in sessions if s.laps]
        if not with_laps:
            self.skipTest("this fixture assembled no player laps")
        session = with_laps[0]
        stored = self.lap_store.list(session.session_uid)
        self.assertEqual(len(stored), len(session.laps), "not every assembled lap was persisted")
        hydrated = self.lap_store.load(session.session_uid, stored[0].lap_number)
        self.assertIsNotNone(hydrated.trace, "a persisted lap has no dense trace")
        self.assertGreater(len(hydrated.trace), 0, "the persisted trace is empty")


if __name__ == "__main__":
    unittest.main()