"""The lap-detail track map: an equal-aspect XY path plotted from the lap's world coordinates.

No track-image assets - the path is the telemetry itself (pos_x vs pos_z), so it works for every
circuit including league/custom tracks and lives in the same coordinate space as the hover marker.
A distance from the linked TracePlot moves the marker to the nearest sample. pyqtgraph is imported
lazily, matching TracePlot: absent, the widget shows an install hint instead of failing import.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ...domain.models import LapTrace

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
            hint.setStyleSheet("color: palette(mid)")
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
    

    def set_trace(self, trace: LapTrace) -> None:
        """Draw the lap's path (no-op if the lap has no Motion channels or pyqtgraph is absent).

        Two corrections over a raw ``(pos_x, pos_z)`` plot:

        * **Handedness.** F1's world frame is left-handed (X right, Y up, Z forward), so plotting
          X vs Z top-down mirrors the circuit - the lap appears to run the wrong way round
          (clockwise vs anti-clockwise). Negating one axis (here Z) restores the true handedness.
          A pure rotation can't do this; only a reflection flips the running direction. The
          *absolute* rotation still follows the game's world frame, not the broadcast map art -
          matching that would need a per-track constant, which this asset-free view avoids by
          design (see DECISIONS -> track map), so a circuit may appear rotated vs its F1.com map.
        * **Closed loop.** The path is closed (last sample joined back to the first) so a lap whose
          trace doesn't span the whole start/finish straight - e.g. a race lap 1 that begins at the
          grid slot, *past* the S/F line - still draws a complete outline. Both endpoints lie on the
          straight, so the closing segment falls along it and fills the gap; for a full flying lap
          the two endpoints coincide at the line and the segment is ~zero length.
        """
        if self._plot is None or not trace.has_motion:
            return
        pg = self._pg
        self._plot.clear()
        self._distance = np.asarray(trace.distance, dtype=float)
        self._x = np.asarray(trace.pos_x, dtype=float)
        self._z = -np.asarray(trace.pos_z, dtype=float)     # negate one axis -> correct handedness
        path_x = np.append(self._x, self._x[0])             # close the loop (fills a lap-1 S/F gap)
        path_z = np.append(self._z, self._z[0])
        self._plot.plot(path_x, path_z, pen=pg.mkPen("#8b949e", width=2))
        self._marker = pg.ScatterPlotItem(
            size=12, brush=pg.mkBrush("#e10600"), pen=pg.mkPen("#ffffff"))
        self._plot.addItem(self._marker)
        self._marker.setData([self._x[0]], [self._z[0]])

    def set_cursor_distance(self, distance: float) -> None:
        """Move the marker to the sample nearest ``distance`` (m); hide it when distance < 0."""
        if self._marker is None or self._distance is None:
            return
        if distance < 0:
            self._marker.setData([], [])
            return
        i = int(np.argmin(np.abs(self._distance - distance)))
        self._marker.setData([self._x[i]], [self._z[i]])