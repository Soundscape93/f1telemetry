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
import math

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
_PANEL_FILL = "#b4bcc8"   # solid-ish light grey for filled structural panels (floor fences)
_BACKGROUND = "#0d1117"   # fixed dark ground, so the neon colour-coding reads the same on a light & dark desktop. a bit darker than the tooltip
_GAUGE_R = 34

# body regions: (svg id, car_status model key, path d). Two ids may share a model key (sidepods) -
# CarDamage carries a single sidepod value, so both are coloured from it.
_BODY_PARTS = (
    ("floor", "floor",
     "m 262.67186 274.50392 -23.66412 -10e-6 -11.04326 15.25022 3.15521 9.72859 13.93555 -0.26294 "
     "c 0 0 -0.20414 23.69377 -3.2288 35.01953 -1.70083 6.36871 -4.45046 12.58445 -8.2439 17.97546 "
     "-2.98938 4.24834 -11.13969 10.89817 -11.13969 10.89817 l -0.26294 49.16881 h 4.20696 "
     "c 0 0 1.86205 -18.83068 4.47389 -27.86976 3.21235 -11.11731 9.68105 -21.05144 13.62806 -31.92963 "
     "5.91153 -16.29251 11.51802 -32.806 15.00384 -49.78367 1.90218 -9.26456 3.1792 -28.19477 3.1792 -28.19477 z"
     "m -106.22565 -0.52586 23.66412 -1e-5 11.04326 15.25022 -3.15521 9.72859 -13.93555 -0.26294 "
     "c 0 0 0.20414 23.69377 3.2288 35.01953 1.70083 6.36871 4.45046 12.58445 8.2439 17.97546 2.98938 "
     "4.24834 11.13969 10.89817 11.13969 10.89817 l 0.26294 49.16881 h -4.20696 "
     "c 0 0 -1.86205 -18.83068 -4.47389 -27.86976 -3.21235 -11.11731 -9.68105 -21.05144 -13.62806 -31.92963 "
     "-5.91153 -16.29251 -11.51802 -32.806 -15.00384 -49.78367 -1.90218 -9.26456 -3.1792 -28.19477 -3.1792 -28.19477 z"
     "m -4.73284 -0.26294 h -4.73283 "
     "l 1.29207 51.30321 3.43037 32.60129 6.58376 34.15323 13.40967 -1e-5 3.41816 19.19425 9.99152 -0.26294 "
     "-4.73283 -25.50467 -15.56378 -37.45892 -8.70905 -34.88002 z"
     "m 115.42838 0.7888 h 4.73283 "
     "l -1.29207 51.30321 -3.43037 32.60129 -6.58376 34.15323 -13.40967 -10e-6 -3.41816 19.19425 "
     "-9.99152 -0.26294 4.73283 -25.50467 15.56378 -37.45892 8.70905 -34.88002 z"),

    ("front_wing_left", "front_wing_left",
     "m 135.93729 76.514025 67.83717 -27.608153 -0.26293 7.625109 "
     "c -10.31909 1.970196 -15.85683 7.344297 -12.88381 33.655653 "
     "l -16.30195 12.357936 -39.44022 8.41391 z"),

    ("front_wing_right", "front_wing_right",
     "m 282.91783 76.77696 -67.83717 -27.608153 0.26293 7.625109 "
     "c 10.31909 1.970196 15.85683 7.344297 12.88381 33.655653 "
     "l 16.30195 12.357931 39.44022 8.41391 z"),
    
    ("sidepod_left", "sidepod",
     "m 159.07555 226.12392 32.07804 -16.30196 -0.52587 19.45718 -7.30345 8.14636 -10.31318 7.36679 "
     "-24.71587 11.3062 6.78165 -15.55357 z"),

    ("sidepod_right", "sidepod",
     "m 260.56837 226.12392 -32.07804 -16.30196 0.52587 19.45718 7.30345 8.14636 10.31318 7.36679 "
     "24.71587 11.3062 -6.78165 -15.55357 z"),

    ("engine", "engine", 
     "m 199.56836 292.38281 -4.4707 13.67383 -11.83225 0.13025 0.78858 23.92699 7.88768 5.39051 "
     "1.31614 4.73389 5.25781 4.46875 0.96717 7.93765 1.66174 3.63119 16.9596 0.13294 2.32446 -3.6556 "
     "1.22496 -8.4401 c 1.39795 -1.4171 3.34624 -2.39792 4.86512 -3.68043 l 0.52587 -4.4707 "
     "7.49257 -4.20729 1.57908 -26.55539 -10.91245 0.26172 -5.38929 -13.27821 z"),

    ("gearbox", "gearbox", 
     "m 204.16887 363.90176 10.91179 0.26293 0.3944 48.38 -11.56913 0z"),
    
    ("diffuser", "diffuser", 
     "m 181.68795 419.64393 56.39951 -0.13146 0.13146 17.35369 -56.26804 0 z"),

    ("rear_wing", "rear_wing",
     "m 167.7524 444.7542 84.2706 0.3944 4.86429 21.29772 -0.52587 8.15098 -8.15098 -0.13147 "
     "-0.92027 -8.15097 -34.18152 0.26293 0.13147 12.4894 -7.23071 0 "
     "v -12.8838 l -33.65565 -0.13147 -1.57761 8.67685 -7.75658 0.13146 -1.05174 -6.31043 z"),
)

