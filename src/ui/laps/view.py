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
        # A lap another surface asked for consumed by the next showEvent. See show_lap.
        self._pending: tuple[str, int] | None = None

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
        """Land on a freshly-reloaded overview whenever the surface is shown (e.g. after ingest).
        Unless another surface asked for a speficic lap first - see :meth:`show_lap`."""
        super().showEvent(event)
        pending, self._pending = self._pending, None
        if pending is not None:
            self._show_detail(*pending)
            return
        self._show_overview()

    def show_lap(self, session_uid: str, lap_number: int) -> None:
        """Open one lap's detail, from outside this surface (the Sessions detail page).

        The target is recorded *and* navigated to, because the order of the two is not ours to
        rely on. The window switches its stack to this widget and calls here, and a stack switch
        fires ``showEvent`` - which resets to the overview and would silently undo the
        navigation. Stashing the target means it survives whichever happens first, and it is
        cleared on use so a later plain visit still lands on the overview.
        """
        self._pending = (str(session_uid), lap_number)
        self._show_detail(str(session_uid), lap_number)

    def refresh(self) -> None:
        """Re-query the overview if it's the visible page (called after an ingest completes)."""
        if self._stack.currentWidget() is self._overview:
            self._overview.reload()

    def invalidate_caches(self) -> None:
        """Drop derived caches after an ingest/re-ingest changed the stored laps.
        
        Deliberately separate from ``refresh()``, which only touches the *visible* page: the
        canonical track-map cache lives on the detail page and would otherwise suvrive an ingest
        made while another surface was showing, and stay stale until the app restarts
        (PRIORITIES -> ALL). If the detail page happens to be the invisible one, its map is redrawn
        now rather than on the next navigation.
        """
        self._detail.invalidate_layouts()
        if self._stack.currentWidget() is self._detail:
            self._detail.reload()

    def _show_overview(self) -> None:
        self._stack.setCurrentWidget(self._overview)
        self._overview.reload()

    def _show_detail(self, session_uid: str, lap_number: int) -> None:
        self._stack.setCurrentWidget(self._detail)
        self._detail.load(session_uid, lap_number)
