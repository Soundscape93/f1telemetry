"""Candidate-lap enumeration for the overlay (comparison.candidate_laps), over fake stores."""
import unittest
from dataclasses import dataclass
from datetime import datetime

from f1telemetry.src.ui.laps import comparison


@dataclass
class _Lap:
    lap_number: int
    lap_time_ms: int | None = None


@dataclass
class _Session:
    session_uid: str
    weekend_link_id: int
    session_link_id: int = 0
    session_type: int = 15
    weekend_structure: tuple = ()
    recorded_at: datetime | None = None     # orders a slot's attempts (weekend_slots)


class _SessionStore:
    def __init__(self, sessions):
        self._sessions = sessions

    def list_sessions(self):
        return list(self._sessions)


class _LapStore:
    def __init__(self, laps_by_uid):
        self._laps = laps_by_uid

    def list(self, uid):
        return tuple(self._laps.get(str(uid), ()))


class CandidateLapsTest(unittest.TestCase):
    def _stores(self):
        sessions = _SessionStore([
            _Session("100", weekend_link_id=7, session_link_id=0),   # base session
            _Session("101", weekend_link_id=7, session_link_id=1),   # same weekend
            _Session("200", weekend_link_id=9, session_link_id=0),   # different weekend
        ])
        laps = _LapStore({
            "100": [_Lap(1, 95000), _Lap(2, 93000), _Lap(3, 94000)],
            "101": [_Lap(1, 99000)],
            "200": [_Lap(1, 80000)],
        })
        return sessions, laps

    def test_excludes_base_lap_from_same_session(self):
        sessions, laps = self._stores()
        groups = comparison.candidate_laps(sessions, laps, "100", 2)
        nums = [ref.lap_number for ref in groups[comparison.SCOPE_SESSION]]
        self.assertEqual(nums, [1, 3])              # lap 2 (the base) omitted

    def test_best_is_fastest_non_base_lap(self):
        sessions, laps = self._stores()
        groups = comparison.candidate_laps(sessions, laps, "100", 1)
        best = groups[comparison.SCOPE_BEST]
        self.assertEqual([ref.lap_number for ref in best], [2])   # 93000 is fastest of laps 2,3

    def test_weekend_scope_covers_only_sibling_sessions(self):
        sessions, laps = self._stores()
        groups = comparison.candidate_laps(sessions, laps, "100", 1)
        uids = {ref.session_uid for ref in groups[comparison.SCOPE_WEEKEND]}
        self.assertEqual(uids, {"101"})             # 200 is a different weekend, base 100 excluded