# structural regions (no damage channel) - drawn neutral
_STRUCTURAL = (
    ("Cockpit / halo", "m 223.46428 268.53464 c 0 10.2624 -6.22611 18.58171 -13.90639 18.58171 "
     "-7.68028 0 -13.90638 -8.31932 -13.90638 -18.58171 0 -10.2624 6.2261 -18.58172 13.90638 -18.58172 "
     "7.68029 0 13.90639 8.31932 13.90639 18.58172 z m -33.50481 -1.67116 "
     "c 0 0 1.01397 -11.59864 4.52294 -15.80949 3.82758 -4.59319 10.09476 -8.08575 16.07244 -7.96283 "
     "5.61992 0.11556 11.35945 3.64819 14.78999 8.10108 3.23875 4.20395 3.83349 15.45214 3.83349 15.45214 h 5.58704 "
     "c 0 0 -0.0339 -10.07765 -1.95933 -14.5917 -2.70784 -6.3482 -8.22863 -11.11516 -12.90425 -16.19164 "
     "-2.4908 -2.70435 -8.03234 -7.55911 -8.03234 -7.55911 l -0.6573 -22.34818 -3.5056 0.10955 0.2191 22.01953 "
     "c 0 0 -5.95222 5.05417 -8.59414 7.91583 -4.18918 4.5376 -8.99628 8.90673 -11.42539 14.58462 -2.12781 4.97363 -2.32864 16.0611 -2.32864 16.0611 z"),
)
# solid light-grey filled panels - more opaque than the subtle _STRUCTURAL wash
_PANELS = (
    ("Floor edge wing (left)",
     "m 187.58166 202.24047 -0.17913 7.52356 m -6.98616 -6.44877 v 9.67315 m -7.34443 3.40352 1.07479 -12.36014 "
     "m -14.91491 20.61541 7.82375 -4.36508 2.36704 -22.01059 "
     "c 0 0 -3.01832 -1.94665 -4.15816 -3.30017 -0.89993 -1.06864 -2.00898 -3.67842 -2.00898 -3.67842 z"),
    ("Floor edge wing (right)",
     "m 233.2328 202.77787 0.17913 7.52356 m 6.98616 -6.44877 v 9.67315 m 7.34443 3.40352 -1.07479 -12.36014 "
     "m 14.91491 20.61541 -7.82375 -4.36508 -2.36704 -22.01059 "
     "c 0 0 3.01832 -1.94665 4.15816 -3.30017 0.89993 -1.06864 2.00898 -3.67842 2.00898 -3.67842 z"),
)
# stroke-only OPEN outlines (no fill): nose/chassis sides, turning-vane fins, etc.
_OUTLINES = (
    ("Chassis / nose", 
     "m 198.06412 140.35008 c 0 0 0.20392 -5.42498 -0.49588 -7.99807 -0.53032 -1.94997 -0.63053 -4.4286 -2.38732 -5.42725 "
     "-1.74939 -0.99444 -6.82325 0.17732 -6.82325 0.17732 l 0.13117 -10.09996 c 0 0 4.76667 0.6655 6.42374 -0.22067 "
     "1.27784 -0.68336 1.77288 -1.2696 1.68379 -3.44568 -0.24614 -6.01279 -0.66103 -18.263368 -0.2978 -25.316455 "
     "0.40772 -7.917136 -2.12958 -17.418987 2.8149 -23.615712 2.37768 -2.979857 6.96024 -3.861498 10.77239 -3.840821 "
     "3.41795 0.01854 7.47836 0.884797 9.62053 3.548224 4.40486 5.476693 2.42467 13.873386 2.88475 20.886602 0.51413 7.837072 "
     "-0.13227 22.358792 -0.3418 28.457792 -0.0646 1.87999 1.58568 2.15044 2.77247 2.58233 2.09844 0.76366 7.08373 0.17735 7.08373 0.17735 "
     "l -0.3935 11.41164 c 0 0 -4.44926 -0.32236 -6.2982 0.69901 -1.49935 0.82825 -2.627 2.40699 -3.19892 4.02159 -0.97829 2.76189 -0.0782 8.78975 -0.0782 8.78975 "
     "m 0.27325 12.99262 v -7.33951 m 2.27778 27.33335 -1.01235 -14.93211 m -26.57408 -4.04938 0.50617 -7.33951 "
     "m -2.02469 23.79013 0.75926 -11.89506 m -5.06173 48.8457 2.78395 -26.82718 m 34.67285 27.08026 -3.29012 -27.08026 "
     "m 46.821 91.36424 -0.25308 -15.94445 m -124.77166 15.43828 0.50617 -15.43828"),
)
_ARMS = (                       # suspension arms - neutral stroked lines, no fill
    "m 222.34141 154.34064 23.69478 -2.2721 m -24.01936 -5.68025 24.66853 4.38191 m -23.0456 7.95236 23.2079 -3.24586 "
    "m -22.39644 18.98828 22.39644 -17.52765 m -25.19726 -15.41782 25.48 3.57043 -0.009 -9.57972 6.82481 -5.51353 "
    "-0.32458 39.92408 -5.51797 -4.5442 -23.2079 16.55388 m -51.56684 -29.53732 23.53249 2.59669 "
    "m -23.69478 -4.7065 24.34395 -2.92127 m -22.72102 8.43923 21.58497 3.73274 m -21.58497 -1.62293 20.61122 13.9572 "
    "m 2.59668 -31.64713 -25.31771 4.3819 0.009 -9.57972 -6.82481 -5.51353 0.32458 39.92408 5.51797 -4.5442 22.39643 16.71617"),
