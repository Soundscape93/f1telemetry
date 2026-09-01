"""The sessions surface - a thin container coordinating the overview, detail and deleted pages.

Mirrors ``ui/laps/view.py`` and ``ui/seasons/view.py``: owns a ``QStackedWidget`` of the pages
and wires their navigation signals to page switches. Pages never reference each other - every
hop goes through a signal on this container. Session uids travel through the signals as ``str``
because they are uint64 and an ``int`` signal would overflow.

Two signals leave the surface entirely, and both do so because the window owns what they need.
``sessions_changed`` says "stored session data changed", so the other surfaces can drop what they
derived from it - the same contract ``SeasonsView`` already has, joined rather than reinvented.
``restore_requested`` asks for a job, not a page: re-reading a capture is minutes of work on a
worker thread, and the window owns workers (E1/E2 plan -> Restore orchestration).
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from .deleted_page import DeletedPage
from .detail_page import DetailPage
from .overview_page import OverviewPage


class SessionsView(QWidget):
    """Browse every stored session, drill into one, and manage the ones that were deleted."""

    sessions_changed = Signal()
    lap_requested = Signal(str, int)  # session uid (str, uint64-safe), lap_number
    restore_requested = Signal(str, str)  # session uid (str, uint64-safe), content_hash ("" = pick)

    def __init__(self, session_store, season_store, capture_store=None, lap_store=None,
                 event_store=None, parent=None):
        super().__init__(parent)
        self._overview = OverviewPage(session_store, season_store, 
                                      lap_store=lap_store, event_store=event_store)
        self._detail = DetailPage(session_store, season_store, capture_store=capture_store,
                                   lap_store=lap_store, event_store=event_store)
        self._deleted = DeletedPage(session_store, capture_store=capture_store)

        self._overview.session_requested.connect(self._show_detail)
        self._overview.deleted_requested.connect(self._show_deleted)
        self._detail.overview_requested.connect(self._show_overview)
        self._deleted.overview_requested.connect(self._show_overview)
        self._overview.sessions_changed.connect(self.sessions_changed)
        self._detail.sessions_changed.connect(self.sessions_changed)
        # Not navigation within this surface: opening a lap's telemetry means leaving Sessions
        # entirely, which only the window can do (pages never reference sibling surfaces)
        self._detail.lap_requested.connect(self.lap_requested)
        # Same rule, different reason: the deleted page confirms and chooses the capture on the GUI
        # thread, then hands the work up. Pages don't own workers - the window does.
        self._deleted.restore_requested.connect(self.restore_requested)

        self._stack = QStackedWidget()
        for page in (self._overview, self._detail, self._deleted):
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

    def _show_deleted(self) -> None:
        self._stack.setCurrentWidget(self._deleted)
        self._deleted.reload()
