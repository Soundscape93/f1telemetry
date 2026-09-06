"""Titled section panels - the framed box every page's content sits in.

Shared because two surfaces build the same thing: the session detail page's four boxes, and the
weekend-filtered overview's race classifications. Sharing by *builder* is how this repo already
does it (``build_classification_table``, called by three unrelated pages), and it is what keeps a
second caller from growing a second definition of what a titled box looks like.
"""
from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from ..style import apply_heading


def panel_box(title: str, content: QWidget, fill: bool = True,
              scroll: bool = False) -> QWidget:
    """One titled section: a bold heading over its content, inside a light frame.

    A framed ``QLabel`` heading rather than a ``QGroupBox``: a group box draws its title in the
    *widget's* own font, so sizing the title up would size every child that inherits it. Here only
    the heading is styled, and ``StyledPanel`` follows the palette with no stylesheet at all.

    ``fill`` pushes the content to the top, leaving empty space below its last row, so the shorter
    box in a row sits naturally beside a taller one instead of stretching its rows apart.

    ``scroll`` puts the content in a scroll area, for a box inside a height-capped row whose
    content has no upper bound. It supersedes ``fill``: the scroll area already takes the spare
    height, so a stretch beside it would have nothing to push against. A *table* does not need
    this - left unfrozen it scrolls itself and keeps its header row pinned, which a scroll area
    around the whole table would not.
    """
    frame = QFrame()
    frame.setFrameShape(QFrame.Shape.StyledPanel)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(10, 8, 10, 10)
    heading = QLabel(title)
    apply_heading(heading, size_px=17)
    layout.addWidget(heading)

    if scroll:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(content)
        layout.addWidget(area, 1)
        return frame

    layout.addWidget(content)
    if fill:
        layout.addStretch(1)
    return frame
