"""The seasons surface - a thin container coordinating the four seasons pages.

`SeasonsView` owns a `QStackedWidget` of page widgets (overview, create, detail, weekend) and
wires their navigation signals to page switches. Each page owns its own widgets, route state, and
data operations; this coordinator only decides which page is visible.

Navigation stays inside this widget, and inside the one application window, with one exception in
each direction. Activating a round no longer opens the weekend page here: `weekend_requested` is
re-emitted for the window, which routes it to the *Sessions* surface's weekend-filtered overview
(E1d - the Sessions surface is where sessions belong). And `show_season` is how the window brings
navigation the other way, back from there - a season, never a round, since the Sessions surface now
owns round assignment too.

The round-centric `weekend` page below is **no longer reachable**. Nothing routes to it as of the
session-centric assignment branch, and the retirement branch deletes it; it is left in place for
exactly one branch rather than removed here, where the check that no caller remains belongs
(PRIORITIES -> E1d).
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
    # Navigation, but off this surface: a round opens the Sessions surface filtered to its
    # weekend, and only the window can switch surfaces (E1d).
    weekend_requested = Signal(int, int)  # season_id, round_number

    def __init__(self, season_store, session_store, lap_store=None,
                 event_store=None, parent=None) -> None:
        """Initialize the seasons view and wire page navigation signals."""
        super().__init__(parent)
        self._season_rosters = SeasonRosterFiles()
        # A season another surface asked for, consumed by the next showEvent. See show_season.
        self._pending: int | None = None

        self._overview = OverviewPage(season_store)
        self._create = CreatePage(season_store)
        self._detail = DetailPage(season_store, session_store, self._season_rosters)
        self._weekend = WeekendPage(season_store, session_store, self._season_rosters,
                                     lap_store=lap_store, event_store=event_store)
        self._edit_calendar = EditCalendarPage(season_store)

        self._overview.create_requested.connect(self._show_create)
        self._overview.season_requested.connect(self._show_detail)
        self._create.season_requested.connect(self._show_detail)
        self._create.cancelled.connect(self._show_overview)
        self._detail.overview_requested.connect(self._show_overview)
        self._weekend.detail_requested.connect(self._show_detail)
        self._weekend.overview_requested.connect(self._show_overview)
        # Straight back out to the window: the calendar's round opens the Sessions surface's
        # weekend-filtered overview, which is now also where the round's sessions are assigned.
        # Nothing reaches the page below any more - see the docstring.
        self._detail.weekend_requested.connect(self.weekend_requested)
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
        """Refresh the overview when the widget is shown, in case a capture was ingested.
        Unless another surface asked for a specific season first - see :meth:`show_season`."""
        super().showEvent(event)
        pending, self._pending = self._pending, None
        if pending is not None:
            self._show_detail(pending)
            return
        self._show_overview()

    def show_season(self, season_id: int) -> None:
        """Open one season's detail page from outside this surface.

        The order of the two halves is not ours to rely on: the window switches its stack to this
        widget and calls here, and a stack switch fires ``showEvent`` - which resets to the
        overview and would silently undo the navigation if it arrived second. So the target is
        stashed for a show event that has not happened yet, and navigated to now for one that has.
        The stash is taken **only while this surface is hidden**, or it would outlive the request
        and hijack the user's next plain visit to Seasons.

        The one caller is the Sessions weekend page's back button, which wants the season. The
        ``round_number`` this used to take existed only for that page's temporary hop back here to
        assign, and went with it when assignment moved (PRIORITIES -> E1d).
        """
        if not self.isVisible():
            self._pending = int(season_id)
        self._show_detail(int(season_id))

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
