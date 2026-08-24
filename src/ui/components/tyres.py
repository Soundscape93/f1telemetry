"""Compound tyre icons for the results-screen TYRE column.

Draws a small tyre seen face-on - a dark tread ring with a thick coloured stripe across the
middle carrying the compound letter (S/M/H/I/W) - in the game's compound colours. Drawn with
QPainter (no external art, so no Pirelli-artwork licensing question) and cached per compound.

Keyed on the *visual* compound (see ``protocol.enums.VisualTyreCompound``); an unknown compound
yields None so the cell simply shows nothing.
"""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap

# visual compound -> (letter, colour). Covers F1 modern + F2 '20 visuals.
_COMPOUND_STYLE: dict[int, tuple[str, str]] = {
    16: ("S", "#e10600"),  # soft - red
    17: ("M", "#fefc00"),  # medium - yellow
    18: ("H", "#ffffff"),  # hard - white
    7: ("I", "#3bb143"),   # intermediate - green
    8: ("W", "#1e6fd9"),   # wet - blue

    # F2
    19: ("SS", "#c56cf0"), # super soft - purple
    20: ("SS", "#e10600"), # soft - red
    21: ("M", "#fefc00"),  # medium - yellow
    22: ("H", "#ffffff"),  # hard - white
    15: ("W", "#1e6fd9"),  # wet - blue


}

_TYRE_EDGE = "#111114"
_RIM = "#5a5a60"


def compound_style(visual_compound: int | None) -> tuple[str, str] | None:
    """The ``(letter, colour)`` for a visual compound, or None if it isn't one we know.

    The public read of ``_COMPOUND_STYLE``, so everything needing the game's compound colours - the
    tyre icon here, the session detail's stint charts - shares one table instead of redefining it.
    The colour is a ``#rrggbb`` string, usable as a Qt colour or a pyqtgraph pen.
    """
    if visual_compound is None:
        return None
    return _COMPOUND_STYLE.get(int(visual_compound))


def _draw(painter: QPainter, dim: float, letter: str, colour: str) -> None:
    """Paint one tyre into a ``dim``×``dim`` square."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    edge = dim * 0.05
    body = QRectF(edge, edge, dim - 2 * edge, dim - 2 * edge)

    # tyre body + a faint inner rim ring to read as a tyre seen head-on
    painter.setPen(QPen(QColor(_TYRE_EDGE), dim * 0.05))
    painter.setBrush(QColor("#0000000"))
    painter.drawEllipse(body)
    inset = dim * 0.15
    painter.setPen(QPen(QColor(_RIM), dim * 0.04))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(body.adjusted(inset, inset, -inset, -inset))

    # coloured compound letter centred on the stripe
    font = QFont()
    font.setWeight(QFont.Weight.Black)
    font.setPixelSize(int(dim * 0.46))
    painter.setFont(font)
    painter.setPen(QColor(colour))
    painter.drawText(QRectF(0, 0, dim, dim), Qt.AlignmentFlag.AlignCenter, letter)


@lru_cache(maxsize=None)
def tyre_pixmap(visual_compound: int, size: int = 22) -> QPixmap | None:
    """A cached tyre ``QPixmap`` for a visual compound, or None if the compound is unknown.

    Rendered at 2× and tagged with a device-pixel ratio so it stays crisp on HiDPI displays.
    """
    style = compound_style(visual_compound)
    if style is None:
        return None
    letter, colour = style
    scale = 2
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    _draw(painter, size * scale, letter, colour)
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return pixmap
