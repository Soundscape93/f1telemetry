"""The session detail's stacked pace and tyre-life charts, on one stint-relative x-axis.

Two full-width plots sharing an axis - tyre life above, observed lap time below. Stacked rather than
side by side on a measurement: at the default 900x600 window a half-width plot gives about 8 px per
lap over a 38-lap race against 18 px full-width, and stacking lets wear fall-off and pace fall-off be
read down one vertical line. Charting is pyqtgraph, imported lazily exactly as
``components/trace_plot.py`` does it, so a missing install shows a hint instead of breaking the page.

Every stint rule lives Qt-free in ``tyre_stints``, and which laps represent a run's pace is decided
once in ``lap_context`` - this module only draws them. It is handed a ``SessionAnalysis`` rather
than a list of stints for exactly that reason: the average in a legend entry and the indicator
beside that lap in the Laps box are then the same judgement, not two that happen to agree.

Three drawing choices carry meaning rather than taste:

* **A lap past the range is drawn clipped, but still on the line.** Pit laps are kept out of the
  scale by rule and the rest of the spread is capped, so any lap can end up above it: it is pinned
  to the top border with a triangle marker and the real time in its tooltip. Detached it read as
  though the stint had skipped a lap - worst at the head of a stint, which is precisely where every
  out-lap sits. The range itself is computed in ``tyre_stints.pace_y_range``.
* **Both axes read in the units the rest of the app uses**: tyre life in ten-point steps, lap time
  as ``m:ss`` through a custom axis, so the axis and the tooltips agree instead of the axis printing
  raw seconds.
* **Compound gives the colour, stint order gives the pattern.** Colours are the game's own, read from
  ``components/tyres`` and never re-picked here. The solid/dashed/dotted cycle is the second channel,
  and it is necessary: a race running medium-hard-medium would otherwise draw two identical yellow
  lines. Same idea as ``trace_plot``'s per-lap patterns.
* **The plots keep pyqtgraph's own black ground**, so an OS light/dark switch cannot touch them and
  the white hard-compound line stays readable either way (core invariant #11 is about widget
  stylesheets; nothing here sets one).
"""
from __future__ import annotations

from functools import lru_cache
from math import nan

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..components.tyres import compound_style
from ..formatting import format_lap_time
from ..style import MUTED_TEXT_QSS
from .lap_context import LapContext, SessionAnalysis
from .tyre_stints import (
    StintLap,
    TyreStint,
    pace_y_range,
    stint_average_label,
    stint_axis_max,
    stint_series
)

_MISSING = "The pace and tyre-life charts need pyqtgraph — install it with:\n\n    pip install pyqtgraph"

# The pace plot gets roughly double the tyre-life plot's height. The y-range is bounded rather than
# fitted - pit laps out, then capped - so the extra pixels go straight into resolution: an 8 s window
# over 420 px resolves about 20 ms, enough to read a lap off the axis instead of having to hover it.
# Tyre life needs less, but not as little as it had.
_LIFE_ROW_HEIGHT = 250
_PACE_ROW_HEIGHT = 420
_AXIS_PAD = 28          # so the lower plot's axis + label aren't clipped
_LEGEND_HEIGHT = 34     # the stint legend sits in its own layout row above both plots
_LEFT_AXIS_WIDTH = 88   # shared, and wide enough for a full "1:20.234" tick; keeps the rows aligned

_LIFE_TICK_STEP = 10    # ten-point steps, so a stint's fall-off can be read straight off the axis

# Pattern by stint order, cycled alongside the compound colour. Two stints on the same compound are
# the same colour by design (the colours are the game's), so this is what separates them.
_STINT_STYLES = (Qt.PenStyle.SolidLine, Qt.PenStyle.DashLine, Qt.PenStyle.DotLine,
                 Qt.PenStyle.DashDotLine, Qt.PenStyle.DashDotDotLine)
_UNKNOWN_COMPOUND = ("?", "#8b949e")    # a compound newer than our table still gets a drawn line

