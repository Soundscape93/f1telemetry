"""Trace preparation for plotting - resample, align, delta, downsample (all numpy, no Qt).

A LapTrace is distance-indexed but every lap has its *own* distance samples, so before laps can
be overlaid or subtracted they must be resampled onto a shared distance grid. This module does
that and the two things built on it; the lap-to-lap **delta time** (the racing "gap" trace,
integrated from speed over distance) and the **downsampling** for the chart.

Everything is **N-series-aware**: ``align``and ``time_deltas`` operate on a *list* of traces, so
a single lap is just a length-1 list and iteration-2 overlay is UI wiring over this same API,
not a rewrite. Kept in analysis/ (not ui) and Qt-free so it's unit-testable and desktop-bound
alongside standings.

Conventions match the domain models: distance is meters, speed km/h; a positive time delta means
``other``reaches a given distance later than the reference (i.e. it's behind).
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from ..domain.models import LapTrace

# Channels whose values are categorical, not continous: linear interpolation onto a new grid
# would invent in-between values (gear 6.5), so they're rounded back to whole numbers after resample.
_DISCRETE_CHANNELS = frozenset({"gear", "drs", "ers_deploy_mode",})


@dataclass(frozen=True)
class AlignedTrace:
    """A LapTrace resampled onto a shared distance grid.
    
    ``distance`` is the common x-axis - identical across the set aligned together - and ``channels``
    maps each resampled channel to its value on that grid. ``label`` is an optional caller
    tag (e.g. "Lap 5") carrid through so an overlay Ui can key a legend/colour on it. 
    """
    distance: np.ndarray
    channels: dict[str, np.ndarray]
    label: str | None = None

    def __len__(self) -> int:
        return len(self.distance)
    
    def channel(self, name: str) -> np.ndarray:
        """The resampled values for one channel (KeyError if it wasn't among those aligned)."""
        return self.channels[name]


def shared_distance_grid(
        traces: Sequence[LapTrace], *, step: float | None = None, num: int | None = None
) -> np.ndarray:
    """A common distance axis spanning the range every given trace actually covers.
    
    Runs from the latest start to the earliest end across all traces (their overlap), so each
    trace has real data at every grid point - no extrapolation past a lap's own time. Resolution
    defaults to the median native sample spacing of the densest trace.
    """
    if not traces:
        raise ValueError("need at least one trace to build a distance grid")
    start = max(float(trace.distance[0]) for trace in traces)
    end = min(float(trace.distance[-1]) for trace in traces)
    if not end > start:
        raise ValueError("traces do not overlap in distance")
    if num is not None:
        return np.linspace(start, end, num=num)
    if step is None:
        step = _default_step(traces)
    n = max(2, int(math.floor((end - start) / step)) + 1)
    return np.linspace(start, end, num=n)


def _default_step(traces: Sequence[LapTrace]) -> float:
    """Median positive distance between consecutive samples of the densest trace (meters)."""
    ref = max(traces, key=len)
    diffs = np.diff(np.asarray(ref.distance, dtype=float))
    diffs = diffs[diffs > 0]
    return float(np.median(diffs)) if diffs.size else 1.0


def resample(
        trace: LapTrace, grid: np.ndarray, *, channels: Sequence[str] | None = None,
        label: str | None = None) -> AlignedTrace:
    """Interpolate one trace's channels onto a ``grid`` (linear; discrete channels rounded)."""
    channels = tuple(channels) if channels is not None else LapTrace.CHANNELS
    xp = np.asarray(trace.distance, dtype=float)
    out: dict[str, np.ndarray] = {}
    for name in channels:
        values = np.interp(grid, xp, np.asarray(getattr(trace, name), dtype=float))
        out[name] = np.round(values) if name in _DISCRETE_CHANNELS else values
    return AlignedTrace(distance=grid, channels=out, label=label)


def align(traces: Sequence[LapTrace], *, channels: Sequence[str] | None = None,
          grid: np.ndarray | None = None, step: float | None = None, num: int | None = None,
          labels: Sequence[str] | None = None) -> list[AlignedTrace]:
    """Resample every trace onto one shared grid (built from t he traces if ``grid``is omitted).
    
    The N-series entry point: pass one lap or many. ``labels``(optional, positional to ``traces``)
    tags each result for a legend. Returns a list of AlignedTrace sharing ``distance``.
    """
    if grid is None:
        grid = shared_distance_grid(traces, step=step, num=num)
    if labels is None:
        labels = [None] * len(traces)
    return [resample(trace, grid, channels=channels, label=label)
            for trace, label in zip(traces, labels)]


def elapsed_time(distance: np.ndarray, speed: np.ndarray) -> np.ndarray:
    """Cumulative time (seconds) to reach each distance point, integration 1/speed over distance.

    Distance is meters, speed km/h. Over a segment dt = d(distance) / v with v the segment's mean
    speed in m/s; a zero-speed segment contributes noting (guarded against div-by-zero). Returns
    an array the same length of ``distance``, starting at 0 - the basis of the lap-to-lap time delta. 
    """
    distance = np.asarray(distance, dtype=float)
    speed_ms = np.asarray(speed, dtype=float) / 3.6  # km/h -> m/s
    dd = np.diff(distance)
    v_mid = (speed_ms[:-1] + speed_ms [1:]) / 2.0
    with np.errstate(divide="ignore", invalid="ignore"):
        dt = np.where(v_mid > 0, dd / v_mid, 0.0)
    return np.concatenate(([0.0], np.cumsum(dt)))


def time_delta(reference: AlignedTrace, other: AlignedTrace) -> np.ndarray:
    """``other`` minus ``reference``: cumulative time at each shared-grid distance (seconds).
    
    Positive = ``other`` reaches that point later (it's behind). Both must be aligned on the same
    grid (see ``align``); both need a resampled ``speed`` channel.
    """
    if not np.array_equal(reference.distance, other.distance):
        raise ValueError("time delta needs traces aligned on the same distance grid")
    ref_time = elapsed_time(reference.distance, reference.channel("speed"))
    other_time = elapsed_time(other.distance, other.channel("speed"))
    return other_time - ref_time


def time_deltas(reference: AlignedTrace, others: Sequence[AlignedTrace]) -> list[np.ndarray]:
    """Time delta of each series vs one reference (the N-series overlay delta)."""
    return [time_delta(reference, other) for other in others]


def downsample(x: np.ndarray, *series: np.ndarray, max_points: int) -> tuple[np.ndarray, ...]:
    """Decimate ``x``and each parallel series together to at most ``max_points``.
    
    A uniform stride (endpoints kept) - cheap and honest for dense, evenly-sampled lap traces,
    and it reduces every series on the *same* indices so they stay aligned for plotting. Arrays
    shorter than a cap are returned unchanged. (A shape-preserving LTTB could replace the stride
    later without chaning callers.)
    """
    if max_points < 2:
        raise ValueError("max_points must be at least 2")
    x = np.asarray(x)
    if len(x) <= max_points:
        return (x, *(np.asarray(s) for s in series))
    idx = np.unique(np.linspace(0, len(x) - 1, max_points).round().astype(int))
    return (x[idx], *(np.asarray(s)[idx] for s in series))
