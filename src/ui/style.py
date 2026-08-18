"""Shared UI style tokens and font helpers.

Fixed colours chosen to read on both the light and dark platform themes. We deliberately avoid Qt
Style Sheet palette roles for muted text: ``palette(mid)`` resolves ``QPalette.Mid``, a 3D-bevel
role (not a text role) that several platform themes - notably Ubuntu's - leave poorly defined or
re-resolve inconsistently on show/navigation, so ``color: palette(mid)`` text can render unreadable
and flip between readable/unreadable across page changes. A fixed mid-grey is stable everywhere.

**Fonts go through the helpers here, never through a stylesheet.** Setting *any* stylesheet on a
widget hands its painting to ``QStyleSheetStyle``, which resolves and *caches* a palette for that
widget at apply time - so a label styled only ``"font-size: 20px; font-weight: 600"`` freezes the
**old theme's** default text colour into itself, despite never asking for a colour, and survives
the ``unpolish``/``polish`` pass in ``app._install_theme_refresh``. That was A4: a live light/dark
switch left every heading in the previous theme's colour until restart, in every release from
v0.3.0 to v0.8.0. A widget with *no* stylesheet follows the palette natively.

A stylesheet that sets its colour **explicitly** - ``MUTED_TEXT_QSS`` - is unaffected and stays,
because the cached palette never reaches the text. ``test/ui/test_style.py`` enforces the split.

**Text is sized in pixels, one scale for the whole UI.** A4 found four ``pt`` sizes mixed in with
eleven ``px`` ones, which is how the Help title ended up a quarter larger than every other page
title. There is no point-size path here on purpose: adding one is what lets the two units drift
apart again. The scale is 20px titles, 18px sub-headings, 14px body, 11px small.
"""
from __future__ import annotations

from PySide6.QtGui import QFont

MUTED_TEXT = "#8b949e"              # muted / secondary text; reads on both light and dark grounds
MUTED_TEXT_QSS = f"color: {MUTED_TEXT};"   # drop-in replacement for "color: palette(mid);"

# Every stylesheet these helpers replaced said ``font-weight: 600``. QFont.Weight.DemiBold *is*
# 600; setBold(True) is Bold == 700, a visibly heavier face on every heading in the app. Exported
# so no call site has to make that choice.
HEADING_WEIGHT = QFont.Weight.DemiBold


def apply_font(widget, *, size_px: int | None = None, weight: QFont.Weight | None = None,
               italic: bool | None = None) -> None:
    """Set font attributes on ``widget`` without giving it a stylesheet.

    Starts from ``widget.font()`` and mutates only what was asked for, so family, hinting and
    everything unspecified stay inherited from the application font.

    ``size_px`` maps to ``setPixelSize``. Point sizes are deliberately not offered - see the module
    docstring - so the UI cannot drift back into two competing scales.
    """
    if size_px is not None and size_px <= 0:
        raise ValueError(f"size_px must be a positive pixel size, got {size_px!r}")

    font = widget.font()
    if size_px is not None:
        font.setPixelSize(size_px)
    if weight is not None:
        font.setWeight(weight)
    if italic is not None:
        font.setItalic(italic)
    widget.setFont(font)


def apply_heading(widget, *, size_px: int) -> None:
    """A heading: ``HEADING_WEIGHT`` at an explicit pixel size."""
    apply_font(widget, size_px=size_px, weight=HEADING_WEIGHT)


def apply_bold(widget) -> None:
    """A caption: ``HEADING_WEIGHT`` at whatever size the widget already has."""
    apply_font(widget, weight=HEADING_WEIGHT)
