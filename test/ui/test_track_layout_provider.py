"""Canonical track-layout caching and its invalidation (PRIORITIES -> ALL), over fake stores."""
from tracemalloc import Trace
import unittest
from dataclasses import dataclass, field

import numpy as np

from f1telemetry.src.ui.laps.track_layout import TrackLayoutProvider


@dataclass
class _Trace:
    """The slice of LapTrace build_layout touches: has_motion + three parallel arrays."""
    has_motion: bool = True
    distance: np.ndarray = field(default_factory=lambda: np.array([0.0, 100.0, 20]))
    pos_x: np.ndarray = field(default_factory=lambda: np.array([0.0, 10.0, 20]))
    pos_z: np.ndarray = field(default_factory=lambda: np.array([0.0, 5.0, 20]))


@dataclass
class _Lap:
    lap_number: int
    is_valid: bool = True
    trace: _Trace | None = field(default_factory=lambda: _Trace())


@dataclass
class _Session:
    session_uid: str
    weekend_link_id: int = 7
    track_id: int = 3


class _SessionStore:
    def __init__(self, sessions):
        self._sessions = {s.session_uid: s for s in sessions}

    def load(self, uid):
        return self._sessions.get(uid)

    def list_sessions(self):
        return list(self._sessions.values())


class _LapStore:
    """Counts load() calls, so "did it rebuild?" is observable without touching the layout."""

    def __init__(self, laps_by_uid):
        self.laps = laps_by_uid
        self.load_calls = 0

    def list(self, uid):
        return tuple(self.laps.get(str(uid), ()))

    def load(self, uid, lap_number):
        self.load_calls += 1
        for lap in self.laps.get(str(uid), ()):
            if lap.lap_number == lap_number:
                return lap
        return None


class TrackLayoutProviderTest(unittest.TestCase):
    def _provider(self, laps):
        sessions = _SessionStore([_Session("100")])
        store = _LapStore({"100": laps})
        return TrackLayoutProvider(sessions, store), store

    def test_layout_is_built_once_and_memoised(self):
        provider, store = self._provider([_Lap(1), _Lap(2), _Lap(3)])
        first = provider.layout_for("100")
        after_build = store.load_calls
        second = provider.layout_for("100")

        self.assertIsNotNone(first)
        self.assertIs(first, second)                    # same object, not a rebuild
        self.assertEqual(store.load_calls, after_build)  # no further trace reads

    def test_invalidate_forces_a_rebuild(self):
        provider, store = self._provider([_Lap(1), _Lap(2), _Lap(3)])
        provider.layout_for("100")
        after_build = store.load_calls

        provider.invalidate()
        provider.layout_for("100")
        self.assertGreater(store.load_calls, after_build)

    def test_invalidate_drops_a_cached_none(self):
        """The A1 bug's real shape: "too few laps" is cached too, and a re-ingest can fix it."""
        laps = [_Lap(1), _Lap(2)]                       # below build_layout's minimum of 3
        provider, store = self._provider(laps)
        self.assertIsNone(provider.layout_for("100"))

        laps.append(_Lap(3))                            # a re-ingest adds the third Motion lap
        self.assertIsNone(provider.layout_for("100"))   # still stale: the None was cached
        provider.invalidate()
        self.assertIsNotNone(provider.layout_for("100"))

    def test_invalid_and_motionless_laps_are_ignored(self):
        provider, _ = self._provider(
            [_Lap(1), _Lap(2), _Lap(3, is_valid=False), _Lap(4, trace=_Trace(has_motion=False))]
        )
        self.assertIsNone(provider.layout_for("100"))   # only 2 usable laps

    def test_unknown_session_returns_none(self):
        provider, _ = self._provider([_Lap(1), _Lap(2), _Lap(3)])
        self.assertIsNone(provider.layout_for("999"))


if __name__ == "__main__":
    unittest.main()