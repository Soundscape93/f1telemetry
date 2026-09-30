"""E1e's pipeline half: which ingests place career sessions automatically, and what they write.

``domain/placement`` decides where a career session goes, and ``test/domain/test_placement`` tests
that; this is the wiring around it, on real SQLite stores. A fresh recording and an import's new
captures place the sessions they stored for the first time, and a failure while placing never
undoes a stored recording. A re-ingest and a restore place nothing because neither takes a season
store, so there is nothing here to test for them. ``ingest`` is injected with a double that saves
through the real store and stamps ``recorded_at`` time-zone aware, as ``ingest_capture`` does - a
stored row reads back naive, and ``TimeZoneTest`` is there for that difference.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from dataclasses import replace
from datetime import timedelta, timezone

from f1telemetry.src.domain.calendars import official_calendar
from f1telemetry.src.domain.placement import CareerPlan, HoldReason
from f1telemetry.src.domain.season import SeasonMode
from f1telemetry.src.ingest.recording import write_header, write_packet
from f1telemetry.src.pipeline import (CareerAssignment, ImportCandidate, archive_and_ingest,
                                      assign_career_sessions, import_captures)
from f1telemetry.src.storage.captures import CaptureStore
from f1telemetry.src.storage.seasons import SeasonStore
from f1telemetry.src.storage.sessions import SessionStore
from f1telemetry.test.domain.test_placement import career_weekend

_MELBOURNE, _SHANGHAI, _SUZUKA = 0, 2, 13       # rounds 1, 2 and 3 of the 2026 calendar


def _aware(sessions):
    """The sessions as ``ingest_capture`` returns them: ``recorded_at`` in UTC, time-zone aware."""
    return [replace(s, recorded_at=s.recorded_at.replace(tzinfo=timezone.utc)) for s in sessions]


class _Ingest:
    """Stands in for ``ingest_capture``: saves what each capture holds through the real store."""

    def __init__(self, holdings: dict[str, list]):
        self.holdings = holdings

    def __call__(self, path, store, lap_store=None, event_store=None, capture_store=None,
                 recorded_by=None):
        held = self.holdings.get(os.path.basename(path), [])
        for session in held:
            store.save(session)
        return list(held)


class _CareerTestCase(unittest.TestCase):
    """A Driver Career season on the 2026 calendar, whose Melbourne weekend is stored in round 1."""

    def setUp(self) -> None:
        self.temp = tempfile.mkdtemp(prefix="career_")
        self.addCleanup(lambda: shutil.rmtree(self.temp, ignore_errors=True))
        url = f"sqlite:///{os.path.join(self.temp, 'test.db')}"
        self.sessions = SessionStore(url)
        self.addCleanup(self.sessions.close)
        self.seasons = SeasonStore(url)
        self.addCleanup(self.seasons.close)
        self.captures = CaptureStore(url)
        self.addCleanup(self.captures.close)
        self.source = os.path.join(self.temp, "shared")
        self.home = os.path.join(self.temp, "captures")
        os.makedirs(self.source)
        self.recordings = 0

        self.season_id = self.seasons.create_season(
            SeasonMode.DRIVER_CAREER, 1, 2026, rounds=official_calendar(2026)).season_id
        for session in _aware(career_weekend(0, _MELBOURNE, day=4)):
            self.sessions.save(session)
            self.seasons.assign_session(session.session_uid, self.season_id, 1)
        self.shanghai = _aware(career_weekend(1, _SHANGHAI, day=11))
        self.race = self.shanghai[-1]

    def placed(self) -> dict[int, int]:
        """Every session placed in the season, and its round."""
        return {uid: number for number, uid in self.seasons.assignments_for_season(self.season_id)}

    @staticmethod
    def attempt(session, minutes: int, uid: int):
        """Another attempt at ``session``'s slot, ``minutes`` after it - before it, if negative."""
        return replace(session, session_uid=uid,
                       recorded_at=session.recorded_at + timedelta(minutes=minutes))

    def record(self, sessions, **kwargs):
        """A fresh recording holding ``sessions``, through ``archive_and_ingest`` like the app."""
        self.recordings += 1
        self.raw = os.path.join(self.temp, f"recording{self.recordings}.f1cap")
        with open(self.raw, "wb") as fh:
            write_header(fh)
            write_packet(fh, 0.0, bytes(24))
        kwargs.setdefault("season_store", self.seasons)
        ingest = _Ingest({os.path.basename(self.raw) + ".zst": sessions})
        return archive_and_ingest(self.raw, self.sessions, ingest=ingest, **kwargs)

    def import_(self, holdings: dict[str, list], **kwargs):
        """An import of one capture per ``holdings`` entry, each holding the sessions listed."""
        candidates = []
        for name in holdings:
            path = os.path.join(self.source, name)
            with open(path, "w") as fh:
                fh.write(name)
            candidates.append(ImportCandidate(path=path, file_name=name,
                                              file_size=os.path.getsize(path)))
        kwargs.setdefault("season_store", self.seasons)
        return import_captures(candidates, self.captures, self.sessions, captures_dir=self.home,
                               hash_file=lambda path: os.path.basename(path).ljust(64, "0"),
                               ingest=_Ingest(holdings), **kwargs)


