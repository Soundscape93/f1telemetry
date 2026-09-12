"""A ``ShareDocument`` drawn as an image - the thin painter over ``share_document`` (DECISIONS -> UI,
E19).

**``QTextDocument``, not ``QPainter`` straight onto the image.** A results table needs its columns
sized from their contents, long names wrapped and each row as tall as its tallest cell, and the
text document does all of that; painting directly would mean writing a table layout by hand, in
code the suite cannot see. It also splits the renderer the way ``race_control`` splits the Race
control box: every decision - which colour, which weight, what may wrap, what is escaped, which
icons appear - is made by ``document_html``, a plain string asserted without a ``QApplication``
(``test_share_image``). What is left for ``render_document`` is the paint, verified offscreen.

**1080 px wide, and as tall as the content.** The height is read off the laid-out document, so a
longer penalty list makes a taller image rather than a cut one - the reason a screenshot of the
page was rejected. The width holds because every column of names may wrap (``Column.wrap``); if a
layout still came out wider, the image would widen rather than clip.

**The type is sized to the worst session in this database.** Shanghai's Sprint Race - 22 drivers
and 11 penalty rows - comes out 1080 x 1547 with a 17 px body. WhatsApp's standard quality is
believed to cap a photo's long side at 1600 px; a 22 px body made that session over 2000 px tall, so
it would have been scaled down to about the same text size anyway, and it overflowed the width too.

**One fixed light palette, whatever the app's theme.** Every colour is written into the markup, and
the paint context carries a fixed palette for anything the markup leaves to it. Measured, either
alone keeps a dark-themed app's image byte-identical to a light-themed one's; with neither, the
theme's text colour leaks in. The hues are the app's (``ui/style``) darkened for white paper: the
on-screen tokens are chosen to read on both themes, which on white costs contrast - the gain green
is 2.5:1 there - and faint text is the first thing a chat app's re-compression takes.

Two things Qt's HTML import does that the markup works around, both found on real sessions: an
``<img>`` whose resource was never added paints a broken-image placeholder, so only icons that were
resolved are written; and a table whose last cell is empty swallows the next paragraph's top
margin, so an empty cell is written as a non-breaking space.
"""
from __future__ import annotations

import math
from collections.abc import Container
from functools import lru_cache
from html import escape

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import (
    QAbstractTextDocumentLayout,
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QPainter,
    QPalette,
    QTextDocument,
)
from PySide6.QtSvg import QSvgRenderer

from .flags import flag_path
from .share_document import Block, Cell, Facts, Icon, IconKind, ShareDocument, Table, Tone
from .tyres import tyre_pixmap

WIDTH = 1080                   # px fixed; the height follows the content
_MARGIN = 40                   # px of paper on every side

# The type scale, in px, sized to the worst session here (see module docstring).
_TITLE_PX = 32
_SECTION_PX = 22
_BODY_PX = 17
_SMALL_PX = 13
_CELL_PADDING = 4
_STRONG_WEIGHT = 600          # style.HEADING_WEIGHT, DemiBold - the app's one bold

_FLAG_SIZE = (23, 17)         # 4:3, like the page's flags
_TYRE_PX = 22                 # the page's own tyre icon size; smaller loses the compound letter

_PAPER = "#ffffff"
_INK = "#1f2328"                # 15.8:1 on white
_MUTED = "#59636e"              # 6.1:1
_STRIPE = "#f6f8fa"             # every second row
_HEADER = "#eaeef2"             # a table's header row
_TONE_COLOURS = {
    Tone.PLAIN: _INK,
    Tone.MUTED: _MUTED,
    Tone.FASTEST: "#0969da",    # style.FASTEST_LAP's blue, 5.2:1 (the token itself is 3.7:1)
    Tone.GAIN: "#1a7f37",       # style.POSITION_GAIN's green, 5.1:1 (2.5:1)
    Tone.LOSS: "#cf222e",       # style.POSITION_LOSS's red, 5.4:1 (3.4:1)
}

_NOWRAP = "white-space:nowrap"
_EMPTY = "&nbsp;"


