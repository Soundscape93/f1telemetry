"""The sessions surface - a thin container coordinating the overview and detail pages.

Mirrors ``ui/laps/view.py`` and ``ui/seasons/view.py``: owns a ``QStackedWidget`` of the pages
and wires their navigation signals to page switches. Pages never reference each other - every
hop goes through a signal on this container. Session uids travel through the signals as ``str``
because they are uint64 and an ``int`` signal would overflow.

``sessions_changed`` is not a navigation signal: it says "stored session data changed", so the
window can tell the other surfaces to drop what they derived from it - the same contract
``SeasonsView`` already has, joined rather than reinvented.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from .detail_page import DetailPage
from .overview_page import OverviewPage


class SessionsView(QWidget):
    """Browse every stored session and drill into one session's classification."""

    sessions_changed = Signal()

    def __init__(self, session_store, season_store, capture_store=None, lap_store=None,
                 parent=None):
        super().__init__(parent)
        self._overview = OverviewPage(session_store, season_store, lap_store=lap_store)
        self._detail = DetailPage(session_store, season_store,
                                  capture_store=capture_store, lap_store=lap_store)

        self._overview.session_requested.connect(self._show_detail)
        self._detail.overview_requested.connect(self._show_overview)
        self._overview.sessions_changed.connect(self.sessions_changed)
        self._detail.sessions_changed.connect(self.sessions_changed)

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
        """Re-query whichever page is visible, after stored sessions changed."""
        self._stack.currentWidget().reload()

    def _show_overview(self) -> None:
        self._stack.setCurrentWidget(self._overview)
        self._overview.reload()

    def _show_detail(self, session_uid: str) -> None:
        self._stack.setCurrentWidget(self._detail)
        self._detail.load(session_uid)
