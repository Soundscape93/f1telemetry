"""Pure Qt table/layout primitives shared across views.

These are view-agnostic building blocks - read-only cells, common table styling, height
fitting, and layout clearing - so every surface that renders a table (seasons, sessions,
laps, ...) styles and sizes it the same way.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


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


def fit_table_height(table: QTableWidget) -> None:
    """Freeze a table's height to show all rows."""
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    height = table.horizontalHeader().height() + 2 * table.frameWidth()
    for i in range(table.rowCount()):
        height += table.rowHeight(i)
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