def document_html(document: ShareDocument, icons: Container[Icon] = ()) -> str:
    """The document in the HTML subset ``QTextDocument`` reads - every decision the renderer makes.

    Qt-free: it only builds a string. ``icons`` are the icons the caller holds an image for; any
    other is left out of its cell, so the default draws none.
    """
    parts = [f'<html><body style="color:{_INK}; font-size:{_BODY_PX}px">',
             _paragraph(_escape(document.title),
                        f"font-size:{_TITLE_PX}px; font-weight:{_STRONG_WEIGHT}; margin:0")]
    if document.meta:
        parts.append(_paragraph(_escape(document.meta),
                                f"color:{_MUTED}; margin-top:6px; margin-bottom:0"))
    parts.extend(_block_html(block, icons) for block in document.blocks)
    if document.footer:
        parts.append(_paragraph(_escape(document.footer),
                                f"font-size:{_SMALL_PX}px; color:{_MUTED}; margin-top:24px",
                                align="right"))
    parts.append("</body></html>")
    return "".join(parts)


def render_document(document: ShareDocument) -> QImage:
    """The document painted ``WIDTH`` px wide and exactly as tall as its content.

    Needs a ``QGuiApplication`` for its fonts, and the tyre icon is a ``QPixmap``, so this runs on
    the GUI thread like everything else that paints. It builds no widget.
    """
    images = {icon: image for icon in document.icons()
              if (image := _icon_image(icon)) is not None}
    text = QTextDocument()
    text.setDocumentMargin(0)
    text.setDefaultFont(_body_font())
    for icon, image in images.items():
        text.addResource(QTextDocument.ResourceType.ImageResource, QUrl(_icon_url(icon)), image)
    text.setHtml(document_html(document, images))
    text.setTextWidth(WIDTH - 2 * _MARGIN)

    laid_out = text.size()
    # Widened only when something would otherwise be cut at the image's edge. A full-width table
    # can lay out a pixel or two past the text width - its column widths are rounded to whole
    # pixels - and that lands in the margin, not off the image.
    width = WIDTH if laid_out.width() <= WIDTH - _MARGIN else math.ceil(laid_out.width()) + 2 * _MARGIN
    image = QImage(width, math.ceil(laid_out.height()) + 2 * _MARGIN, QImage.Format.Format_RGB32)
    image.fill(QColor(_PAPER))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.translate(_MARGIN, _MARGIN)
    context = QAbstractTextDocumentLayout.PaintContext()
    context.palette = _fixed_palette()
    text.documentLayout().draw(painter, context)
    painter.end()
    return image


# --- markup ---------------------------------------------------------------------------------------
def _block_html(block: Block, icons: Container[Icon]) -> str:
    if isinstance(block, Table):
        return _table_html(block, icons)
    if isinstance(block, Facts):
        return _facts_html(block, icons)
    return _heading_html(block.title) + "".join(
        _paragraph(_cell_html(line, icons), "margin-top:0; margin-bottom:6px")
        for line in block.lines)


def _table_html(table: Table, icons: Container[Icon]) -> str:
    """A title, its note, then the table: a shaded header row and every second row striped."""
    header = "".join(
        f'<td align="{column.align.value}" style="{_NOWRAP}; font-size:{_SMALL_PX}px; '
        f'font-weight:{_STRONG_WEIGHT}; color:{_MUTED}">{_escape(column.header) or _EMPTY}</td>'
        for column in table.columns)
    rows = []
    for index, row in enumerate(table.rows):
        stripe = f' bgcolor="{_STRIPE}"' if index % 2 else ""
        cells = []
        for column, cell in zip(table.columns, row, strict=True):
            nowrap = "" if column.wrap else f' style="{_NOWRAP}"'
            cells.append(f'<td align="{column.align.value}" valign="middle"{nowrap}>'
                         f'{_cell_html(cell, icons)}</td>')
        rows.append(f"<tr{stripe}>{''.join(cells)}</tr>")
    return (_heading_html(table.title, table.note)
            + f'<table width="100%" cellspacing="0" cellpadding="{_CELL_PADDING}">'
            + f'<tr bgcolor="{_HEADER}">{header}</tr>{"".join(rows)}</table>')


