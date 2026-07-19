"""Canonical track layout - a distance-resampled median racing line from many laps.

The 2b TrackMap draws the *selected* lap's raw pos_x/pos_z, so the circuit's shape shifts lap to
lap (defending, a missed apex, an off-track moment, a wider line). This module aggregates the many
laps of a race weekend into one clean, stable outline: resample every lap's world position onto a
fixed distance grid and take the per-point median.

Why a fresh grid instead of analysis.traces.align: align() shrinks to the laps' shared *overlap*,
which throws away the start/finish straight a race lap 1 misses (it begins at the grid slot, past
the S/F line). A min-start..max-end grid with out-of-range samples masked to NaN keeps every metre
any single lap covers, and the median self-heals a lap's gap because the others span it. No
alignment step is needed because F1 track world coordinates are fixed geometry - the same point on
track is the same pos_x/pos_z across laps and sessions.

Pure numpy, Qt-free and store-free (the weekend lap gathering lives in ui/laps/track_layouts.py),
so it is unit-testable in isolation.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from ..domain.models import LapTrace

_MIN_LAPS = 3       # fewer usable Motion traces than this -> caller falls back to the driven line
_GRID_NUM = 1000    # points on the canonical distance grid

# Sector colours, shared by the track map and the trace boundary markers: sector 1 / 2 / 3.
SECTOR_COLOURS = ("#e10600", "#00c0e4", "#f6d411")      # red, cyan, yellow


def sector_bounds(distance, sector2_start: float, sector3_start: float) -> tuple[int, int]:
    """Split an ascending distance axis into three sectors.
    
    Returns ``(i2, i3)``: ``distance[:i2]`` is sector 1, ``distance[i2:i3]`` is sector 2 and
    ``distance[i3:]`` is sector 3. ``searchsorted`` is exact on the sorted lap-distance grid and
    clamps to the ends, so a boundary past the covered range just yields an empty sector (e.g. a
    race lap-1 line starting after the S/F line gives an empty sector 1).
    """
    i2 = int(np.searchsorted(distance, sector2_start, side="left"))
    i3 = int(np.searchsorted(distance, sector3_start, side="left"))
    return i2, i3


@dataclass(frozen=True)
class TrackLayout:
    """A canonical circuit outline: world positon sampled on a fixed distance grid.
    
    ``distance`` runs from the earliest lap start to the latest lap end (meters, ~0..track_length);
    ``pos_x`` and ``pos_z`` are the per-point median world positions across the laps it was built from.
    All three are parallel and the same length. Raw world coords are kept - the handedness and
    loop-close corrections belong to rendering (TrackMap) - so no coordinate-frame choice is baked
    in here, and the grid stays distance-indexed for the hover marker.
    """

    distance: np.ndarray
    pos_x: np.ndarray
    pos_z: np.ndarray

    def __len__(self) -> int:
        return len(self.distance)


def build_layout(traces: Sequence[LapTrace], *, num: int = _GRID_NUM,
                 min_laps: int = _MIN_LAPS) -> TrackLayout | None:
    """Median racing line from ``traces``, or None if fewer than ``min_laps`` carry Motion.
    
    Each usable trace is interpolated onto one shared distance grid; grid points outside a lap's
    own distance span are set to NaN so that lap doesn't vote where it has no data. The per-point
    ``nanmedian``is robust to single-lap excursions and fills the S/F gap from the laps that cover
    it. The grid spans the earliest start to the latest end across the laps, so its endpoints are
    always covered by at least one lap (no leading/trailing NaN).
    """
    usable = [t for t in traces if t.has_motion]
    if len(usable) < min_laps:
        return None
    start = min(t.distance[0] for t in usable)
    end = max(t.distance[-1] for t in usable)
    grid = np.linspace(start, end, num=num)
    xs = np.empty((len(usable), num))
    zs = np.empty((len(usable), num))
    for i, trace in enumerate(usable):
        d = np.asanyarray(trace.distance, dtype=float)
        outside = (grid < d[0]) | (grid > d[-1])        # np.interp clamps; we want NaN past the span
        px = np.interp(grid, d, np.asanyarray(trace.pos_x, dtype=float))
        pz = np.interp(grid, d, np.asanyarray(trace.pos_z, dtype=float))
        px[outside] = np.nan
        pz[outside] = np.nan
        xs[i] = px
        zs[i] = pz
    with np.errstate(invalid="ignore"):     # an all-NaN column would warn; the grid spans real data
        pos_x = np.nanmedian(xs, axis=0)
        pos_z = np.nanmedian(zs, axis=0)
    return TrackLayout(distance=grid, pos_x=pos_x, pos_z=pos_z)