_WHEELS = ("RL", "RR", "FL", "FR")      # UDP wheel order throughout (domain/models)
_CURSOR = "#40f0f0"                     # the shared hover line, same as the lap-trace plots
_LIFE_TITLE = "Tyre life — worst wheel"
_PACE_TITLE = "Observed lap time by stint"


class StintCharts(QWidget):
    """Tyre life over observed lap time, per stint, on a shared stint-relative axis."""

    def __init__(self, analysis: SessionAnalysis | None = None, *, parent=None) -> None:
        super().__init__(parent)
        self._analysis = SessionAnalysis()
        self._stints: tuple[TyreStint, ...] = ()
        self._excluded: frozenset[int] = frozenset()
        self._vlines: list = []
        self._proxy = None      # kept alive so the mouse SignalProxy isn't garbage collected
        self._link = None       # the shared-x plot the cursor position is read from
        self._axis_max = 1
        self._pace_bounds: tuple[float, float] | None = None        # where a lap outside the window clips to

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
        self._glw = pg.GraphicsLayoutWidget()
        layout.addWidget(self._glw)
        if analysis is not None and analysis.stints:
            self.set_analysis(analysis)

    def set_analysis(self, analysis: SessionAnalysis) -> None:
        """Draw a session's runs; an analysis with no stints clears the charts.

        The whole analysis rather than its stints alone: the tooltips name what a lap was and the
        legend's average leaves the same laps out, and both read it from here (``lap_context``).
        Whether the session began on the grid is already settled inside it.
        """
        self._analysis = analysis
        self._stints = tuple(analysis.stints)
        if self._pg is None or self._glw is None:
            return
        self._glw.clear()
        self._vlines = []
        self._proxy = self._link = None
        self._excluded = analysis.excluded_laps
        if not self._stints:
            return

        self._axis_max = stint_axis_max(self._stints)
        legend = self._add_legend()
        life = self._add_plot(row=1, title=_LIFE_TITLE, axis="Tyre life", unit="%",
                              height=_LIFE_ROW_HEIGHT)
        pace = self._add_plot(row=2, title=_PACE_TITLE, axis="Lap time", height=_PACE_ROW_HEIGHT,
                              left=_lap_time_axis_class(self._pg)(orientation="left"))
        pace.setXLink(life)     # one axis: stint lap n is the same lap in both rows, always

        # No synthetic 100% anchor - the first stored sample of a stint already reads a few percent
        # worn and there is no 100% measurement to draw. The full 0-100 scale says "near new" on its
        # own, without inventing a point (DECISIONS -> UI).
        life.setYRange(0.0, 100.0, padding=0)
        life.getAxis("left").setTicks([_life_ticks(), []])
        self._apply_pace_range(pace)

        self._draw_life(life, legend)
        self._draw_pace(pace)
        for plot in (life, pace):
            self._add_cursor_line(plot)

        total = _AXIS_PAD + _LEGEND_HEIGHT + _LIFE_ROW_HEIGHT + _PACE_ROW_HEIGHT
        self._glw.setFixedHeight(total)     # same reason as trace_plot: a weak sizeHint gets clipped
        self.setMaximumHeight(total)
        self._install_cursor(life)

    # --- scaffolding ---------------------------------------------------------------------------
    def _add_legend(self):
        """One horizontal legend above both plots, naming each stint's compound and lap range."""
        pg = self._pg
        legend = pg.LegendItem(colCount=max(1, len(self._stints)), offset=None,
                               brush=pg.mkBrush(20, 20, 20, 200), pen=pg.mkPen(90, 90, 90),
                               labelTextColor="#f0f0f0")
        self._glw.addItem(legend, row=0, col=0)
        return legend

    def _add_plot(self, row: int, title: str, axis: str, height: int,
                  unit: str | None = None, left=None):
        """One row of the stack, styled and axis-labelled like the lap-trace plots.

        ``left`` swaps in a custom axis. Note that a plot using one must *not* also declare a unit:
        ``setLabel(units=...)`` turns on pyqtgraph's SI-prefix scaling, which would fight a tick
        formatter that is already producing its own text.
        """
        kwargs = {"axisItems": {"left": left}} if left is not None else {}
        plot = self._glw.addPlot(row=row, col=0, **kwargs)
        plot.setTitle(title)
        plot.setMinimumHeight(height)
        plot.setMouseEnabled(x=False, y=False)  # the scale is fixed by the data, not by the mouse
        plot.setMenuEnabled(False)
        plot.hideButtons()
        plot.showGrid(x=True, y=True, alpha=0.2)
        plot.setLabel("left", axis, units=unit)
        plot.getAxis("left").setWidth(_LEFT_AXIS_WIDTH)
        plot.setLabel("bottom", "Stint lap")
        plot.getAxis("bottom").setTicks([_axis_ticks(self._axis_max), []])
        plot.setXRange(0.5, self._axis_max + 0.5, padding=0)
        return plot

    def _apply_pace_range(self, plot) -> None:
        """Fix the pace axis to its window: out-laps can't flatten it, and near-identical laps can't
        be magnified into a fall-off that never happened."""
        self._pace_bounds = None        # cleared first: a redraw must never clip to the old window
        span = pace_y_range(self._stints)
        if span is None:
            return                      # nothing timed to scale to; the plot fits what it has
        low, high = span[0] / 1000.0, span[1] / 1000.0
        self._pace_bounds = (low, high)
        plot.setYRange(low, high, padding=0)
        
    # --- the two rows --------------------------------------------------------------------------
    def _draw_life(self, plot, legend) -> None:
        """Tyre life per stint: ``100 - max(wear)``, with the four wheels in each point's tooltip.

        Every stored lap here is a real wear reading, out-laps included, so the whole stint is one
        line - unlike the pace chart, where the out-lap has to come off the line.
        """
        for stint in self._stints:
            colour, style = _stint_style(stint)
            xs, ys = stint_series(stint, lambda lap: lap.tyre_life)
            curve = plot.plot(xs, ys, pen=self._pg.mkPen(colour, width=2, style=style),
                              connect="finite")     # a missing lap breaks the line, never bridges it
            legend.addItem(curve, _legend_label(stint, self._stint_average(stint)))
            self._scatter(plot, colour, "o",
                          [(lap.stint_lap, lap.tyre_life) for lap in stint.laps],
                          [_life_tip(lap) for lap in stint.laps])

    def _draw_pace(self, plot) -> None:
        """Observed lap time per stint, with anything past the range clipped to its nearer edge."""
        for stint in self._stints:
            colour, style = _stint_style(stint)
            xs, ys = stint_series(stint, self._pace_value)
            plot.plot(xs, ys, pen=self._pg.mkPen(colour, width=2, style=style),
                      connect="finite")        # a missing lap breaks the line, never bridges it

            # Round markers inside the window; outside it a triangle pointing the way the real value
            # lies, so a point resting on a border can never be read as a lap that ran that time.
            # Both edges are reachable: the top is out-laps and incidents, the bottom a run's
            # opening flying lap in practice or qualifying.
            groups: dict[str, list] = {"o": [], "t1": [], "t": []}
            for lap in stint.laps:
                if lap.lap_time_ms:
                    groups[_pace_symbol(self._clip_side(lap))].append(lap)
            for symbol, group in groups.items():
                self._scatter(plot, colour, symbol,
                              [(lap.stint_lap, self._pace_value(lap)) for lap in group],
                              [_pace_tip(lap, self._analysis.for_lap(lap.lap_number),
                                         self._clip_side(lap)) for lap in group])

    def _stint_average(self, stint: TyreStint) -> str:
        """This stint's corrected average pace, ready for its legend entry."""
        return stint_average_label(stint, self._excluded)

    def _clip_side(self, lap: StintLap) -> str:
        """-1 when the lap is drawn on the bottom edge, +1 on the top edge, 0 when it fits."""
        seconds = _pace_seconds(lap)
        if self._pace_bounds is None or seconds != seconds:
            return 0
        low, high = self._pace_bounds
        return -1 if seconds < low else 1 if seconds > high else 0

    def _pace_value(self, lap: StintLap) -> float:
        """A lap's y position in seconds, pinned to the window's edge when it falls outside.

        Clipped laps stay *on* the line rather than floating free of it. Detached they read as
        though the run had skipped a lap - worst at the head of a run, which is where every out-lap
        sits. Joined, the line runs into the border and stops, the ordinary way of drawing a value
        that leaves the scale; the triangle marks it and the tooltip carries the real time.

        Clamped at both ends. The floor is normally the quickest lap so nothing should sit below it,
        but a stale bound or an odd reading must not put a point off the plot: drawing nothing at all
        is how the Suzuka P1 chart silently lost its best lap.
        """
        seconds = _pace_seconds(lap)
        if self._pace_bounds is None or seconds != seconds:
            return seconds
        low, high = self._pace_bounds
        return min(max(seconds, low), high)
        
    def _scatter(self, plot, colour: str, symbol: str, points, tips) -> None:
        """Hoverable per-lap markers - the tooltip is where the real lap number and the wear live."""
        drawable = [(x, y) for x, y in points if y == y]        # drop nan; a hole has no marker
        if not drawable:
            return
        pg = self._pg
        plot.addItem(pg.ScatterPlotItem(
            x=[float(x) for x, _ in drawable], y=[float(y) for _, y in drawable],
            symbol=symbol, size=7, brush=pg.mkBrush(colour), pen=pg.mkPen(colour),
            data=[tip for tip, (_, y) in zip(tips, points) if y == y],
            hoverable=True, hoverSize=11, tip=lambda x, y, data: data))

    # --- the shared cursor ---------------------------------------------------------------------
    def _add_cursor_line(self, plot) -> None:
        vline = plot.addLine(x=0, pen=self._pg.mkPen(color=_CURSOR, width=1))
        vline.hide()            # moved on hover, not shown until then
        self._vlines.append(vline)

    def _install_cursor(self, link) -> None:
        """One vertical line moved across both plots together, so a stint lap reads down the stack."""
        self._link = link
        self._proxy = self._pg.SignalProxy(
            self._glw.scene().sigMouseMoved, rateLimit=60, slot=self._on_mouse_move)

    def _on_mouse_move(self, event) -> None:
        if self._link is None:
            return
        pos = event[0]      # SignalProxy wraps the original signal in a tuple
        x = float(self._link.getViewBox().mapSceneToView(pos).x())
        # Snap to whole stint laps and clamp to the axis: this is a discrete axis, so "hovering
        # stint lap n" has to mean the same lap in both rows rather than a point between two.
        x = float(min(max(round(x), 1), self._axis_max))
        for vline in self._vlines:
            vline.setPos(x)
            vline.show()


