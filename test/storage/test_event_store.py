"""EventStore - the session_events round trip, and the LapStore contract it copies.

The events themselves were settled against all 33 captures before any code was written
(TELEMETRY_NOTES -> "Event packets"); what is tested here is only that storing them and reading
them back changes nothing. Two things get more attention than their size suggests: the optional
penalty fields, where None ("not applicable") and 0 are genuinely different answers, and
replace-by-uid, which is the whole reason a re-ingest is safe to run twice.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from f1telemetry.src.domain.models import SessionOvertake, SessionPenalty
from f1telemetry.src.storage.events import EventStore


def make_penalty(lap: int = 3, frame: int = 1000, **kwargs) -> SessionPenalty:
    """A time penalty for car 4, with every optional field populated."""
    fields = dict(
        vehicle_index=4, penalty_type=4, infringement_type=13, lap_number=lap,
        other_vehicle_index=9, time_s=5, places_gained=2,
        session_time_s=421.5, frame=frame,
    )
    fields.update(kwargs)
    return SessionPenalty(**fields)


def make_overtake(frame: int = 2000, **kwargs) -> SessionOvertake:
    fields = dict(overtaking_vehicle_index=4, overtaken_vehicle_index=11, lap_number=6,
                  session_time_s=812.25, frame=frame)
    fields.update(kwargs)
    return SessionOvertake(**fields)


class EventStoreRoundTripTest(unittest.TestCase):
    def setUp(self):
        fd, self._db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.store = EventStore(f"sqlite:///{self._db}")
        self.addCleanup(os.unlink, self._db)
        self.addCleanup(self.store.close)

    def test_a_penalty_round_trips_whole(self):
        self.store.save_events(123, (make_penalty(),))
        penalty, = self.store.load_penalties(123)
        self.assertEqual(penalty, make_penalty(), "a penalty must survive storage unchanged")

    def test_an_overtake_round_trips_whole(self):
        self.store.save_events(123, (), (make_overtake(),))
        overtake, = self.store.load_overtakes(123)
        self.assertEqual(overtake, make_overtake(), "a pass must survive storage unchanged")

    def test_the_not_applicable_fields_read_back_none_and_not_a_coerced_zero(self):
        """The wire's 255 sentinel is None by the time it reaches here, and must stay None.

        ``places_gained`` is the field that makes this load-bearing rather than tidy: it is
        legitimately 0 in 73 of 127 measured penalties, so a mapping that turned "not applicable"
        into 0 would silently claim the driver gained no places.
        """
        self.store.save_events(123, (make_penalty(other_vehicle_index=None, time_s=None,
                                                  places_gained=None),))
        penalty, = self.store.load_penalties(123)
        for field in ("other_vehicle_index", "time_s", "places_gained"):
            with self.subTest(field=field):
                self.assertIsNone(getattr(penalty, field))

    def test_a_real_zero_stays_zero(self):
        self.store.save_events(123, (make_penalty(places_gained=0),))
        penalty, = self.store.load_penalties(123)
        self.assertEqual(penalty.places_gained, 0)
        self.assertIsNotNone(penalty.places_gained)

    def test_a_replay_recovered_penalty_keeps_its_zero_frame(self):
        """37% of penalties arrive only in the end-of-session replay, and carry frame 0."""
        self.store.save_events(123, (make_penalty(frame=0),))
        penalty, = self.store.load_penalties(123)
        self.assertEqual(penalty.frame, 0)

    def test_the_two_codes_do_not_leak_into_each_other(self):
        """One table, two codes: each reader must return only its own rows."""
        self.store.save_events(123, (make_penalty(),), (make_overtake(), make_overtake()))
        self.assertEqual(len(self.store.load_penalties(123)), 1)
        self.assertEqual(len(self.store.load_overtakes(123)), 2)

    def test_penalties_read_back_ordered_by_lap_then_frame(self):
        stored = (make_penalty(lap=5, frame=900), make_penalty(lap=1, frame=800),
                  make_penalty(lap=1, frame=0))
        self.store.save_events(123, stored)
        loaded = self.store.load_penalties(123)
        self.assertEqual([(p.lap_number, p.frame) for p in loaded],
                         [(1, 0), (1, 800), (5, 900)])

    def test_overtakes_read_back_in_the_order_they_were_announced(self):
        stored = (make_overtake(frame=3000), make_overtake(frame=1000), make_overtake(frame=2000))
        self.store.save_events(123, (), stored)
        self.assertEqual([o.frame for o in self.store.load_overtakes(123)], [3000, 1000, 2000])

    def test_events_are_scoped_to_their_session(self):
        self.store.save_events(123, (make_penalty(),), (make_overtake(),))
        self.store.save_events(456, (make_penalty(), make_penalty()))
        self.assertEqual(len(self.store.load_penalties(123)), 1)
        self.assertEqual(len(self.store.load_penalties(456)), 2)
        self.assertEqual(self.store.load_overtakes(456), ())

    def test_a_session_with_no_events_reads_back_empty(self):
        self.assertEqual(self.store.load_penalties(999), ())
        self.assertEqual(self.store.load_overtakes(999), ())

    # --- the LapStore contract ------------------------------------------------
    def test_resave_replaces_by_uid(self):
        self.store.save_events(123, (make_penalty(), make_penalty()), (make_overtake(),))
        self.store.save_events(123, (make_penalty(),))
        self.assertEqual(len(self.store.load_penalties(123)), 1, "old rows must not survive")
        self.assertEqual(self.store.load_overtakes(123), (), "the other code is replaced too")

    def test_resave_with_nothing_clears_the_session(self):
        """A re-ingest that produced no events must leave none behind - the replace is the point."""
        self.store.save_events(123, (make_penalty(),), (make_overtake(),))
        self.store.save_events(123)
        self.assertEqual(self.store.load_penalties(123), ())
        self.assertEqual(self.store.load_overtakes(123), ())

    def test_resave_leaves_other_sessions_alone(self):
        self.store.save_events(123, (make_penalty(),))
        self.store.save_events(456, (make_penalty(),))
        self.store.save_events(123, ())
        self.assertEqual(len(self.store.load_penalties(456)), 1)

    def test_delete_removes_both_codes_and_counts_them(self):
        self.store.save_events(123, (make_penalty(), make_penalty()), (make_overtake(),))
        self.assertEqual(self.store.delete(123), 3, "the count covers both codes")
        self.assertEqual(self.store.load_penalties(123), ())
        self.assertEqual(self.store.load_overtakes(123), ())

    def test_delete_of_an_unknown_uid_is_a_clean_no_op(self):
        self.assertEqual(self.store.delete(999), 0)

    def test_uint64_high_bit_uid(self):
        """session_uid is TEXT for this reason: the real ones overflow SQLite's INTEGER."""
        big = 0x8000_0000_0000_0000
        self.store.save_events(big, (make_penalty(),))
        self.assertEqual(len(self.store.load_penalties(big)), 1)
        self.assertEqual(self.store.load_penalties(big + 1), ())

    def test_an_int_uid_and_a_str_uid_are_the_same_session(self):
        """Callers pass both (the pipeline an int, the UI a str); the store keys on the text."""
        self.store.save_events(123, (make_penalty(),))
        self.assertEqual(len(self.store.load_penalties("123")), 1)
        self.store.save_events("123", ())
        self.assertEqual(self.store.load_penalties(123), ())

    def test_it_is_a_context_manager_and_closes_twice_safely(self):
        with EventStore(f"sqlite:///{self._db}") as store:
            store.save_events(777, (make_penalty(),))
        self.assertEqual(len(self.store.load_penalties(777)), 1)
        self.store.close()
        self.store.close()


class EventTableCreationTest(unittest.TestCase):
    """``session_events`` is a brand-new table, so create_all makes it and ensure_schema skips it.

    The ``deleted_sessions`` / ``captures`` / ``meta`` precedent, checked rather than assumed: this
    is what makes PIPELINE_VERSION 5 need no migration on a database created before it.
    """

    def test_an_existing_database_gains_the_table_when_any_store_opens_it(self):
        from sqlalchemy import inspect
        from f1telemetry.src.storage.sessions import SessionStore

        fd, db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(os.unlink, db)
        url = f"sqlite:///{db}"

        with SessionStore(url) as sessions:
            # simulate a pre-E15 database: drop the table create_all just made
            with sessions._engine.begin() as conn:
                from sqlalchemy import text
                conn.execute(text("DROP TABLE session_events"))
            self.assertNotIn("session_events", inspect(sessions._engine).get_table_names())

        with EventStore(url) as events:
            self.assertIn("session_events", inspect(events._engine).get_table_names())
            events.save_events(1, (make_penalty(),))
            self.assertEqual(len(events.load_penalties(1)), 1)


if __name__ == "__main__":
    unittest.main()
