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