def _facts_html(facts: Facts, icons: Container[Icon]) -> str:
    """One line of labelled values: a small muted label over each value, spread across the width."""
    if not facts.pairs:
        return _heading_html(facts.title)
    cells = "".join(
        f'<td valign="top"><span style="font-size:{_SMALL_PX}px; color:{_MUTED}">'
        f"{_escape(key.upper())}</span><br>{_cell_html(value, icons)}</td>"
        for key, value in facts.pairs)
    return (_heading_html(facts.title)
            + '<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:18px">'
            + f"<tr>{cells}</tr></table>")


def _heading_html(title: str, note: str = "") -> str:
    """A block's title and the muted note under it; nothing at all for a block with neither."""
    out = ""
    if title:
        out += _paragraph(_escape(title), f"font-size:{_SECTION_PX}px; font-weight:{_STRONG_WEIGHT}; "
                                         "margin-top:28px; margin-bottom:4px")
    if note:
        out += _paragraph(_escape(note), f"color:{_MUTED}; margin-top:0; margin-bottom:8px")
    return out


def _cell_html(cell: Cell, icons: Container[Icon]) -> str:
    """One cell: its icon if there is an image for it, then its text in its tone and weight.

    Never empty - see the module docstring for what an empty last cell does to the next heading.
    """
    styles = []
    if cell.tone is not Tone.PLAIN:
        styles.append(f"color:{_TONE_COLOURS[cell.tone]}")
    if cell.strong:
        styles.append(f"font-weight:{_STRONG_WEIGHT}")
    content = _escape(cell.text)
    if content and styles:
        style = "; ".join(styles)
        content = f'<span style="{style}">{content}</span>'
    if cell.icon is not None and cell.icon in icons:
        width, height = _FLAG_SIZE if cell.icon.kind is IconKind.FLAG else (_TYRE_PX, _TYRE_PX)
        image = (f'<img src="{_icon_url(cell.icon)}" width="{width}" height="{height}" '
                 'style="vertical-align:middle">')
        content = f"{image}&nbsp;&nbsp;{content}" if content else image
    return content or _EMPTY


def _escape(text: str) -> str:
    """Text as markup. Quotes are left alone: no text a document carries is put in an attribute."""
    return escape(text, quote=False)


def _paragraph(content: str, style: str, align: str = "") -> str:
    """One paragraph of already-escaped content."""
    aligned = f' align="{align}"' if align else ""
    return f'<p{aligned} style="{style}">{content}</p>'


def _icon_url(icon: Icon) -> str:
    """The resource name an icon's image is registered under - ``flag/79``, ``tyre/16``."""
    return f"{icon.kind.value}/{icon.key}"


# --- paint -----------------------------------------------------------------------------------------
@lru_cache(maxsize=None)
def _icon_image(icon: Icon) -> QImage | None:
    """The picture for one icon, or None when there is none to draw. Cached like ``flag_icon``."""
    if icon.kind is IconKind.FLAG:
        path = flag_path(icon.key)
        if path is None:
            return None
        renderer = QSvgRenderer(str(path))
        if not renderer.isValid():
            return None
        image = QImage(*_FLAG_SIZE, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        return image
    pixmap = tyre_pixmap(icon.key, _TYRE_PX)
    return None if pixmap is None else pixmap.toImage()


def _body_font() -> QFont:
    """The app's typeface - the image should read like the app on that machine - at the image's
    own size, never the app's, which follows the user's settings rather than a 1080 px canvas."""
    font = QFont(QGuiApplication.font().family())
    font.setPixelSize(_BODY_PX)
    return font


def _fixed_palette() -> QPalette:
    """What the paint falls back to for any colour the markup does not state."""
    palette = QPalette()
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive,
                  QPalette.ColorGroup.Disabled):
        for role, colour in ((QPalette.ColorRole.Text, _INK), (QPalette.ColorRole.WindowText, _INK),
                             (QPalette.ColorRole.Base, _PAPER), (QPalette.ColorRole.Window, _PAPER),
                             (QPalette.ColorRole.Link, _TONE_COLOURS[Tone.FASTEST])):
            palette.setColor(group, role, QColor(colour))
    return palette
