"""A reusable value-on-a-range row: ``name | min | track+marker | max | value``.

A thin, view-agnostic building block for any readout that shows a numeric value within an adjustable
range - the lap-detail setup panel and the session view (probably) use this. ``SliderMarkerBar``paints
the track + value marker; ``SetupSliderRow`` composes it with the label columns. Fixed column widths
mean independently stacked rows still line up without a shared grid.

Callers pass already-formatted strings + a 0..1 marker fraction, so this stays free of any
domain/range logic (that lives with the caller, e.g. ``setup_panel._SETUP_SPEC``).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from ..style import MUTED_TEXT_QSS, apply_bold

# --- slider rail + value-marker styling ------------------------------
_RAIL_H = 6         # slider rail thickness (px)
_MARKER_W = 3       # value marker line width (px)
_MARKER_COLOUR = "#58a6ff"  # value marker / fill blue

# shared column widths so separatly-stacket rows align without a shared grid
NAME_W = 180
EDGE_W = 40     # min/max labels
VALUE_W = 70


class SliderMarkerBar(QWidget):
    """A thin horizontal rail with a marker at ``fraction`` (0..1), plus a subtle fill up to it.
    
    The drawable rail is inset by the marker half-width, so a value sitting exactly on min/max
    still draws its marker fully inside the widget - values at the extremas stay readable.
    """

    def __init__(self, fraction: float, parent = None):
        super().__init__(parent)
        self._fraction = min(1.0, max(0.0, fraction))
        self.setMinimumSize(120, 18)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    
    def set_fraction(self, fraction: float) -> None:
        """Reposition the marker (0..1, clamped) and repaint."""
        self._fraction = min(1.0, max(0.0, fraction))
        self.update()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        inset = _MARKER_W + 2
        x0, x1 = inset, w - inset
        span = max(1, x1 - x0)
        cy = h / 2.0

        # base rail
        rail = QRectF(x0, cy - _RAIL_H / 2, span, _RAIL_H)
        base = QColor("#6e7681"); base.setAlpha(90)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(base)
        painter.drawRoundedRect(rail, _RAIL_H / 2, _RAIL_H / 2)

        # subtle fill up to the marker
        mark_x = x0 + span * self._fraction
        if mark_x > x0:
            fill = QRectF(x0, cy - _RAIL_H / 2, mark_x - x0, _RAIL_H)
            accent = QColor(_MARKER_COLOUR); accent.setAlpha(120)
            painter.setBrush(accent)
            painter.drawRoundedRect(fill, _RAIL_H / 2, _RAIL_H / 2)
        
        # value marker line (taller then the rail so it reads at the extremes)
        pen = QPen(QColor(_MARKER_COLOUR))
        pen.setWidth(_MARKER_W)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(int(mark_x), int(cy - h * 0.35), int(mark_x), int(cy + h * 0.35))
        painter.end()


class SetupSliderRow(QWidget):
    """One ``name | min | track+marker | max | value`` row over fixed-width columns.
    
    All numeric values are pre-formatted strings; ``fraction`` (0..1) positions the marker. The
    selected value lives in its own bold column so it never overlaps the min/max ends.
    """

    def __init__(self, *, name: str, min_text: str, max_text: str, value_text: str, 
                 fraction: float, parent = None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        
        name_label = QLabel(name)
        name_label.setFixedWidth(NAME_W)

        min_label = QLabel(min_text)
        min_label.setFixedWidth(EDGE_W)
        min_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        min_label.setStyleSheet(MUTED_TEXT_QSS)

        bar = SliderMarkerBar(fraction)

        max_label = QLabel(max_text)
        max_label.setFixedWidth(EDGE_W)
        max_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        max_label.setStyleSheet(MUTED_TEXT_QSS)

        value_label = QLabel(value_text)
        value_label.setFixedWidth(VALUE_W)
        value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        apply_bold(value_label)

        row.addWidget(name_label)
        row.addWidget(min_label)
        row.addWidget(bar, 1)       # the rail absorbs the horizontal slack
        row.addWidget(max_label)
        row.addWidget(value_label)


    
        
