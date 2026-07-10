"""Canonical track-layout provider for the lap detail map - gathers a weekend's laps and caches.

The TrackMap wants one clean outline per track rather than the driven lap's line. Building it needs
the world position of *many* laps, which are spread across the sessions of a race weekend (practice,
qualifying, race) - a cross-store walk: SessionStore holds each session's track_id/weekend_link_id,
LapStore holds the laps and their Parquet traces. This collaborator does that walk once per weekend
and memoises the result (analysis.track_layout does the pure numpy). Mirrors ui/laps/comparison.py.

Aggregating over the whole weekend (not one session) matters: a qualifying session alone often has
only one or two usable timed laps, below the median's minimum. Practice + quali + race together give
plenty. Laps are filtered to valid + Motion-carrying; below the threshold the provider returns None
and the caller falls back to the selected lap's raw line.
"""
from __future__ import annotations

from ...analysis.track_layout import TrackLayout, build_layout


class TrackLayoutProvider:
    """Builds and caches a canonical TrackLayout per race weekend (keyed by weekend + track)."""

    def __init__(self, session_store, lap_store):
        self._sessions = session_store
        self._laps = lap_store
        self._cache: dict[tuple[int, int], TrackLayout | None] = {}
    
    def layout_for(self, base_uid:str) -> TrackLayout | None:
        """Canonical layout for the weekend the given session belongs to, or None to fall back.
        
        Walks every session sharing this one's ``weekend_link_id``at the same ``track_id``, loads
        their valid Motion laps, and builds the median line. Returns None (cached too) when the
        weekend has fewer than the median's minimum usable laps, or the session isn't stored.
        """
        base = self._sessions.load(base_uid)
        if base is None:
            return None
        key = (base.weekend_link_id, base.track_id)
        if key not in self._cache:
            self._cache[key] = build_layout(self._weekend_traces(base))
        return self._cache[key]
    
    def _weekend_traces(self, base) -> list:
        """Every valid, Motion-carrying lap trace across the base session's race weekend."""
        traces = []
        for session in self._sessions.list_sessions():
            if (session.weekend_link_id != base.weekend_link_id
                    or session.track_id != base.track_id):
                continue
            uid = str(session.session_uid)
            for lap in self._laps.list(uid):                # cheap; no traces read
                if not lap.is_valid:
                    continue
                full = self._laps.load(uid, lap.lap_number)  # this valid lap's trace
                if full is not None and full.trace is not None and full.trace.has_motion:
                    traces.append(full.trace)
        return traces
    