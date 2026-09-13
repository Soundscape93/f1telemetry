"""The sessions overview - foldable per-session cards over every stored session.

One collapsible card per captured session, newest first: the header carries the track and
session label, a delete action, and a muted recorded-time / driver-count line. Expanding a card
reveals a single compact summary row - session, leader, fastest lap, weather, AI difficulty -
and double-clicking the title opens the session's detail page.

The page is thin on purpose. *Which* cards exist and in what order is ``weekend_view``'s rule and
*what a card says* is ``components.session_card``'s widget; both are shared with the
weekend-filtered overview, which owns different chrome over the same spine (DECISIONS -> UI).
What is left here is this page's own chrome: the heading, the "Deleted sessions (n)" button, the
track/session filter, and remembering which cards the user opened.

Mirrors ``ui/laps/overview_page.py`` on purpose: same card idiom, same expansion set surviving a
re-filter, same A4b rules (no font-bearing stylesheet, ``apply_bold`` / ``MUTED_TEXT_QSS``). The
difference is what a card holds - the laps overview lists a session's laps and reads LapStore,
this summarises the session itself and never does, so the whole page costs one query.
"""
from __future__ import annotations

from functools import partial

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget
)

from ..components import (
    CardAction,
    SessionCard,
    clear_layout,
    confirm_and_delete,
    display_name_fn,
)
from ..season_roster import SeasonRosterFiles
from ..style import MUTED_TEXT_QSS, apply_heading
from .league_names import SessionRosters
from .weekend_view import SessionRow, overview_rows


class OverviewPage(QWidget):
    """Foldable per-session summary cards with a track / session filter."""

    session_requested = Signal(str)  # session_uid (str, uint64-safe)
    sessions_changed = Signal()  # a delete removed stored data - other surfaces re-read
    deleted_requested = Signal()  # open the deleted-sessions manager (the container hops)

    def __init__(self, session_store, season_store, lap_store=None,
                 event_store=None, rosters=None, parent=None):
        super().__init__(parent)
        self._sessions = session_store
        self._seasons = season_store
        self._lap_store = lap_store
        self._event_store = event_store         # deleting a session takes its penalties + passes too
        # A league member who raced with online-name sharing off captured as "Player"; this resolves
        # that through the season's saved roster (E1c). Built here when the container did not inject
        # one, so the names are right by default rather than only when a caller remembers to wire it.
        self._rosters = rosters or SessionRosters(season_store, SeasonRosterFiles())
        self._expanded: set[str] = set()  # uids whose card is open (survives a re-filter)
        self._query =  ""

        outer = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("Sessions")
        apply_heading(title, size_px=20)
        header.addWidget(title)
        header.addStretch(1)
        # Always shown, cound and all - it is the only route to the manager and "(0)" is the
        # honest answer rather than a button that appears and disappears.
        self._deleted = QPushButton()
        self._deleted.setToolTip(
            "Sessions you deleted: what was removed, and how to bring one back")
        self._deleted.clicked.connect(self.deleted_requested.emit)
        header.addWidget(self._deleted)
        outer.addLayout(header)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter by track or session")
        self._search.textChanged.connect(self._on_search)
        outer.addWidget(self._search)

        self._body = QVBoxLayout()
        host = QWidget()
        host.setLayout(self._body)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

    # --- filters ---------------------------------------------------------
    def _on_search(self, text: str) -> None:
        self._query = text.strip().lower()
        self.reload()

    # --- build -----------------------------------------------------------
    def reload(self) -> None:
        """Rebuild the cards from the session store, honouring the current filter."""
        clear_layout(self._body)
        # Re-read the assignments and roster files for this paint: assigning a session on the
        # Seasons surface, or hand-editing a roster JSON, has to show up without a restart.
        self._rosters.invalidate()
        self._deleted.setText(f"Deleted sessions ({len(self._sessions.deleted_sessions())})")
        rows = overview_rows(self._sessions.list_sessions(), self._query)
        for row in rows:
            self._body.addWidget(self._card(row))
        if not rows:
            empty = QLabel(self._empty_message())
            empty.setStyleSheet(MUTED_TEXT_QSS)
            self._body.addWidget(empty)
        self._body.addStretch(1)

    def _empty_message(self) -> str:
        if self._query:
            return "No sessions match the filter."
        return "No sessions stored yet - record one, or import a capture from Help."

    def _card(self, row: SessionRow) -> QWidget:
        """The shared card, titled with the track as well as the slot: this list spans weekends."""
        uid = str(row.session.session_uid)
        card = SessionCard(
            row.session,
            title=f"{row.track} \u2014 {row.label}",
            label=row.label,
            # Resolved per card, off the cached roster: the captured name wins whenever it is not
            # generic, so this changes the sessions that actually need it.
            name_of=display_name_fn(self._rosters.roster_for_session(row.session.session_uid)),
            actions=(CardAction(
                "Delete…",
                "Delete this session's stored results (the recording is kept)",
                partial(self._delete, int(row.session.session_uid)),  
            ),),
            expanded=uid in self._expanded,
        )
        card.activated.connect(partial(self.session_requested.emit, uid))
        card.toggled.connect(partial(self._remember, uid))
        return card

    def _remember(self, uid: str, expanded: bool) -> None:
        """Keep a card's fold state, so a re-filter doesn't close what the user opened."""
        if expanded:
            self._expanded.add(uid)
        else:
            self._expanded.discard(uid)

    def _delete(self, session_uid: int) -> None:
        """Delete through the shared guard, then tell the window and re-query.

        A refusal or a cancel changes nothing, so neither needs a reload - and the refusal
        message (which names the season and round) has already been shown by the shared helper.
        """
        if not confirm_and_delete(self, session_uid, self._sessions, self._seasons,
                                  lap_store=self._lap_store, event_store=self._event_store):
            return
        self.sessions_changed.emit()
        self.reload()