class RecordingTest(_CareerTestCase):
    """``archive_and_ingest`` given a season store - what a fresh recording places."""

    def test_a_new_weekend_is_placed_in_its_round(self):
        sessions, _, _, career = self.record(self.shanghai)
        uids = [s.session_uid for s in self.shanghai]
        self.assertEqual(7, len(sessions))
        self.assertEqual(CareerAssignment(CareerPlan(
            assigned=tuple((uid, (self.season_id, 2)) for uid in uids))), career)
        self.assertEqual({uid: 2 for uid in uids},
                         {uid: number for uid, number in self.placed().items() if uid in uids})

    def test_without_a_season_store_nothing_is_placed(self):
        *_, career = self.record(self.shanghai, season_store=None)
        self.assertEqual(CareerAssignment(), career)
        self.assertEqual({1}, set(self.placed().values()))

    def test_a_session_stored_before_the_recording_is_not_new(self):
        """The recording stores it again, but not for the first time, so it is left to the user."""
        self.sessions.save(self.race)
        *_, career = self.record(self.shanghai)
        self.assertEqual(6, len(career.plan.assigned))
        self.assertNotIn(self.race.session_uid, self.placed())

    def test_a_later_attempt_recorded_separately_replaces_the_earlier_one(self):
        self.record(self.shanghai)
        *_, career = self.record([self.attempt(self.race, 30, uid=777)])
        self.assertEqual(CareerPlan(assigned=((777, (self.season_id, 2)),),
                                    unassigned=((self.race.session_uid, (self.season_id, 2)),)),
                         career.plan)
        self.assertEqual(2, self.placed()[777])
        self.assertNotIn(self.race.session_uid, self.placed())

    def test_placing_waits_until_the_raw_capture_is_deleted(self):
        raw_there: list[bool] = []
        list_seasons = self.seasons.list_seasons

        def watching():
            raw_there.append(os.path.exists(self.raw))
            return list_seasons()

        self.seasons.list_seasons = watching
        self.record(self.shanghai)
        self.assertEqual([False], raw_there)

    def test_a_failure_while_placing_leaves_the_recording_stored(self):
        def failing(assign, unassign=()):
            raise OSError("disk I/O error")

        self.seasons.apply_placements = failing
        with self.assertLogs("f1telemetry.src.pipeline", level="ERROR"):
            sessions, archive_path, _, career = self.record(self.shanghai)
        self.assertEqual(CareerAssignment(error="disk I/O error"), career)
        self.assertEqual(7, len(sessions))
        self.assertTrue(os.path.exists(archive_path))
        self.assertFalse(os.path.exists(self.raw))
        self.assertLessEqual({s.session_uid for s in self.shanghai}, self.sessions.stored_uids())
        self.assertEqual({1}, set(self.placed().values()))


