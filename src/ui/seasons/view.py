"""The seasons surface - a thin container coordinating the four seasons pages.

`SeasonsView` owns a `QStackedWidget` of page widgets (overview, create, detail, weekend) and
wires their navigation signals to page switches. Each page owns its own widgets, route state, and
data operations; this coordinator only decides which page is visible. All navigation stays inside
this widget, and inside the one application window - nothing opens a new window.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from ..season_roster import SeasonRosterFiles
from .create_page import CreatePage
from .detail_page import DetailPage
from .edit_calendar_page import EditCalendarPage
from .overview_page import OverviewPage
from .weekend_page import WeekendPage


class SeasonsView(QWidget):
    """Browse / create / inspect seasons and drill into weekends, all in one widget."""

    # Not a navigation signal: it says "stored session data changed", so the window can tell the
    # other surfaces to drop what they derived from it. Re-emitted from the weekend page, which
    # owns the only delete action that removes stored sessions.
    sessions_changed = Signal()

    def __init__(self, season_store, session_store, lap_store=None, parent=None) -> None:
        """Initialize the seasons view and wire page navigation signals."""
        super().__init__(parent)
        self._season_rosters = SeasonRosterFiles()

        self._overview = OverviewPage(season_store)
        self._create = CreatePage(season_store)
        self._detail = DetailPage(season_store, session_store, self._season_rosters)
        self._weekend = WeekendPage(season_store, session_store, self._season_rosters, lap_store=lap_store)
        self._edit_calendar = EditCalendarPage(season_store)

        self._overview.create_requested.connect(self._show_create)
        self._overview.season_requested.connect(self._show_detail)
        self._create.season_requested.connect(self._show_detail)
        self._create.cancelled.connect(self._show_overview)
        self._detail.overview_requested.connect(self._show_overview)
        self._detail.weekend_requested.connect(self._show_weekend)
        self._weekend.detail_requested.connect(self._show_detail)
        self._weekend.overview_requested.connect(self._show_overview)
        self._weekend.sessions_changed.connect(self.sessions_changed)
        self._detail.edit_calendar_requested.connect(self._show_edit_calendar)
        self._edit_calendar.saved.connect(self._show_detail)
        self._edit_calendar.cancelled.connect(self._show_detail)

        self._stack = QStackedWidget()
        for page in (self._overview, self._create, self._detail, self._weekend,
                     self._edit_calendar):
            self._stack.addWidget(page)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        self._show_overview()

    def showEvent(self, event) -> None:
        """Refresh the overview when the widget is shown, in case a capture was ingested."""
        super().showEvent(event)
        self._show_overview()

    def refresh(self) -> None:
        """Re-query whatever page is showing."""
        page = self._stack.currentWidget()
        if page is self._weekend:
            self._weekend.reload()
        elif page is self._detail:
            self._detail.reload()
        elif page is self._overview:
            self._overview.reload()

    # --- page switching ------------------------------------------------
    #
    # Each _show_* switches the page first, then populates it. A page's load/reload may discover
    # its target has vanished and emit a fallback navigation signal, which re-navigates last and
    # wins (Qt signals run synchronously on this thread).

    def _show_overview(self) -> None:
        """Switch to the overview page and refresh its contents."""
        self._stack.setCurrentWidget(self._overview)
        self._overview.reload()

    def _show_create(self) -> None:
        """Switch to the create page and reset the form."""
        self._stack.setCurrentWidget(self._create)
        self._create.reset()

    def _show_detail(self, season_id: int) -> None:
        """Switch to the detail page for a season."""
        self._stack.setCurrentWidget(self._detail)
        self._detail.load(season_id)

    def _show_weekend(self, season_id: int, round_number: int) -> None:
        """Switch to the weekend page for a given season/round."""
        self._stack.setCurrentWidget(self._weekend)
        self._weekend.load(season_id, round_number)

    def _show_edit_calendar(self, season_id: int) -> None:
        """Switch to the calendar editor for a season."""
        self._stack.setCurrentWidget(self._edit_calendar)
        self._edit_calendar.load(season_id)