# --- per-stint presentation ----------------------------------------------------------------------
def _stint_style(stint: TyreStint) -> tuple[str, Qt.PenStyle]:
    """Colour from the compound (the game's own), pattern from the stint's order."""
    _, colour = compound_style(stint.visual_compound) or _UNKNOWN_COMPOUND
    return colour, _STINT_STYLES[(stint.index - 1) % len(_STINT_STYLES)]


def _legend_label(stint: TyreStint, average: str) -> str:
    """``Stint 3 · M · laps 22-29 · avg 1:22.926``.

    The lap range disambiguates a repeated compound; the average is what the run was actually
    worth. It is the stint's *representative* pace, not the mean of the laps drawn: the laps into
    and out of the pits, a race's standing start, and any lap run behind a safety car or caught by a
    red flag are left out of it (``lap_context`` decides, ``stint_average_ms`` applies), so two runs
    compare directly even when one of them opens with a 37-second out-lap. Every excluded lap is
    marked in the Laps box, so the number can always be accounted for from the page.
    """
    letter, _ = compound_style(stint.visual_compound) or _UNKNOWN_COMPOUND
    return (f"Stint {stint.index} · {letter} · "
            f"laps {stint.first_lap_number}\u2013{stint.last_lap_number} · avg {average}")


def _axis_ticks(axis_max: int) -> list[tuple[float, str]]:
    """Whole-number stint-lap ticks, thinned so a long stint's axis doesn't crowd. Never fractional."""
    stride = 1 if axis_max <= 15 else 2 if axis_max <= 30 else 5
    return [(float(n), str(n)) for n in range(1, axis_max + 1) if n == 1 or n % stride == 0]


