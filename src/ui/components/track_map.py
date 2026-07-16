"""The lap-detail track map: an equal-aspect XY path plotted from world coordinates.

The path is telemetry, not a track-image asset, so it works for every circuit including
league/custom tracks and lives in the same coordinate space as the hover marker. It draws the
canonical median line for the track when available (``set_layout``; see analysis.track_layout),
falling back to the selected lap's own line (``set_trace``). A distance from the linked TracePlot
moves the marker to the nearest sample. pyqtgraph is imported lazily, matching TracePlot: absent,
the widget shows an install hint instead of failing import.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ...analysis.track_layout import TrackLayout
from ...domain.models import LapTrace
from ..style import MUTED_TEXT_QSS

_MISSING = "The track map needs pyqtgraph - install it with: \n\n   pip install pyqtgraph"
_SIZE = 320 # px; the map is square (equal aspect)


class TrackMap(QWidget):
    """Equal-aspect plot of one lap's path, with a marker driven by a cursor distance."""

    def __init__(self, trace: LapTrace | None = None, parent=None) -> None:
        super().__init__(parent)
        self._distance = None
        self._x = None
        self._z = None
        self._marker = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        try:
            import pyqtgraph as pg
        except ImportError:
            self._pg = None
            self._plot = None
            hint = QLabel(_MISSING)
            hint.setStyleSheet(MUTED_TEXT_QSS)
            layout.addWidget(hint)
            return
        
        self._pg = pg
        self._widget = pg.PlotWidget()
        self._widget.setFixedSize(_SIZE, _SIZE)
        self._widget.setMenuEnabled(False)
        self._widget.setMouseEnabled(x=False, y=False)
        self._widget.hideButtons()
        self._widget.hideAxis('left')
        self._widget.hideAxis('bottom')
        self._plot = self._widget.getPlotItem()
        self._plot.setAspectLocked(True)        # equal aspect: the track keeps its true shape
        layout.addWidget(self._widget)
        if trace is not None:
            self.set_trace(trace)
    

    def set_layout(self, layout: TrackLayout) -> None:
        """Draw the canonical median line for the track (preferred over the driven lap).

        The layout is a distance-resampled median over the race weekend's laps (see
        ``analysis.track_layout``), so the circuit keeps the same clean shape regardless of which
        lap is being viewed. The hover marker still indexes ``layout.distance``.
        """
        if self._plot is None:
            return
        self._render(layout.distance, layout.pos_x, layout.pos_z)

    def set_trace(self, trace: LapTrace) -> None:
        """Draw this lap's own path - the fallback when no canonical layout is available.
        
        Used when a weekend has too few Motion Laps to build a stable median (see 
        ``TrackLayoutProvider``); the shape then follows the driven line for this one lap.
        """
        if self._plot is None or not trace.has_motion:
            return
        self._render(trace.distance, trace.pos_x, trace.pos_z)

    def _render(self, distance, pos_x, pos_z) -> None:
        """Draw an outline from parallel distance/pos_x/pos_z arrays and reset the marker.

        Shared by ``set_layout`` (the canonical median line) and ``set_trace`` (the single-lap
        fallback): both feed raw world coords and get the same two corrections. F1's world frame is
        left-handed (X right, Y up, Z forward), so plotting X vs Z top-down mirrors the circuit -
        the lap appears to run the wrong way round (clockwise vs anti-clockwise); negating one axis
        (here Z) restores the true handedness (a pure rotation can't - only a reflection flips the
        running direction). The absolute rotation still follows the game's world frame, not the
        broadcast map art - matching that would need a per-track constant, which this asset-free view
        avoids by design (see DECISIONS -> track map). The path is then closed (last sample joined
        back to the first) so a shape that doesn't span the whole start/finish straight - e.g. a
        driven-lap fallback on a race lap 1 that begins at the grid slot, past the S/F line - still
        draws a complete outline; the closing segment falls along the straight (~zero length for a
        full loop).
        """
        pg = self._pg
        self._plot.clear()
        self._distance = np.asarray(distance, dtype=float)
        self._x = np.asarray(pos_x, dtype=float)
        self._z = -np.asarray(pos_z, dtype=float)  # negate one axis -> correct handedness
        path_x = np.append(self._x, self._x[0])  # close the loop (fills a lap-1 S/F gap)
        path_z = np.append(self._z, self._z[0])
        self._plot.plot(path_x, path_z, pen=pg.mkPen(color='#8b949e', width=6))
        self._marker = pg.ScatterPlotItem(
            size=12, brush=pg.mkBrush('#e10600'), pen=pg.mkPen(color='#ffffff'))
        self._plot.addItem(self._marker)
        self._marker.setData([self._x[0]], [self._z[0]])  # start marker at the first sample


    def set_cursor_distance(self, distance: float) -> None:
        """Move the marker to the sample nearest ``distance`` (m); hide it when distance < 0."""
        if self._marker is None or self._distance is None:
            return
        if distance < 0:
            self._marker.setData([], [])
            return
        i = int(np.argmin(np.abs(self._distance - distance)))
        self._marker.setData([self._x[i]], [self._z[i]])