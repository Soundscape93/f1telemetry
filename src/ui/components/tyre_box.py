"""The lap-detail tyre widget: a 4-box graphic of the player's tyre state at the lap line.

Renders a LapTyreContext (compound + age header, then per-wheel wear / damage / blisters) into the
real on-car 2x2 layout - front axle on top, rear below - so the corners read spatially:

    FL  FR
    RL  RR

The context's tuples are in UDP wheel order (RL, RR, FL, FR); ``wheel_grid_cells`` is the one place
that maps that order onto grid positions, so it's a plain functuon and unit-tested. The elaborate
car-body render is deffered (see lap-view-plan); this is the simple 1b graphic.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...domain.models import LapTyreContext
from .tyres import tyre_pixmap

# (grid row, grid col, index into the RL, RR, FL, FR tuples, corner label) - the on-car layout.
_GRID_CELLS: tuple[tuple[int, int, int, str], ...] = (
    (0, 0, 2, "FL"), (0, 1, 3, "FR"),
    (1, 0, 0, "RL"), (1, 1, 1, "RR"),
)


def wheel_grid_cells() -> tuple[tuple[int, int, int, str], ...]:
    """The 2x2 placement of the RL, RR, FL, FR tuples: ``(row, col, tuple index, label)`` per wheel."""
    return _GRID_CELLS


def _wear_color(pct: float) -> str:
    """Green (usable) -> orange (high wear) -> red (blowout/terminal risk) for the wear/damage %. Reads on both palettes."""
    if pct >= 80:
        return "#f85149"  # red
    if pct >= 60:
        return "#d29922"   # orange
    return "#3fb950"    # green


def _wheel_cell(label: str, wear: float, damage: int, blisters: int) -> QFrame:
    """One corner box: corner label, big wear %", and a small damage/blisters line."""
    frame = QFrame()
    frame.setFrameShape(QFrame.Shape.StyledPanel)
    box = QVBoxLayout(frame)
    box.setContentsMargins(8, 6, 8, 6)
    box.setSpacing(1)

    corner = QLabel(label)
    corner.setStyleSheet("color: palette(mid); font-size: 10px; font-weight: 600;")

    value = QLabel(f"{wear:.0f}%")
    value.setStyleSheet(f"color: {_wear_color(wear)}; font-size: 18px; font-weight: 700;")

    detail = QLabel(f"dmg {damage}%  bl {blisters}%")
    detail.setStyleSheet("color: palette(mid); font-size: 10px;")

    box.addWidget(corner)
    box.addWidget(value)
    box.addWidget(detail)
    return frame


class TyreBox(QWidget):
    """A compact tyre readout for one lap: compound/age header + the 2x2 per-wheel grid"""

    def __init__(self, tyre_context: LapTyreContext | None = None, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._header = QHBoxLayout()
        outer.addLayout(self._header)
        
        grid_host = QWidget()
        self._grid = QGridLayout(grid_host)
        self._grid.setSpacing(6)
        outer.addWidget(grid_host)

        if tyre_context is not None:
            self.set_context(tyre_context)

    def set_context(self, tyre_context: LapTyreContext) -> None:
        """Render (or re-render) for a tyre context."""
        _clear_layout(self._header)
        pixmax = tyre_pixmap(tyre_context.visual_compound, size=28)
        if pixmax is not None:
            icon = QLabel()
            icon.setPixmap(pixmax)
            self._header.addWidget(icon)
        age = QLabel(f"{tyre_context.age_laps} lap" + ("s" if tyre_context.age_laps != 1 else "") + " old")
        age.setStyleSheet("font-weight: 600;")
        self._header.addWidget(age)
        self._header.addStretch(1)

        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for row, col, idx, label in _GRID_CELLS:
            self._grid.addWidget(
                _wheel_cell(label, tyre_context.wear[idx], tyre_context.damage[idx],
                            tyre_context.blisters[idx]), row, col
            )


def _clear_layout(layout) -> None:
    """Remove and delete every widget in a (possibly nested-item) layout row."""
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().deleteLater()

