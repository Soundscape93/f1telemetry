"""Single-lap telemetry graph: stacked, distance-linked channel plots for one LapTrace.

Draws speed, throttle/brake, gear, steering and ERS as stacked plots sharing one distance x-axis
(traces are distance-indexed - see the models). Charting uses pyqtgraph, which is imported lazily:
if it isn't installed the widget shows an install hint instead of failing, so the app and the test
suite stay importable. Point-count is capped via ``analysis.traces.downsample``.

Overlay (N laps) is handled via ``set_traces``.
"""
from __future__ import annotations

from  collections.abc import Sequence

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ...analysis import traces as trace_prep
from ...domain.models import LapTrace
from ..style import MUTED_TEXT_QSS

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
    "g_lat": "#58a6ff", "g_long": "#f778ba",
}
# optional g-force row, appended after ERS when the lap carries Motion. Lateral
# longitudinal share on row like throttle/brake: solid = lateral, dashed = longitudinal.
_GFORCE_ROW: tuple[tuple[str, ...], str, str] = (("g_lat", "g_long"), "G-Force", "g")
_GFORCE_LABELS = {"g_lat": "Lateral", "g_long": "Longitudinal"}  # single-lap g-force legend entries

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
# Overlay (comparison) mode colours bay *lap*, not by channel, so up to this many laps stay legible
# in the legen; the referen lap (the one being viewed) is index 0. A synthetic bottom row shows
# each other lap's cumulative time delta (the racing gap) to that reference.
_LAP_PENS = ("#e10600", "#58a6ff", "#3fb950", "#d29922", "#a371f7",
             "#f778ba", "#79c0ff", "#ffa657")
# Colour-blind-safe lap palette (Okabe-Ito, minus black - invisible on the dark plots). These stay
# distinct under red-green (and other) colour-vision deficiencies; paired with _LAP_STYLES so laps
# also differ by line pattern, not colour alone.
_CB_LAP_PENS = ("#e69f00", "#56b4e9", "#009e73", "#f0e442", "#0072b2",
                "#d55e00", "#cc79a7", "#ffffff")
# Per-lap line pattern, cycled alongside the colour so overlaid laps differ two ways at once. The
# reference lap (index 0) is solid. Used on single-channel rows + the Δ row; the throttle/brake row
# keeps solid=throttle / dashed=brake for its channel distinction.
_LAP_STYLES = (Qt.PenStyle.SolidLine, Qt.PenStyle.DashLine, Qt.PenStyle.DotLine,
               Qt.PenStyle.DashDotLine, Qt.PenStyle.DashDotDotLine)
_MAX_OVERLAY = len(_LAP_PENS)
_LEGEND_HEIGHT = 34     # the overlay's lap-name legend sits in its own row above the plots
_DELTA_ROW: tuple[tuple[str, ...], str, str] = (("_delta",), "Δ vs ref", "s")