def _pace_symbol(clip_side: int) -> str:
    """Round inside the window, outside it a triangle pointing the way the real value lies."""
    return "o" if clip_side == 0 else ("t1" if clip_side > 0 else "t")


@lru_cache(maxsize=1)
def _lap_time_axis_class(pg):
    """A left-axis type whose ticks read as lap times, so the axis uses the tooltips' own unit.

    Built lazily and cached because it subclasses a pyqtgraph type, and pyqtgraph is imported only
    when the widget is actually constructed - this module has to stay importable without it.
    """

    class LapTimeAxis(pg.AxisItem):
        def tickStrings(self, values, scale, spacing):
            # Follow pyqtgraph's own tick spacing: whole seconds where the ticks are a second or
            # more apart, tenths or milliseconds where they are closer, so a tight range keeps its
            # resolution instead of printing a column of identical strings.
            decimals = 0 if spacing >= 1.0 else 1 if spacing >= 0.1 else 3
            return [_lap_tick(value, decimals) for value in values]

    return LapTimeAxis


def _lap_tick(seconds: float, decimals: int) -> str:
    """``82.737`` -> ``1:23`` / ``1:22.7`` / ``1:22.737`` - the laps table's unit, at axis precision.

    Rounds before splitting off the minutes, so a tick just under the minute can't print ``1:60``.
    """
    total = round(max(float(seconds), 0.0), decimals)
    minutes, rest = divmod(total, 60.0)
    width = 2 + (decimals + 1 if decimals else 0)
    return f"{int(minutes)}:{rest:0{width}.{decimals}f}"