# each corner: model key, gauge centre (gx, gy), on-car tyre centre (tx, ty)
_CORNERS = (
    ("fl", 70, 150, 148, 150),
    ("fr", 350, 150, 272, 150),
    ("rl", 70, 430, 148, 428),
    ("rr", 350, 430, 272, 428),
)
_GAUGE_R = 34
_TYRE_W, _TYRE_H = 26.5, 56.3
_BRAKE_W, _BRAKE_H, _BRAKE_GAP = 9, 18, 4     # inboard brake block

_PATH_TOKEN = re.compile(r"[MmLlHhVvCcQqSsTtAaZz]|-?\d*\.?\d+(?:[eE][-+]?\d+)?")


def _arc_to(path: QPainterPath, x0, y0, rx, ry, phi_deg, large_arc, sweep, x, y) -> None:
    """Append an SVG elliptical arc (A/a) to ``path`` as cubic-Bezier segments.

    Endpoint -> centre parameterisation per SVG spec F.6, then <=90 degrees Bezier chunks. Handles
    rx != ry and x-axis rotation, so it copes with anything Inkscape/Figma export.
    """
    if rx == 0 or ry == 0:
        path.lineTo(x, y)
        return
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(phi_deg % 360)
    cos_phi, sin_phi = math.cos(phi), math.sin(phi)
    dx, dy = (x0 - x) / 2, (y0 - y) / 2
    x1p = cos_phi * dx + sin_phi * dy
    y1p = -sin_phi * dx + cos_phi * dy
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    co = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large_arc == sweep:
        co = -co
    cxp = co * rx * y1p / ry
    cyp = -co * ry * x1p / rx
    cx = cos_phi * cxp - sin_phi * cyp + (x0 + x) / 2
    cy = sin_phi * cxp + cos_phi * cyp + (y0 + y) / 2

    def _angle(ux, uy, vx, vy):
        dot = ux * vx + uy * vy
        length = math.hypot(ux, uy) * math.hypot(vx, vy)
        ang = math.acos(max(-1.0, min(1.0, dot / length))) if length else 0.0
        return -ang if ux * vy - uy * vx < 0 else ang

    ux, uy = (x1p - cxp) / rx, (y1p - cyp) / ry
    theta1 = _angle(1, 0, ux, uy)
    dtheta = _angle(ux, uy, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dtheta > 0:
        dtheta -= 2 * math.pi
    elif sweep and dtheta < 0:
        dtheta += 2 * math.pi

    segments = max(1, int(math.ceil(abs(dtheta) / (math.pi / 2))))
    delta = dtheta / segments
    t = 4 / 3 * math.tan(delta / 4)
    theta = theta1
    for _ in range(segments):
        cos1, sin1 = math.cos(theta), math.sin(theta)
        theta2 = theta + delta
        cos2, sin2 = math.cos(theta2), math.sin(theta2)
        ex = cos_phi * rx * cos2 - sin_phi * ry * sin2 + cx
        ey = sin_phi * rx * cos2 + cos_phi * ry * sin2 + cy
        c1x = cos_phi * rx * (cos1 - t * sin1) - sin_phi * ry * (sin1 + t * cos1) + cx
        c1y = sin_phi * rx * (cos1 - t * sin1) + cos_phi * ry * (sin1 + t * cos1) + cy
        c2x = cos_phi * rx * (cos2 + t * sin2) - sin_phi * ry * (sin2 - t * cos2) + cx
        c2y = sin_phi * rx * (cos2 + t * sin2) + cos_phi * ry * (sin2 - t * cos2) + cy
        path.cubicTo(c1x, c1y, c2x, c2y, ex, ey)
        theta = theta2


def _svg_path(d: str) -> QPainterPath:
    """Parse an SVG path ``d`` string into a QPainterPath.

    Supports M/L/H/V/C/Q/Z plus smooth curves (S/T) and elliptical arcs (A), absolute and relative -
    enough for anything Inkscape/Figma export. Transforms are NOT read: paths must carry their
    geometry in ``d`` with any ``transform`` flattened (see the Inkscape workflow in DECISIONS.md).
    """
    tokens = _PATH_TOKEN.findall(d)
    path = QPainterPath()
    i, n = 0, len(tokens)
    cx = cy = sx = sy = 0.0
    ctrl_x = ctrl_y = 0.0          # last cubic/quad control point, for S/T reflection
    cmd = prev = ""

    def f() -> float:
        nonlocal i
        val = float(tokens[i])
        i += 1
        return val

    while i < n:
        if tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
        upper, rel = cmd.upper(), cmd.islower()
        if upper == "M":
            x, y = f(), f()
            if rel:
                x, y = x + cx, y + cy
            cx, cy = sx, sy = x, y
            path.moveTo(cx, cy)
            cmd = "l" if rel else "L"          # subsequent pairs are implicit lineto
        elif upper == "L":
            x, y = f(), f()
            if rel:
                x, y = x + cx, y + cy
            cx, cy = x, y
            path.lineTo(cx, cy)
        elif upper == "H":
            v = f()
            cx = v + cx if rel else v
            path.lineTo(cx, cy)
        elif upper == "V":
            v = f()
            cy = v + cy if rel else v
            path.lineTo(cx, cy)
        elif upper == "C":
            x1, y1, x2, y2, x, y = f(), f(), f(), f(), f(), f()
            if rel:
                x1, y1, x2, y2, x, y = x1 + cx, y1 + cy, x2 + cx, y2 + cy, x + cx, y + cy
            path.cubicTo(x1, y1, x2, y2, x, y)
            ctrl_x, ctrl_y, cx, cy = x2, y2, x, y
        elif upper == "S":
            x2, y2, x, y = f(), f(), f(), f()
            if rel:
                x2, y2, x, y = x2 + cx, y2 + cy, x + cx, y + cy
            x1, y1 = (2 * cx - ctrl_x, 2 * cy - ctrl_y) if prev in ("C", "S") else (cx, cy)
            path.cubicTo(x1, y1, x2, y2, x, y)
            ctrl_x, ctrl_y, cx, cy = x2, y2, x, y
        elif upper == "Q":
            x1, y1, x, y = f(), f(), f(), f()
            if rel:
                x1, y1, x, y = x1 + cx, y1 + cy, x + cx, y + cy
            path.quadTo(x1, y1, x, y)
            ctrl_x, ctrl_y, cx, cy = x1, y1, x, y
        elif upper == "T":
            x, y = f(), f()
            if rel:
                x, y = x + cx, y + cy
            x1, y1 = (2 * cx - ctrl_x, 2 * cy - ctrl_y) if prev in ("Q", "T") else (cx, cy)
            path.quadTo(x1, y1, x, y)
            ctrl_x, ctrl_y, cx, cy = x1, y1, x, y
        elif upper == "A":
            rx, ry, phi, large_arc, sweep = f(), f(), f(), f(), f()
            x, y = f(), f()
            if rel:
                x, y = x + cx, y + cy
            _arc_to(path, cx, cy, rx, ry, phi, large_arc != 0, sweep != 0, x, y)
            cx, cy = x, y
        elif upper == "Z":
            path.closeSubpath()
            cx, cy = sx, sy
        else:
            i += 1
            continue
        prev = upper
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
            f"QGraphicsView {{ background: {_BACKGROUND}; border: none; border-radius: 6px; }}"
            "QToolTip { color: #e6edf3; background-color: #1c242e;"
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
        for label, d in _PANELS:                       # solid light-grey filled floor fences
            item = QGraphicsPathItem(_svg_path(d))
            self._paint(item, _PANEL_FILL, fill_alpha=150, width=1.8)
            item.setZValue(1)
            item.setToolTip(label)
            self._scene.addItem(item)
        for label, d in _OUTLINES:                     # stroke-only open outlines, with tooltip
            item = QGraphicsPathItem(_svg_path(d))
            item.setPen(self._stroke_pen(_NEUTRAL, 1.8))
            item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            item.setZValue(1)
            item.setToolTip(label)
            self._scene.addItem(item)
        for d in _ARMS:
            item = QGraphicsPathItem(_svg_path(d))
            item.setPen(self._stroke_pen(_NEUTRAL, 1.6))
            item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            item.setZValue(1)
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

            # inboard brake block, coloured by brake temperature
            if corner is not None:
                inboard = 1 if tx < 210 else -1     # toward the car centreline
                bx = tx + inboard * (_TYRE_W / 2 + _BRAKE_GAP + _BRAKE_W / 2)
                brake_colour = status_colour(corner.brake_status)
                brake = QGraphicsPathItem(self._rounded_rect(bx, ty, _BRAKE_W, _BRAKE_H, 3))
                self._paint(brake, brake_colour)
                self._glow(brake, brake_colour)
                brake.setZValue(2)
                brake.setToolTip(tip)
                self._scene.addItem(brake)

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
