"""The laps surface - a thin containter coordinationg the overview and detail pages.

Mirrors ``ui/seasons/view.py``: owns a ``QStackedWidget`` of the two pages and wires their
navigation signals to page switches. The overview lists stored laps as foldable per-session cards;
opening a lap shows its detail. Session uids travel trough the signals as ``str``(they're uint64,
so an ``int``signal would overflow).
"""

from __future__ import annotations

from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from .detail_page import DetailPage
from .overview_page import OverviewPage


class LapsView(QWidget):
    """Browse stored laps and drill into one lap's detail, all in one widget."""

    def __init__(self, session_store, lap_store, parent=None):
        super().__init__(parent)
        self._overview = OverviewPage(session_store, lap_store)
        self._detail = DetailPage(session_store, lap_store)

        self._overview.lap_requested.connect(self._show_detail)
        self._detail.overview_requested.connect(self._show_overview)

        self._stack = QStackedWidget()
        for page in (self._overview, self._detail):
            self._stack.addWidget(page)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        self._show_overview()

    def showEvent(self, event):
        """Land on a freshly-reloaded overview whenever the surface is shown (e.g. after ingest)."""
        super().showEvent(event)
        self._show_overview()

    def refresh(self) -> None:
        """Re-query the overview if it's the visible page (called after an ingest completes)."""
        if self._stack.currentWidget() is self._overview:
            self._overview.reload()

    def _show_overview(self) -> None:
        self._stack.setCurrentWidget(self._overview)
        self._overview.reload()

    def _show_detail(self, session_uid: str, lap_number: int) -> None:
        self._stack.setCurrentWidget(self._detail)
        self._detail.load(session_uid, lap_number)
