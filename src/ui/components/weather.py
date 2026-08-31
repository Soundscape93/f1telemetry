"""Outline weather icons for a session's conditions.

Line art with ``QPainter`` and no bundled asset: a sun, a cloud, raindrops and a bolt,
composed into the conditions the game reports. Uncoloured on purpose - every stroke uses the
widget's own palette text colour, read at paint time, so the icon follows a live light/dark
switch. A cached ``QPixmap`` would freeze the stroke colour at creating.

The sun behind a cloud is drawn by clipping the sun to the area *outside* the cloud silhoutte,
rather than painting an opaque cloud over it: an opaque cloud would need a background colour to
erase with, and would show as a patch wherever the card's background isn't exactly that colour.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ...protocol.enums import Weather
from ..formatting import weather_label

# A session that ran both dry and wet. NOT a Weather member: the game reports one condition per
# Session packet and the assembler keeps only the last, so nothing selects this today. Filling it
# means accumulating the distinct `weather` values seen across a session's Session packets -
# ground truth, unlike weatherForecastSamples, which is weekend-wide, rolls past samples off, and
# is a forecast that `forecast_accuracy` may mark Approximate.
MIXED = "mixed"

_ICON_PX = 18
# Storm is "heavy rain plus a bolt", but four drops and a bolt turn to mush at 18 px - two drops
# flanking the bolt is what actually reads at this size.
_DROPS = {Weather.LIGHT_RAIN: 2, Weather.HEAVY_RAIN: 4, Weather.STORM: 2, MIXED: 2}


def session_weather(session):
    """What to draw for a session: ``MIXED`` when it ran both dry and wet, else its snapshot.
    
    The sentinel stays inside this module. ``SessionResult.weather`` is a ``Weather`` and the
    stored column an int, so ``MIXED`` - which is neither - is resolved here, at the one seam
    that draws it, from the set of conditions the session recorded. A session ingested before
    that set existed has none and reads as its snapshot, exactly as it did before.
    """
    return MIXED if session.is_mixed_weather else session.weather


class WeatherIcon(QWidget):
    """A small uncoloured line-art icon for one weather condition.

    Carries the condition as its tooltip: the icon replaces the words in a compact row, and a
    picture alone is not an accessible label.
    """

    def __init__(self, weather, size_px: int = _ICON_PX, parent=None) -> None:
        super().__init__(parent)
        self._weather = weather
        self.setFixedSize(size_px, size_px)
        self.setToolTip("Mixed dry / wet" if weather == MIXED else weather_label(weather))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self.palette().text().color())   # read now, never cached: follows the theme
        pen.setWidthF(max(1.0, self.width() / 16.0))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)     # outline only, no fills
        _paint(painter, self._weather, QRectF(0, 0, self.width(), self.height()))


def _paint(painter: QPainter, weather, box: QRectF) -> None:
    """Compose one condition from the shared marks."""
    if weather == Weather.CLEAR:
        _sun(painter, box.center(), box.width() * 0.20)
        return

    # Everything else has a cloud, and rain hangs below it, so the cloud sits high in the box.
    cloud_box = QRectF(box.left(), box.top() + box.height() * 0.06,
                       box.width(), box.height() * 0.72)
    cloud = _cloud_path(cloud_box)

    if weather in (Weather.LIGHT_CLOUD, MIXED):
        _sun_behind(painter, box, cloud)
    painter.drawPath(cloud)

    drops = _DROPS.get(weather, 0)
    if drops:
        _rain(painter, box, drops)
    if weather == Weather.STORM:
        _bolt(painter, box)


def _cloud_path(box: QRectF) -> QPainterPath:
    """One cloud outline: a flat base with fully rounded ends, a big dome, a smaller shoulder.

    ``setFillRule(WindingFill)`` is load-bearing, not decoration. Under ``QPainterPath``'s
    default ``OddEvenFill`` the overlaps between the lobes and the base cancel out, and
    ``simplified()`` returns *four* contours instead of one - the lobes' hidden arcs get stroked
    as interior lines and the icon reads as a pile of bubbles rather than a cloud.
    """
    w, h = box.width(), box.height()
    x, y = box.left(), box.top()
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    # A corner radius of half the base's height is what gives the fully-rounded left and right
    # ends; anything less reads as a rounded rectangle with bumps on top.
    base = QRectF(x, y + h * 0.46, w, h * 0.42)
    path.addRoundedRect(base, h * 0.21, h * 0.21)
    path.addEllipse(QRectF(x + w * 0.14, y, w * 0.50, h * 0.70))             # the big dome
    path.addEllipse(QRectF(x + w * 0.56, y + h * 0.20, w * 0.30, h * 0.46))  # right shoulder
    return path.simplified()


def _sun(painter: QPainter, centre: QPointF, radius: float, rays: int = 8) -> None:
    """A ring with straight rays around it."""
    painter.drawEllipse(centre, radius, radius)
    inner, outer = radius * 1.45, radius * 2.05
    for i in range(rays):
        angle = 2 * math.pi * i / rays
        dx, dy = math.cos(angle), math.sin(angle)
        painter.drawLine(QPointF(centre.x() + dx * inner, centre.y() + dy * inner),
                         QPointF(centre.x() + dx * outer, centre.y() + dy * outer))


def _sun_behind(painter: QPainter, box: QRectF, cloud: QPainterPath) -> None:
    """A sun peeking out from behind the cloud, clipped to whatever the cloud doesn't cover."""
    whole = QPainterPath()
    whole.addRect(box)
    painter.save()
    painter.setClipPath(whole.subtracted(cloud))
    _sun(painter, QPointF(box.left() + box.width() * 0.76, box.top() + box.height() * 0.22),
         box.width() * 0.14)
    painter.restore()


def _rain(painter: QPainter, box: QRectF, drops: int) -> None:
    """Short slanted strokes under the cloud - more of them for heavier rain."""
    top = box.top() + box.height() * 0.84
    bottom = box.bottom() - box.height() * 0.04
    left = box.left() + box.width() * 0.20
    span = box.width() * 0.60
    for i in range(drops):
        x = left + span * (i + 0.5) / drops
        painter.drawLine(QPointF(x + box.width() * 0.03, top),
                         QPointF(x - box.width() * 0.03, bottom))


def _bolt(painter: QPainter, box: QRectF) -> None:
    """A zigzag between the drops, stroked open so it stays line art rather than a filled flash."""
    w, h = box.width(), box.height()
    x, y = box.left(), box.top()
    path = QPainterPath(QPointF(x + w * 0.56, y + h * 0.82))
    path.lineTo(QPointF(x + w * 0.44, y + h * 0.91))
    path.lineTo(QPointF(x + w * 0.53, y + h * 0.91))
    path.lineTo(QPointF(x + w * 0.41, y + h * 1.00))
    painter.drawPath(path)