class ImportTest(_CareerTestCase):
    """``import_captures`` given a season store - what an import's new captures place."""

    def test_the_new_captures_are_placed_after_the_pass(self):
        suzuka = _aware(career_weekend(2, _SUZUKA, day=18))
        summary = self.import_({"shanghai.f1cap.zst": self.shanghai, "suzuka.f1cap.zst": suzuka})
        self.assertEqual(14, len(summary.career.plan.assigned))
        placed = self.placed()
        self.assertEqual({2}, {placed[s.session_uid] for s in self.shanghai})
        self.assertEqual({3}, {placed[s.session_uid] for s in suzuka})

    def test_after_a_cancel_what_was_imported_is_placed(self):
        suzuka = _aware(career_weekend(2, _SUZUKA, day=18))
        polls = iter([False, True])             # polled before each capture: stop before Suzuka
        summary = self.import_({"shanghai.f1cap.zst": self.shanghai, "suzuka.f1cap.zst": suzuka},
                               cancelled=lambda: next(polls))
        self.assertTrue(summary.cancelled)
        self.assertEqual(7, len(summary.career.plan.assigned))
        self.assertEqual({2}, {self.placed()[s.session_uid] for s in self.shanghai})

    def test_a_session_already_stored_is_not_new(self):
        """A renamed copy of a recording already held: the ingest stores it again, nothing more."""
        self.sessions.save(self.race)
        summary = self.import_({"copy.f1cap.zst": self.shanghai})
        self.assertEqual(6, len(summary.career.plan.assigned))
        self.assertNotIn(self.race.session_uid, self.placed())

    def test_without_a_season_store_nothing_is_placed(self):
        summary = self.import_({"shanghai.f1cap.zst": self.shanghai}, season_store=None)
        self.assertEqual(CareerAssignment(), summary.career)
        self.assertEqual({1}, set(self.placed().values()))


class AssignCareerSessionsTest(_CareerTestCase):
    """``assign_career_sessions`` called directly."""

    def test_nothing_new_reads_nothing(self):
        self.assertEqual(CareerAssignment(), assign_career_sessions([], None, None))

    def test_a_hold_is_logged_with_both_rounds(self):
        """The user cannot see why rounds disagree without both numbers, so the log keeps them."""
        suzuka = _aware(career_weekend(1, _SUZUKA, day=11))        # index round 2, track round 3
        for session in suzuka:
            self.sessions.save(session)
        with self.assertLogs("f1telemetry.src.pipeline", level="INFO") as logs:
            career = assign_career_sessions([s.session_uid for s in suzuka], self.sessions,
                                            self.seasons)
        self.assertEqual({HoldReason.ROUNDS_DISAGREE}, {hold.reason for hold in career.plan.held})
        self.assertIn("ROUNDS_DISAGREE (track round 3, index round 2)", "\n".join(logs.output))


@unittest.skipUnless(hasattr(time, "tzset"), "needs time.tzset to change the local time zone")
class TimeZoneTest(_CareerTestCase):
    """The rule sees stored rows only, so the local time zone cannot reorder two attempts.

    A stored ``recorded_at`` reads back naive, and Python reads a naive time as local time, so a
    fresh session and a stored one compare a UTC offset apart. East of UTC that would make an older
    attempt imported later look like the latest; west of it, a new recording look older than the
    attempt it follows. Both zones are POSIX rules, so they need no time zone database.
    """

    def in_zone(self, rule: str) -> None:
        saved = os.environ.get("TZ")

        def restore():
            if saved is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = saved
            time.tzset()

        self.addCleanup(restore)
        os.environ["TZ"] = rule
        time.tzset()
        self.assertNotEqual(0, time.timezone, "the zone must differ from UTC to test anything")

    def test_east_of_utc_an_older_attempt_imported_later_is_held(self):
        self.in_zone("CET-1CEST,M3.5.0,M10.5.0/3")             # Europe/Zurich
        self.record(self.shanghai)
        summary = self.import_({"older.f1cap.zst": [self.attempt(self.race, -30, uid=777)]})
        self.assertEqual([HoldReason.SUPERSEDED], [h.reason for h in summary.career.plan.held])
        self.assertEqual(2, self.placed()[self.race.session_uid])
        self.assertNotIn(777, self.placed())

    def test_west_of_utc_a_new_recording_replaces_the_attempt_it_follows(self):
        self.in_zone("EST5EDT,M3.2.0,M11.1.0")                 # America/New_York
        self.record(self.shanghai)
        *_, career = self.record([self.attempt(self.race, 30, uid=777)])
        self.assertEqual(((777, (self.season_id, 2)),), career.plan.assigned)
        self.assertNotIn(self.race.session_uid, self.placed())


if __name__ == "__main__":
    unittest.main()
