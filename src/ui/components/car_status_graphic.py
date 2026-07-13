"""The lap-detail car-status graphic.

An in-game-style top-down car: a neon silhouette whose body regions are coloured by damage/wear and
whose four tyres are pulled out to corner gauges (wear % + carcass temp). Shapes are authored as SVG
path ``d`` strings (draw in Inkscape, paste the ``d``) and rendered as ``QGraphicsPathItem``s so each
part recolours with ``setBrush`` and carries a native ``setToolTip`` - the SVG-authored →
QGraphicsScene path-item approach chosen in DECISIONS.md (2c). All health/colour logic lives in the
Qt-free ``car_status`` model; this widget is the thin renderer over it.
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsEllipseItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

from .car_status import Status, damage_parts, status_colour, tyre_corners

_VIEWBOX = QRectF(0, 0, 420, 560)
_NEUTRAL = "#8b949e"      # structural / no-data grey (matches car_status Status.NONE)
_GAUGE_R = 34

# body regions: (svg id, car_status model key, path d). Two ids may share a model key (sidepods) -
# CarDamage carries a single sidepod value, so both are coloured from it.
_BODY_PARTS = (
    ("floor", "floor", "M182 150 L238 150 L262 300 L268 452 L152 452 L158 300 Z"),
    ("front_wing_left", "front_wing_left", "M150 96 L204 78 L204 96 L168 112 L150 112 Z"),
    ("front_wing_right", "front_wing_right", "M270 96 L216 78 L216 96 L252 112 L270 112 Z"),
    ("sidepod_left", "sidepod", "M186 236 L160 250 L158 336 L188 322 Z"),
    ("sidepod_right", "sidepod", "M234 236 L260 250 L262 336 L232 322 Z"),
    ("engine", "engine", "M196 250 L224 250 L232 356 L188 356 Z"),
    ("gearbox", "gearbox", "M194 356 L226 356 L230 410 L190 410 Z"),
    ("diffuser", "diffuser", "M196 410 L224 410 L230 452 L190 452 Z"),
    ("rear_wing", "rear_wing",
     "M150 462 L270 462 L270 490 L150 490 Z M150 462 L146 496 L156 496 L156 462 Z "
     "M270 462 L274 496 L264 496 L264 462 Z"),
)

# structural regions (no damage channel) - drawn neutral
_STRUCTURAL = (
    ("Chassis / nose", "M200 82 L220 82 L232 176 L188 176 Z"),
    ("Cockpit / halo", "M192 176 Q210 168 228 176 L232 250 Q210 262 188 250 Z"),
)
_ARMS = (                       # suspension arms - neutral stroked lines, no fill
    "M190 150 L152 150", "M190 168 L156 182",
    "M230 150 L268 150", "M230 168 L264 182",
    "M190 392 L152 405", "M232 392 L270 405",
)
# each corner: model key, gauge centre (gx, gy), on-car tyre centre (tx, ty)
_CORNERS = (
    ("fl", 70, 150, 140, 150),
    ("fr", 350, 150, 280, 150),
    ("rl", 70, 430, 140, 405),
    ("rr", 350, 430, 280, 405),
)
_GAUGE_R = 34
_TYRE_W, _TYRE_H = 16, 34

_PATH_TOKEN = re.compile(r"[MmLlHhVvCcQqZz]|-?\d*\.?\d+(?:[eE][-+]?\d+)?")


def _svg_path(d: str) -> QPainterPath:
    """Parse an SVG path ``d`` string (M/L/H/V/C/Q/Z, absolute + relative) into a QPainterPath.

    Enough for hand-authored car shapes; arcs (A) and smooth (S/T) aren't used - re-author without
    them, or extend here, if a future part needs them.
    """
    tokens = _PATH_TOKEN.findall(d)
    path = QPainterPath()
    i, n = 0, len(tokens)
    cx = cy = sx = sy = 0.0
    cmd = ""

    def f() -> float:
        nonlocal i
        val = float(tokens[i])
        i += 1
        return val

    while i < n:
        if tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
        if cmd in ("M", "m"):
            x, y = f(), f()
            if cmd == "m":
                x, y = x + cx, y + cy
            cx, cy = x, y
            sx, sy = x, y
            path.moveTo(cx, cy)
            cmd = "l" if cmd == "m" else "L"       # subsequent pairs are implicit lineto
        elif cmd in ("L", "l"):
            x, y = f(), f()
            if cmd == "l":
                x, y = x + cx, y + cy
            cx, cy = x, y
            path.lineTo(cx, cy)
        elif cmd in ("H", "h"):
            x = f()
            cx = x + cx if cmd == "h" else x
            path.lineTo(cx, cy)
        elif cmd in ("V", "v"):
            y = f()
            cy = y + cy if cmd == "v" else y
            path.lineTo(cx, cy)
        elif cmd in ("C", "c"):
            x1, y1, x2, y2, x, y = f(), f(), f(), f(), f(), f()
            if cmd == "c":
                x1, y1, x2, y2, x, y = x1 + cx, y1 + cy, x2 + cx, y2 + cy, x + cx, y + cy
            path.cubicTo(x1, y1, x2, y2, x, y)
            cx, cy = x, y
        elif cmd in ("Q", "q"):
            x1, y1, x, y = f(), f(), f(), f()
            if cmd == "q":
                x1, y1, x, y = x1 + cx, y1 + cy, x + cx, y + cy
            path.quadTo(x1, y1, x, y)
            cx, cy = x, y
        elif cmd in ("Z", "z"):
            path.closeSubpath()
            cx, cy = sx, sy
        else:
            i += 1
    return path


class CarStatusGraphic(QGraphicsView):
    """Renders one lap's ``LapTyreContext`` + ``CarDamage`` as the colour-coded car graphic."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(
            "QGraphicsView { background: transparent; border: none; }"
            "QToolTip { color: #e6edf3; background-color: #1c242e;" \
            " border: 1px solid #444c56; padding: 4px 6px; }"
        )
        self.setMinimumSize(230, 300)
        self.setMaximumWidth(380)

    def set_lap(self, tyre_context, damage) -> None:
        """(Re)build the scene for one lap; either input may be None (drawn neutral / empty)."""
        self._scene.clear()
        self._draw_structural()
        self._draw_body(damage)
        self._draw_corners(tyre_context, damage)
        self._scene.setSceneRect(_VIEWBOX)
        self.fitInView(_VIEWBOX, Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(_VIEWBOX, Qt.AspectRatioMode.KeepAspectRatio)

    def showEvent(self, event):
        super().showEvent(event)
        self.fitInView(_VIEWBOX, Qt.AspectRatioMode.KeepAspectRatio)

    # --- drawing helpers ----------------------------------------------------------
    def _draw_body(self, damage) -> None:
        parts = {p.key: p for p in damage_parts(damage)} if damage is not None else {}
        for _svg_id, model_key, d in _BODY_PARTS:
            part = parts.get(model_key)
            status = part.status if part else Status.NONE
            item = QGraphicsPathItem(_svg_path(d))
            self._paint(item, status_colour(status))
            self._glow(item, status_colour(status))
            item.setZValue(0 if model_key == "floor" else 2)
            if part is not None:
                item.setToolTip(f"{part.label} — {part.detail}")
            self._scene.addItem(item)

    def _draw_structural(self) -> None:
        for label, d in _STRUCTURAL:
            item = QGraphicsPathItem(_svg_path(d))
            self._paint(item, _NEUTRAL, fill_alpha=26, width=1.8)
            item.setZValue(1)
            item.setToolTip(label)
            self._scene.addItem(item)
        for d in _ARMS:
            item = QGraphicsPathItem(_svg_path(d))
            item.setPen(self._stroke_pen(_NEUTRAL, 1.6))
            item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            item.setZValue(1)
            self._scene.addItem(item)

    def _draw_connectors(self) -> None:
        for d in _CONNECTORS:
            pen = self._stroke_pen(_NEUTRAL, 1.4)
            pen.setStyle(Qt.PenStyle.DotLine)
            item = QGraphicsPathItem(_svg_path(d))
            item.setPen(pen)
            item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            item.setZValue(-1)
            self._scene.addItem(item)

    def _draw_corners(self, tyre_context, damage) -> None:
        corners = ({c.key: c for c in tyre_corners(tyre_context, damage)}
                   if tyre_context is not None else {})
        for key, gx, gy, tx, ty in _CORNERS:
            corner = corners.get(key)
            temp_colour = corner.temp_colour if corner else _NEUTRAL
            tip = corner.detail if corner else "No tyre data"

            # dashed connector: on-car tyre <-> gauge (behind both, so endpoints tuck under them)
            edge_x = tx - _TYRE_W / 2 if gx < tx else tx + _TYRE_W / 2
            conn = QGraphicsPathItem(self._line_path(edge_x, ty, gx, gy))
            pen = self._stroke_pen(_NEUTRAL, 1.4)
            pen.setStyle(Qt.PenStyle.DotLine)
            conn.setPen(pen)
            conn.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            conn.setZValue(-1)
            self._scene.addItem(conn)

            # on-car tyre block, coloured by tyre temperature
            tyre = QGraphicsPathItem(self._rounded_rect(tx, ty, _TYRE_W, _TYRE_H, 5))
            self._paint(tyre, temp_colour)
            self._glow(tyre, temp_colour)
            tyre.setZValue(2)
            tyre.setToolTip(tip)
            self._scene.addItem(tyre)

            # corner gauge ring + wear% / carcass-temp text
            ring = QGraphicsEllipseItem(gx - _GAUGE_R, gy - _GAUGE_R, 2 * _GAUGE_R, 2 * _GAUGE_R)
            self._paint(ring, temp_colour, fill_alpha=30, width=2.6)
            self._glow(ring, temp_colour)
            ring.setZValue(3)
            ring.setToolTip(tip)
            self._scene.addItem(ring)

            wear_text = f"{corner.wear_pct:.0f}%" if corner else "--"
            wear_colour = corner.wear_colour if corner else _NEUTRAL
            self._text(wear_text, gx, gy - 6, wear_colour, 13, True, tip)
            if corner is not None:
                self._text(f"{corner.carcass_temp}°C", gx, gy + 12, _NEUTRAL, 8, False, tip)

    def _text(self, text, cx, cy, colour, point_size, bold, tooltip) -> None:
        item = QGraphicsSimpleTextItem(text)
        font = QFont()
        font.setPointSizeF(point_size)
        font.setBold(bold)
        item.setFont(font)
        item.setBrush(QColor(colour))
        rect = item.boundingRect()
        item.setPos(cx - rect.width() / 2, cy - rect.height() / 2)
        item.setZValue(4)
        item.setToolTip(tooltip)
        self._scene.addItem(item)

    @staticmethod
    def _stroke_pen(colour, width) -> QPen:
        pen = QPen(QColor(colour))
        pen.setWidthF(width)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        return pen
    
    @staticmethod
    def _line_path(x1, y1, x2, y2) -> QPainterPath:
        path = QPainterPath()
        path.moveTo(x1, y1)
        path.lineTo(x2, y2)
        return path

    @staticmethod
    def _rounded_rect(cx, cy, w, h, r) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(cx - w / 2, cy - h / 2, w, h, r, r)
        return path

    def _paint(self, item, colour, *, fill_alpha=55, width=2.4) -> None:
        item.setPen(self._stroke_pen(colour, width))
        fill = QColor(colour)
        fill.setAlpha(fill_alpha)
        item.setBrush(QBrush(fill))

    @staticmethod
    def _glow(item, colour) -> None:
        effect = QGraphicsDropShadowEffect()
        effect.setBlurRadius(8)
        effect.setOffset(0, 0)
        glow = QColor(colour)
        glow.setAlpha(180)
        effect.setColor(glow)
        item.setGraphicsEffect(effect)
