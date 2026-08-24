"""Pure Qt table/layout primitives shared across views.

These are view-agnostic building blocks - read-only cells, common table styling, height
fitting, and layout clearing - so every surface that renders a table (seasons, sessions,
laps, ...) styles and sizes it the same way.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..style import apply_bold


def cell(text: str) -> QTableWidgetItem:
    """Return a read-only table cell with the given text."""
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    return item


def tidy_table(table: QTableWidget) -> None:
    """Apply common table styling."""
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)


def clear_layout(layout: QVBoxLayout) -> None:
    """Remove all widgets from a layout and delete them."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


def fit_table_height(table: QTableWidget, max_height: int | None = None) -> None:
    """Freeze a table's height to show all rows, or to ``max_height`` if that is shorter.

    Uncapped, the table never scrolls: it is sized to its content and whatever contains it does
    the scrolling. Capped, a table longer than the ceiling keeps its own scrollbar and its header
    stays pinned - which is what a height-capped box wants.

    Leaving the height unset instead is not the same thing and does not work: a ``QTableWidget``
    reports a size hint far smaller than its content, so in a vertical layout it collapses to a
    row or two rather than filling the space available to it. A maximum on the container caps a
    tall row; it never keeps a short one tall.
    """
    height = table.horizontalHeader().height() + 2 * table.frameWidth()
    for i in range(table.rowCount()):
        height += table.rowHeight(i)
    if max_height is not None and height > max_height:
        table.setFixedHeight(max_height)     # keeps ScrollBarAsNeeded, so the table scrolls itself
        return
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.setFixedHeight(height)


def build_kv_table(rows: list[tuple[str, str | None]]) -> QTableWidget:
    """A read-only key/value (2-column) table with the bold section header rows.
    
    Each row is ``(label, value)``; a row whose ``value``is ``None`` is a section header - the
    label is bolded and spans both columns. Values are right-aligned. Shared by the lap damage and
    setup panels (and any future two-column readout), styled and sized like every other table here.
    """
    table = QTableWidget(len(rows), 2)
    table.horizontalHeader().setVisible(False)
    tidy_table(table)
    for i, (label, value) in enumerate(rows):
        if value is None:               # section header
            head = cell(label)
            font = head.font()
            font.setBold(True)
            head.setFont(font)
            table.setItem(i, 0, head)
            table.setSpan(i, 0, 1, 2)
        else:
            table.setItem(i, 0, cell(label))
            val = cell(value)
            val.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(i, 1, val)
    fit_table_height(table)
    return table


def build_pair_grid(rows: list[tuple[tuple[str, object], tuple[str, object]]]) -> QWidget:
    """Two labelled read-outs per row, centred, with a thin rule under each row.

    Each row is ``((left_label, left_value), (right_label, right_value))``; a value is either a
    string or a ready-made widget (so a caller can pass a coloured label or an icon). Every cell
    renders its label bold above its value, both centred.

    Built from plain widgets in a ``QGridLayout`` rather than a ``QTableWidget`` on purpose. The
    row rules would otherwise need ``QTableWidget::item { border-bottom: ... }``, and setting
    *any* stylesheet on a widget hands its painting to ``QStyleSheetStyle``, which caches a
    palette at apply time - the A4 freeze (see ``ui/style``). A stylesheet that only sets a border
    would sail past ``test_styles.py`` and still freeze the cell text on a live theme switch.
    ``QFrame.HLine`` separators cost nothing and follow the palette natively.
    """
    host = QWidget()
    grid = QGridLayout(host)
    grid.setContentsMargins(4, 2, 4, 2)
    grid.setHorizontalSpacing(12)
    grid.setVerticalSpacing(2)
    grid.setColumnStretch(0, 1)
    grid.setColumnStretch(1, 1)

    for index, (left, right) in enumerate(rows):
        grid.addWidget(_labelled_cell(*left), index * 2, 0)
        grid.addWidget(_labelled_cell(*right), index * 2, 1)
        rule = QFrame()
        rule.setFrameShape(QFrame.Shape.HLine)
        rule.setFrameShadow(QFrame.Shadow.Sunken)
        grid.addWidget(rule, index * 2 + 1, 0, 1, 2)
    return host


def _labelled_cell(label: str, value: object) -> QWidget:
    """One read-out: a bold caption above its value, both centred."""
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 4, 0, 6)
    layout.setSpacing(2)

    caption = QLabel(label)
    apply_bold(caption)
    caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(caption)

    if isinstance(value, QWidget):
        layout.addWidget(value, alignment=Qt.AlignmentFlag.AlignCenter)
    else:
        text = QLabel(str(value))
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(text)
    return box


def fit_columns(table: QTableWidget, stretch: set[int]) -> None:
    """Size every column to its contents except ``stretch``, which absorb the spare width.

    ``tidy_table`` stretches all columns equally, so a three-character PTS column gets exactly as
    much room as a driver's full name and the name is the one that truncates. Naming the few
    columns that should take the slack keeps the numbers narrow and the text readable.
    """
    header = table.horizontalHeader()
    for column in range(header.count()):
        mode = (QHeaderView.ResizeMode.Stretch if column in stretch
                else QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(column, mode)