def _life_ticks() -> list[tuple[float, str]]:
    """0-100% in ten-point steps, so wear can be read off the axis without hovering a point."""
    return [(float(value), str(value)) for value in range(0, 101, _LIFE_TICK_STEP)]


def _pace_seconds(lap: StintLap) -> float:
    """A lap's time in seconds, or nan for a lap the game never timed - so the line breaks there."""
    return lap.lap_time_ms / 1000.0 if lap.lap_time_ms else nan


def _life_tip(lap: StintLap) -> str:
    wheels = "  ".join(f"{name} {value:.1f}%" for name, value in zip(_WHEELS, lap.wear))
    return (f"Lap {lap.lap_number} · stint lap {lap.stint_lap}\n"
            f"Tyre life {lap.tyre_life:.1f}% (worst wheel)\n"
            f"Wear  {wheels}")


def _pace_tip(lap: StintLap, context: LapContext, clip_side: int) -> str:
    """What one lap says on hover: its real number, its real time, and why it sits where it does.
    
    The reasons come from the shared classification, so a lap the Laps box marks ``IN`` and the
    legend's average skips explains itself the same way here.
    """
    lines = [f"Lap {lap.lap_number} · stint lap {lap.stint_lap}", format_lap_time(lap.lap_time_ms)]
    lines.extend(context.reasons)
    if clip_side > 0:
        # Say it outright: a marker resting on a border must never read as a real measurement.
        lines.append("Drawn clipped at the top: the time above is the real one")
    elif clip_side < 0:
        lines.append("Drawn clipped at the bottom: the time above is the real one")
    return "\n".join(lines)
