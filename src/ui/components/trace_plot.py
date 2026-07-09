"""Single-lap telemetry graph: stacked, distance-linked channel plots for one LapTrace.

Draws speed, throttle/brake, gear, steering and ERS as stacked plots sharing one distance x-axis
(traces are distance-indexed - see the models). Charting uses pyqtgraph, which is imported lazily:
if it isn't installed the widget shows an install hint instead of failing, so the app and the test
suite stay importable. Point-count is capped via ``analysis.traces.downsample``.

Overlay (N laps) is iteration 2 and lives elsewhere; this is the single-lap 1b view.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ...analysis import traces as trace_prep
from ...domain.models import LapTrace

_MAX_POINTS = 2000  # per channel - a responsive chart without visible loss on a lap trace
_MISSING = "Telemetry graphs need pyqtgraph — install it with:\n\n    pip install pyqtgraph"


# One stacked plot per row: (channel attr to draw together, left-axis title, unit).
# Steering is the raw UDP value: -1.0 (full lock left) .. 1.0 (full lock right) - normalized, not
# an angle (see protocol/v2025/structs.py CarTelemetryData), so it carries no unit.
_ROWS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("speed",), "Speed", "km/h"),
    (("throttle", "brake"), "Throttle / Brake", ""),
    (("gear",), "Gear", ""),
    (("steer",), "Steering", ""),
    (("ers_store_energy",), "ERS Store Energy", "J"),
)
_PENS = {
    "speed": "#e10600", "throttle": "#3fb950", "brake": "#f85149",
    "gear": "#58a6ff", "steer": "#d29922", "ers_store_energy": "#a371f7",
}
# Colour-blind-safe override fo the throttle/brake pair (Okabe-Ito): the default green/red is
# the classic red-green-confusion pair, so blue/orange reads clearly for all CVD types.
CB_PENS = {"throttle": "#0072b2", "brake": "#e69f00"}   # blue / orange

# Stable per-channel y-range, keyed on the row's first channel. A ``None`` bound means "fit the
# lap's data on that side"; a number pins it (and panning can't cross it). Gear sets its own range
# in _style_gear_axis. This stops each channel's scale from jumping around lap to lap.
_Y_RANGES: dict[str, tuple[float | None, float | None]] = {
    "speed": (0.0, None),            # km/h - never below 0 (negative speed is irrelevant)
    "throttle": (0.0, 1.0),          # throttle & brake are 0..1 fractions
    "steer": (-1.0, 1.0),            # full lock left .. right, normalized
    "ers_store_energy": (0.0, None),  # joules - never below 0
}

_ROW_HEIGHT = 240   # px per stacked channel plot - tall enough to read without zooming; the
                    # detail page scrolls through the stack (total = rows * this + a little pad)
_AXIS_PAD = 28      # extra height so the bottom row's distance axis + label aren't clipped
_LEFT_AXIS_WIDTH = 76  # wide enough for the ERS store energy ticks; shared so titles line up


class TracePlot(QWidget):
    """Stacked single-lap telemetry plots; a graceful placeholder when pyqtgraph is absent."""

    def __init__(self, trace: LapTrace | None = None, parent=None, *,
                 colorblind: bool = False) -> None:
        super().__init__(parent)
        self._colorblind = colorblind
        self._trace: LapTrace | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        try:
            import pyqtgraph as pg
        except ImportError:
            self._pg = None
            self._glw = None
            hint = QLabel(_MISSING)
            hint.setStyleSheet("color: palette(mid);")
            layout.addWidget(hint)
            return
        
        self._pg = pg
        pg.setConfigOptions(antialias=True)
        self._glw = glw = pg.GraphicsLayoutWidget()
        layout.addWidget(self._glw)
        if trace is not None:
            self.set_trace(trace)

    def set_trace(self, trace: LapTrace) -> None:
        """Draw (or redraw) the stacked channel plots for one Lap."""
        self._trace = trace
        if self._pg is None or self._glw is None:
            return
        pg = self._pg
        pens = {**_PENS, **(CB_PENS if self._colorblind else {})}
        self._glw.clear()
        x = np.asarray(trace.distance, dtype=float)
        link = None
        total = _AXIS_PAD
        for i, (channels, title, unit) in enumerate(_ROWS):
            plot = self._glw.addPlot(row=i, col=0)
            plot.setMinimumHeight(_ROW_HEIGHT)
            plot.setMouseEnabled(x=False, y=False)  # pan/zoom distance only
            plot.setMenuEnabled(False)  # no right-click context menu
            plot.hideButtons()  # no auto-scale or reset buttons
            total += _ROW_HEIGHT
            plot.showGrid(x=True, y=True, alpha=0.2)
            plot.setLabel("left", title, units=unit or None)
            plot.getAxis("left").setWidth(_LEFT_AXIS_WIDTH)  # align titles, room for wide ticks (ERS)
            plot.setLabel("bottom", "Distance", units="m")  # distance on every row (visible while scrolling)
            if link is None:
                link = plot
            else:
                plot.setXLink(link)                     # pan/zoom distance together
            for name in channels:
                y = np.asarray(getattr(trace, name), dtype=float)
                dx, dy = trace_prep.downsample(x, y, max_points=_MAX_POINTS)
                plot.plot(dx, dy, pen=pg.mkPen(pens.get(name, "#8b949e"), width=2))
            if "gear" in channels:
                self._style_gear_axis(plot, trace.gear)
            else:
                self._apply_yrange(plot, channels, trace)
        # Fix the whole stack's height so every row gets its full height and none are clipped;
        # the detail page's QScrollArea handles scrolling. A plain minimum isn't enough - the
        # GraphicsLayoutWidget's weak sizeHint lets an ancestor allocate it too little and pyqtgraph
        # clips the lower rows rather than shrinking them (this is what hid Steering and ERS).
        self._glw.setFixedHeight(total)
        self.setMinimumHeight(total)
    
    def set_colorblind(self, enabled: bool) -> None:
        """Switch the throttle/brake palette (default green/red vs colour-blind blue/orange)."""
        if enabled == self._colorblind:
            return
        self._colorblind = enabled
        if self._trace is not None:
            self.set_trace(self._trace)  # redraw with the new palette
    
    @staticmethod
    def _apply_yrange(plot, channels, trace) -> None:
        """Pin a channel's y-range per _Y_RANGES so scales are stable and never cross a floor.

        A ``None`` bound fits this lap's data (with a little headroom); a fixed bound is exact and
        also caps panning, so e.g. speed and ERS can never be dragged below 0.
        """
        spec = _Y_RANGES.get(channels[0])
        if spec is None:
            return
        lo, hi = spec
        if lo is None or hi is None:                    # fit the open side(s) to this lap's data
            data = np.concatenate([np.asarray(getattr(trace, c), dtype=float) for c in channels])
            span = (float(data.max()) - float(data.min())) or 1.0
            lo = float(data.min()) - span * 0.05 if lo is None else lo
            hi = float(data.max()) + span * 0.05 if hi is None else hi
        plot.setYRange(lo, hi, padding=0)
        vb = plot.getViewBox()                          # keep panning/zoom inside the sensible range
        vb.setLimits(yMin=spec[0] if spec[0] is not None else None,
                     yMax=spec[1] if spec[1] is not None else None)

    @staticmethod
    def _style_gear_axis(plot, gear) -> None:
        """Whole-number gear ticks (R plus 0-8) with a horizontal grid, so no fractional gears."""
        g = np.asarray(gear, dtype=float)
        lo = int(np.floor(g.min())) if g.size else 0
        hi = int(np.ceil(g.max())) if g.size else 8
        labels = {-1: "R"}
        ticks = [(v, labels.get(v, str(v))) for v in range(lo, hi + 1)]
        plot.getAxis("left").setTicks([ticks, []])      # majors only, one per gear
        plot.setYRange(lo - 0.5, hi + 0.5, padding=0)