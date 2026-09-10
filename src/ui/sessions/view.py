"""The sessions surface - a thin container coordinating the overview, detail and deleted pages.

Mirrors ``ui/laps/view.py`` and ``ui/seasons/view.py``: owns a ``QStackedWidget`` of the pages
and wires their navigation signals to page switches. Pages never reference each other - every
hop goes through a signal on this container. Session uids travel through the signals as ``str``
because they are uint64 and an ``int`` signal would overflow.

Three signals leave the surface entirely, and all three do so because the window owns what they
need. ``sessions_changed`` says "stored session data changed", so the other surfaces can drop what
they derived from it - the same contract ``SeasonsView`` already has, joined rather than reinvented.
``restore_requested`` asks for a job, not a page: re-reading a capture is minutes of work on a
worker thread, and the window owns workers (E1/E2 plan -> Restore orchestration). ``season_requested``
comes off the weekend page's back button and lands on the *Seasons* surface, which no page here may
reference.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from ..season_roster import SeasonRosterFiles
from .deleted_page import DeletedPage
from .detail_page import DetailPage
from .league_names import SessionRosters
from .overview_page import OverviewPage
from .weekend_page import WeekendPage


class SessionsView(QWidget):
    """Browse every stored session, drill into one, and manage the ones that were deleted."""

    sessions_changed = Signal()
    lap_requested = Signal(str, int)        # session uid (str, uint64-safe), lap_number
    restore_requested = Signal(str, str)    # session uid (str, uint64-safe), content_hash ("" = pick)
    season_requested = Signal(int)          # the weekend page's back-button - a Seasons page

    def __init__(self, session_store, season_store, capture_store=None, lap_store=None,
                 event_store=None, parent=None):
        super().__init__(parent)
        # One resolver shared by every page, the way ``SeasonsView`` owns one ``SeasonRosterFiles`` 
        # for its own: it caches per paint and each page clears it in ``reload``, so sharing costs
        # nothing and keeps a single answer to "whose roster names this session?" (E1c).
        self._rosters = SessionRosters(season_store, SeasonRosterFiles())
        # A weekend another surface asked for, consumed by the neext showEvent. See show_weekend.
        self._pending: tuple[int, int] | None = None

        self._overview = OverviewPage(session_store, season_store, 
                                     lap_store=lap_store, event_store=event_store,
                                     rosters=self._rosters)
        self._detail = DetailPage(session_store, season_store, capture_store=capture_store,
                                     lap_store=lap_store, event_store=event_store, 
                                    rosters=self._rosters)
        self._deleted = DeletedPage(session_store, capture_store=capture_store)
        self._weekend = WeekendPage(session_store, season_store, 
                                     lap_store=lap_store, event_store=event_store, 
                                     rosters=self._rosters)

        self._overview.session_requested.connect(self._show_detail)
        self._overview.deleted_requested.connect(self._show_deleted)
        self._detail.overview_requested.connect(self._show_overview)
        self._deleted.overview_requested.connect(self._show_overview)
        self._weekend.session_requested.connect(self._show_detail)
        self._overview.sessions_changed.connect(self.sessions_changed)
        self._detail.sessions_changed.connect(self.sessions_changed)
        self._weekend.sessions_changed.connect(self.sessions_changed)
        # Not navigation within this surface: opening a lap's telemetry means leaving Sessions
        # entirely, which only the window can do (pages never reference sibling surfaces)
        self._detail.lap_requested.connect(self.lap_requested)
        # The same rule, and the same reason, for the hop back to Seasons.
        self._weekend.season_requested.connect(self.season_requested)
        # Same rule, different reason: the deleted page confirms and chooses the capture on the GUI
        # thread, then hands the work up. Pages don't own workers - the window does.
        self._deleted.restore_requested.connect(self.restore_requested)

        self._stack = QStackedWidget()
        for page in (self._overview, self._detail, self._deleted, self._weekend):
            self._stack.addWidget(page)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        self._show_overview()

    def showEvent(self, event):
        """Land on a freshly-reloaded overview whenever the surface is shown (e.g. after ingest).
        Unless another surface asked for a specific weekend first - see :meth:`show_weekend`."""
        super().showEvent(event)
        pending, self._pending = self._pending, None
        if pending is not None:
            self._show_weekend(*pending)
            return
        self._show_overview()

    def show_weekend(self, season_id: int, round_number: int) -> None:
        """Open one round's weekend, from outside this surface (a season's calendar).

        The order of the two halves is not ours to rely on: the window switches its stack to this
        widget and calls here, and a stack switch fires ``showEvent`` - which resets to the
        overview and would silently undo the navigation if it arrived second. So the target is
        stashed for a show event that has not happened yet, and navigated to now for one that has.

        The stash is taken **only while this surface is hidden**, which is what keeps it from
        outliving the request. Stashing unconditionally leaves a target nothing consumes - the
        window shows the surface *before* calling, so the show event is already spent - and the
        user's next plain visit to Sessions would silently re-open this weekend instead of the
        overview.
        """
        if not self.isVisible():
            self._pending = (int(season_id), int(round_number))
        self._show_weekend(int(season_id), int(round_number))

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

    def _show_weekend(self, season_id: int, round_number: int) -> None:
        self._stack.setCurrentWidget(self._weekend)
        self._weekend.load(season_id, round_number)