class TracePlot(QWidget):
    """Stacked single-lap telemetry plots; a graceful placeholder when pyqtgraph is absent.
    
    Emits the distance (m) under the mouse as it moves over any plot, so a linked view
    can move its marker. -1.0 when the curser leaves the plot area.
    """
    cursor_moved = Signal(float)      # distance under the mouse, or -1.0 when outside the plot area

    def __init__(self, trace: LapTrace | None = None, parent=None, *,
                 colorblind: bool = False) -> None:
        super().__init__(parent)
        self._colorblind = colorblind
        self._trace: list[LapTrace] = []        # current lap(s): 1 = single view, >1 = overlay
        self._labels: list[str | None] = []
        self._link = None                       # the shared-x plot (source of cursor distance)
        self._proxy = None                      # kept alive so the mouse SignalProxy isn't GC'd
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        try:
            import pyqtgraph as pg
        except ImportError:
            self._pg = None
            self._glw = None
            hint = QLabel(_MISSING)
            hint.setStyleSheet(MUTED_TEXT_QSS)
            layout.addWidget(hint)
            return
        
        self._pg = pg
        pg.setConfigOptions(antialias=True)
        self._glw = glw = pg.GraphicsLayoutWidget()
        layout.addWidget(self._glw)
        if trace is not None:
            self.set_trace(trace)
    
    def set_trace(self, trace: LapTrace) -> None:
        """Draw one lap (single-lap view). Convenience for ``set_traces`` with one lap."""
        self.set_traces([trace])

    def set_traces(self, traces: Sequence[LapTrace], labels: Sequence[str] | None = None) -> None:
        """Draw one lap, or overlay several for comparison.
        
        One trace keeps the original single-lap look: each channel in its own colour, no legend and
        no delta row. Two or more are aligned on a shared distance grid (``analysis.traces.align``),
        colour *per lap* with a legend, and gain a bottom Δ-time row - each lap's racing gap to the
        reference (``traces[0]``, with the lap being viewed). Laps past the palette are dropped.
        """
        traces = list(traces)
        self._trace = traces
        self._labels = list(labels) if labels is not None else [None] * len(traces)
        if self._pg is None or self._glw is None or not traces:
            return
        self._glw.clear()
        if len(traces) == 1:
            self._draw_single(traces[0])
        else:
            self._draw_overlay(traces, self._labels)
    
    def set_colorblind(self, enabled: bool) -> None:
        """Switch to/from the colour-blind palette and redraw the current lap(s) in place.

        Affects both views: the single-lap throttle/brake pair and the overlay's per-lap colours.
        """
        if enabled == self._colorblind:
            return
        self._colorblind = enabled
        if self._trace:
            self.set_traces(self._trace, self._labels)
    
    def _draw_single(self, trace: LapTrace) -> None:
        """The single-lap render: one stacked plot per channel group, each in its own colour."""
        pg = self._pg
        pens ={**_PENS, **(CB_PENS if self._colorblind else {})}
        x = np.asanyarray(trace.distance, dtype=float)
        link = None
        rows = _ROWS + ((_GFORCE_ROW,) if trace.g_lat is not None else ())
        total = _AXIS_PAD
        for i, (channels, title, unit) in enumerate(rows):
            plot = self._glw.addPlot(row=i, col=0)
            plot.setMinimumHeight(_ROW_HEIGHT)
            plot.setMouseEnabled(x=False, y=False)      # pan/zoom distance only
            plot.setMenuEnabled(False)                  # no right click context menu
            plot.hideButtons()                          # no auto-scale or reset buttons
            total += _ROW_HEIGHT
            plot.showGrid(x=True, y=True, alpha=0.2)
            plot.setLabel("left", title, units=unit or None)
            plot.getAxis("left").setWidth(_LEFT_AXIS_WIDTH)      # align titles, room for wide ticks (ERS)
            plot.setLabel("bottom", "Distance", units="m")      # distance on every row (visible while scrolling)
            if link is None:
                link = plot
            else:
                plot.setXLink(link)         # pan/zoom distance together
            # The g-force row carries two channels told apart by colour; in single-lap mode add a
            # small in-plot legend so the colours are labelled (lateral vs longitudinal). Overlay
            # mode skips it - the per-lap legend up top would balloon with N laps x 2 channels.
            legend = None
            if channels == _GFORCE_ROW[0]:
                legend = plot.addLegend(offset=(-10, 10), brush=pg.mkBrush(20, 20, 20, 200),
                                        pen=pg.mkPen(90, 90, 90), labelTextColor="#f0f0f0")
            for name in channels:
                y = np.asanyarray(getattr(trace, name), dtype=float)
                dx, dy = trace_prep.downsample(x, y, max_points=_MAX_POINTS)
                curve = plot.plot(dx, dy, pen=pg.mkPen(pens.get(name, "#8b949e"), width=2))
                if legend is not None:
                    legend.addItem(curve, _GFORCE_LABELS.get(name, name))
            if "gear" in channels:
                self._style_gear_axis(plot, trace.gear)
            else:
                self._apply_yrange(plot, channels, trace)
        # Fix the whole stack's height so every row gets its full height and none are clipped;
        # the detail page's QScrollArea handles scrolling. A plain minimum isn't enough - the
        # GraphicsLayoutWidget weak sizeHint lets an ancestor allocate it too littel and pyqtgraph
        # clips the lower rows rather han shrinking them.
        self._glw.setFixedHeight(total)
        self.setMaximumHeight(total)
        self._install_cursor(link)
    
    def _draw_overlay(self, traces: list[LapTrace], labels: list[str | None]) -> None:
        """Overlay several laps: align on a shared grid, colour per lap, add a Δ-time row."""
        pg = self._pg
        lap_pens = _CB_LAP_PENS if self._colorblind else _LAP_PENS
        n = min(len(traces), _MAX_OVERLAY)
        traces, labels = traces[:n], labels[:n]
        g_ok = any(t.g_lat is not None for t in traces)
        chans = LapTrace.CHANNELS + (("g_lat", "g_long") if g_ok else ())
        try:
            aligned = trace_prep.align(traces, labels=labels, channels=chans)
        except ValueError:
            # No shared distance overlap (e.g. badly trimmed) - say so instead of crashing.
            self._glw.addLabel("These laps don't share a common distance range to overlay",
                               row=0, col=0)
            self._glw.setFixedHeight(_ROW_HEIGHT)
            self.setMaximumHeight(_ROW_HEIGHT)
            return
        x = aligned[0].distance
        deltas = trace_prep.time_deltas(aligned[0], aligned[1:])    # one gap trace per non-ref lap
        rows = _ROWS + ((_GFORCE_ROW,) if g_ok else ()) + (_DELTA_ROW,)

        # A horizontal legend in its own layout row above the plots, so the lap names never sit on
        # top of the traces. pyqtgraph's LegendItem has no `horizontal` flag - it lays entries out in
        # a grid, so `colCount=n` puts all n lap names in one row. (The default colCount=1 stacks them
        # vertically; that column grew with the lap count and, against the fixed-height plot stack,
        # clipped the bottom Δ row once 3+ laps were overlaid.) Plots start at row 1; each lap's speed
        # curve is registered onto the legend below.`
        legend = pg.LegendItem(colCount=n, offset=None, brush=pg.mkBrush(20, 20, 20, 200),
                               pen=pg.mkPen(90, 90, 90), labelTextColor="#f0f0f0")
        self._glw.addItem(legend, row=0, col=0)

        link = None
        total = _AXIS_PAD + _LEGEND_HEIGHT
        for i, (channels, title, unit) in enumerate(rows):
            plot = self._glw.addPlot(row=i + 1, col=0)      # row 0 is the legend
            plot.setMinimumHeight(_ROW_HEIGHT)
            plot.setMouseEnabled(x=False, y=False)      # pan/zoom distance only
            plot.setMenuEnabled(False)                  # no right click context menu
            plot.hideButtons()                          # no auto-scale or reset buttons
            total += _ROW_HEIGHT
            plot.showGrid(x=True, y=True, alpha=0.2)
            plot.setLabel("left", title, units=unit or None)
            plot.getAxis("left").setWidth(_LEFT_AXIS_WIDTH)      # align titles, room for wide ticks (ERS)
            plot.setLabel("bottom", "Distance", units="m")      # distance on every row (visible while scrolling)
            if link is None:
                link = plot
            else:
                plot.setXLink(link)         # pan/zoom distance together
            if channels[0] == "_delta":
                self._draw_delta_row(plot, x, deltas, lap_pens)
                continue
            multi = len(channels) > 1       # throttle/brake or g-force row: one plot per channel, but share the y-axis
            for li, at in enumerate(aligned):
                color = lap_pens[li % len(lap_pens)]
                lap_style = _LAP_STYLES[li % len(_LAP_STYLES)] # per-lap pattern; index 0 = solid ref
                for ci, name in enumerate(channels):
                    y = at.channel(name)
                    dx, dy = trace_prep.downsample(x, y, max_points=_MAX_POINTS)
                    # single-channel rows; pattern *by lap* alongside he colour, so laps differ two
                    # wasy at once (reabable in color-blind mode). Mulit-channel rows instead keep
                    # solid/dashed to separate the channels (throttle vs brake), where colour already
                    # tells the laps apart
                    style = (Qt.PenStyle.DashLine if ci else Qt.PenStyle.SolidLine)
                    curve = plot.plot(dx, dy, pen=pg.mkPen(color=color, width=2, style=style))
                    if i == 0 and ci == 0:              # one legend entry per lap, from the speed row
                        legend.addItem(curve, at.label or f"Lap {li + 1}")
            if "gear" in channels:
                self._style_gear_axis(
                    plot, np.concatenate([at.channel("gear") for at in aligned]))
            else:
                self._apply_yrange_arrays(
                    plot, channels, [at.channel(c) for at in aligned for c in channels])
        self._glw.setFixedHeight(total)
        self.setMaximumHeight(total)
        self._install_cursor(link)

    def _draw_delta_row(self, plot, x, deltas, lap_pens) -> None:
        """Δ-time row: one non-reference lap's cumulative gap to the reference (0-line = ref).
        
        Each gap trace carries the same per-lap colour *and* pattern as the channel rows, so a lap
        is identified the same way in every row (and stays legible under colour-vision deficiency).
        """
        pg = self._pg
        # The reference lap sits on y=0; draw it in the reference colour + its own pattern (index 0).
        plot.addLine(y=0, pen=pg.mkPen(lap_pens[0], width=1, style=_LAP_STYLES[0]))
        for li, d in enumerate(deltas, start=1):
            color = lap_pens[li % len(lap_pens)]
            dx, dy = trace_prep.downsample(x, d, max_points=_MAX_POINTS)
            style = _LAP_STYLES[li % len(_LAP_STYLES)]
            plot.plot(dx, dy, pen=pg.mkPen(color=color, width=2, style=style))
        plot.getViewBox().enableAutoRange(axis="y")     # gaps are small + signed - just fit them

    def _install_cursor(self, link) -> None:
        """Track the mouse over the linked-x plots and emit its distance for a linked view."""
        self._link = link
        if link is None:
            self._proxy = None
            return
        pg = self._pg
        self._proxy = pg.SignalProxy(
            self._glw.scene().sigMouseMoved, rateLimit=60, slot=self._on_mouse_move)
        
    def _on_mouse_move(self, event) -> None:
        pos = event[0]  # SignalProxy wraps the original signal in a tuple
        if self._link is None:
            return
        vb = self._link.getViewBox()
        self.cursor_moved.emit(float(vb.mapSceneToView(pos).x()))
    
    @staticmethod
    def _apply_yrange(plot, channels, trace) -> None:
        """Pin a single lap's y-range per _Y_Ranges (stable scales; fixed bounds also cap panning)."""
        TracePlot._apply_yrange_arrays(plot, channels, [getattr(trace, c) for c in channels])
    
    @staticmethod
    def _apply_yrange_arrays(plot, channels, arrays) -> None:
        """Pin the row's y-range per _Y_RANGES, fitting any open side across the given data arrays.
        
        A ``None`` bound fits the data (with headroom) across *every* array passed - for an overlay
        that's every lap, so one scale holds them all; a fixed bound is exact and also caps panning
        (e.g. speend and ERS can never be dragged below 0).
        """
        spec = _Y_RANGES.get(channels[0])
        if spec is None:
            return
        lo, hi = spec
        if lo is None or hi is None:            # fit the open side(s) to the data
            data = np.concatenate([np.asanyarray(a, dtype=float) for a in arrays])
            span = (float(data.max()) - float(data.min())) or 1.0
            lo = float(data.min()) - span * 0.05 if lo is None else lo
            hi = float(data.max()) + span * 0.05 if hi is None else hi
        plot.setYRange(lo, hi, padding=0)       # no extra headroom
        vb = plot.getViewBox()                  # keep panning/zooming inside the sensible range
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