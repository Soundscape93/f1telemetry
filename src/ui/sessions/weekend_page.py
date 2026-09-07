"""The weekend-filtered sessions overview - one round's weekend, in running order.

Where a season's calendar lands (E1d): double-clicking a round opens *this*, not the round-centric
weekend page, because the Sessions surface is where sessions belong. Same spine as the plain
overview - ``weekend_view`` decides the rows, ``components.session_card`` renders them - and only
the chrome differs: a round header instead of a heading, no deleted-sessions button and no filter
(the weekend *is* the filter), and cards open on their summary line rather than folded shut.

**The full classifications are the weekend's races', not every card's.** A table per session was
height without an answer - a nine-session sprint weekend opened as nine full grids, and what a
practice card needs to say is already its summary line. So the races get one each, side by side
beneath the cards in the half-width boxes the session detail page reads in. Which sessions earn
one is ``weekend_view.race_rows``, not a rule this page keeps.

**It shows the weekend's stored sessions, not the round's assigned ones**, and the two are
deliberately not the same list. The round-centric page renders ``rounds_with_results``, so an
attempt nobody assigned is invisible there; filtering stored sessions by ``weekend_link_id`` shows
every attempt at every slot, which is what a weekend actually held. In this database that is one
visible row: weekend `3602002284` stores eight sessions and has seven assigned, the odd one out
being the first of Practice 2's two attempts.

**A round with nothing assigned has no weekend**, because the only link from a round to a weekend
runs through its assigned sessions - and that is 88 of this database's 96 rounds, so the empty
state is the common case and has to read as deliberate. Guessing from the round's track was
rejected: a track is not a weekend (Suzuka has three here), so it would show a weekend the round
has nothing to do with.

**Names resolve through ``SessionRosters``**, which gates on ``ROSTER_SEASON_MODES`` - LEAGUE
*and* GRAND_PRIX. This database's only real league is a GRAND_PRIX season, so this page names it
where the round-centric page it replaces shows raw captured names (DECISIONS -> UI, E1c).

**One deliberate scaffold lives here.** Assignment is still written only by the round-centric
page, so this one carries an "Assign captures…" button that hops back to it through the window.
It keeps assignment working with no unreachable code and no broken intermediate state; the
session-centric assignment branch deletes the button and the retirement branch deletes the page
(PRIORITIES -> E1d).
"""
from __future__ import annotations

from collections import Counter
from functools import partial

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget
)

from ...protocol.reference import track_name
from ..components import (
    CardAction,
    SessionCard,
    build_classification_table,
    clear_layout,
    confirm_and_delete,
    display_name_fn,
    panel_box,
)
from ..formatting import recorded_label
from ..season_roster import SeasonRosterFiles
from ..style import MUTED_TEXT_QSS, apply_heading
from .league_names import SessionRosters
from .weekend_view import SessionRow, SlotRow, race_rows, weekend_of, weekend_rows


class WeekendPage(QWidget):
    """One round's weekend as session cards, with its uncaptured slots kept in running order.

    ``load(season_id, round_number)`` populates the page. Emits ``season_requested(season_id)``
    for the back button and when the round has vanished underneath it.
    """

    session_requested = Signal(str)     # session_uid (str, uint64-safe)
    sessions_changed = Signal()         # a delete removed stored data - other surfaces re-read
    season_requested = Signal(int)      # leave Sessions fo this season's detail page
    # TEMPORARY (see module docstring): assignment still lives on the round-centric page.
    assign_requested = Signal(int, int)  # season_id, round_number

    def __init__(self, session_store, season_store, lap_store=None,
                 event_store=None, rosters=None, parent=None) -> None:
        super().__init__(parent)
        self._sessions = session_store
        self._seasons = season_store
        self._lap_store = lap_store
        self._event_store = event_store         # deleting a session takes its penalties + passes too
        self._rosters = rosters or SessionRosters(season_store, SeasonRosterFiles())
        self._season_id: int | None = None
        self._round_number: int | None = None
        # Cards open by default here, unlike the plain overview: this page replaces one that
        # showed every classification table outright, and a weekend is a handful of sessions
        # rather than the whole store. So the page remeberes what was *closed*.
        self._collapsed: set[str] = set()

        outer = QVBoxLayout(self)

        header = QHBoxLayout()
        back = QPushButton("← Season")
        back.clicked.connect(self._on_back)
        header.addWidget(back)
        header.addSpacing(12)
        self._title = QLabel()
        apply_heading(self._title, size_px=20)
        header.addWidget(self._title)
        header.addStretch(1)
        self._assign = QPushButton("Assign captures…")
        self._assign.setToolTip(
            "Assign or unassign this round's captures on the season's weekend page")
        self._assign.clicked.connect(self._on_assign)
        header.addWidget(self._assign)
        outer.addLayout(header)

        self._body = QVBoxLayout()
        host = QWidget()
        host.setLayout(self._body)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

    # --- navigation ------------------------------------------------------
    def _on_back(self) -> None:
        """Return to the season this round belongs to (on the Seasons surface)."""
        if self._season_id is not None:
            self.season_requested.emit(self._season_id)

    def _on_assign(self) -> None:
        """Hop to the round-centrig weekend page to assign captures. Temporary - see module docstring."""
        if self._season_id is not None and self._round_number is not None:
            self.assign_requested.emit(self._season_id, self._round_number)

    # --- build -----------------------------------------------------------
    def load(self, season_id: int, round_number: int) -> None:
        """Populate the page for one round's weekend."""
        self._season_id = int(season_id)
        self._round_number = int(round_number)
        self.reload()

    def reload(self) -> None:
        """Re-query the round, resolve its weekend, and rebuild the rows.

        Deliberately never calls ``rounds_with_results``: that hydrates every session in the
        season - 37 in this database - and it is not needed here. The round's number and track
        come off the season's own calendar, its assigned uids off one assignments read, and the
        weekend's sessions out of the single ``list_sessions`` query the rows need anyway (E1c).
        """
        clear_layout(self._body)
        # Assigning a session, or hand-editing a roster JSON, has to show up on the next paint.
        self._rosters.invalidate()
        round = self._round()
        if round is None:
            # The season or the round went away underneath us. The season detail page bounces on
            # to the seasons overview if the season is the part that vanished.
            if self._season_id is not None:
                self.season_requested.emit(self._season_id)
            return
        self._title.setText(f"Round {round.round_number} \u2014 {track_name(round.track_id)}")

        all_sessions = self._sessions.list_sessions()
        assigned = {uid for number, uid
                     in self._seasons.assignments_for_season(self._season_id)
                     if number == self._round_number}
        weekend = weekend_of([s for s in all_sessions if s.session_uid in assigned])
        rows = ([] if weekend is None else
                 weekend_rows([s for s in all_sessions if s.weekend_link_id == weekend]))
        for row in rows:
            self._body.addWidget(
                self._card(row) if isinstance(row, SessionRow) else self._slot_row(row))
        races = self._race_row(rows)
        if races is not None:
            self._body.addWidget(races)
        if not rows:
            # The only way to have no rows: nothing is assigned, so there is no weekend to
            # resolve. A weekend that resolved always has at lest the session that named it.
            empty = QLabel(
                f"No sessions are assigned to round {round.round_number} yet, so there is no "
                "weekend to show. Use “Assign captures…” to put this round's captures in it.")
            empty.setWordWrap(True)
            empty.setStyleSheet(MUTED_TEXT_QSS)
            self._body.addWidget(empty)
        self._body.addStretch(1)

    def _round(self):
        """This page's round off the season's calendar, or None if either has vanished."""
        if self._season_id is None or self._round_number is None:
            return None
        season = self._seasons.get_season(self._season_id)
        rounds = season.rounds if season is not None else ()
        return next((r for r in rounds if r.round_number == self._round_number), None)

    def _card(self, row: SessionRow) -> QWidget:
        """The shared card, titled with the slot alone - the track is in the page header.

        Two attempts at one slot are two of these in a row, identical but for the recorded time on
        the meta line. Nothing numbers them: which one counts is a judgement about the session
        (core invariant #5).
        """
        uid = str(row.session.session_uid)
        name_of = display_name_fn(self._rosters.roster_for_session(row.session.session_uid))
        card = SessionCard(
            row.session,
            title=row.label,
            label=row.label,
            name_of=name_of,
            actions=(CardAction(
                "Delete…",
                "Delete this session's stored results (the recording is kept)",
                partial(self._delete, int(row.session.session_uid)),  
            ),),
            expanded=uid not in self._collapsed,
        )
        card.activated.connect(partial(self.session_requested.emit, uid))
        card.toggled.connect(partial(self._remember, uid))
        return card

    def _race_row(self, rows) -> QWidget | None:
        """The weekend's race classifications, side by side beneath the session cards.

        None while no race is captured, so a weekend still being driven simply does not have this
        yet. A sprint weekend fills both halves - the Sprint Race scores points too - and a plain
        weekend leaves the second half empty rather than stretching one table across the page: a
        classification is a narrow thing, and full width makes it harder to read, not easier.

        A race driven twice gets a box each, in the order they were driven, and the recorded time
        joins the title of *that* race only - the app numbers no attempt (core invariant #5).
        """
        races = race_rows(rows)
        if not races:
            return None
        attempts = Counter(row.label for row in races)
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 12, 0, 0)
        for row in races:
            title = f"Final classification · {row.label}"
            if attempts[row.label] > 1:
                title = f"{title} · {recorded_label(row.session.recorded_at)}"
            name_of = display_name_fn(self._rosters.roster_for_session(row.session.session_uid))
            # ``is_sprint_race`` comes off the slot, not the session: both races report RACE, and
            # only the position tells them apart (invariant #5). It picks the sprint points table
            # for a reconstructed result, so the two boxes cannot score the same race twice over.
            layout.addWidget(panel_box(title, build_classification_table(
                row.session, name_of, is_sprint_race=row.slot.is_sprint_race), fill=True), 1)
        if len(races) == 1:
            layout.addStretch(1)    # one race stays half-width rather than spanning the page
        return host

    @staticmethod
    def _slot_row(row: SlotRow) -> QWidget:
        """A greyed placeholder for a weekend position holding no session.

        Keeps the Sprint Race / Race (and everything around them) in their real running order, so
        an empty spot reads as intentional rather than as something the filter lost. Whether it
        says Skipped or not-captured-yet is ``weekend_view``'s rule, not this page's.
        """
        label = QLabel(f"{row.label}  \u2014  {row.state.value}")
        label.setStyleSheet(f"{MUTED_TEXT_QSS} font-style: italic; padding: 4px 0;")
        return label

    def _remember(self, uid: str, expanded: bool) -> None:
        """Keep a card's fold state across a re-query."""
        if expanded:
            self._collapsed.discard(uid)
        else:
            self._collapsed.add(uid)

    def _delete(self, session_uid: int) -> None:
        """Delete through the shared guard, then tell the window and re-query.

        The guard refuses a session assigned to a round, naming it - so on this page it refuses
        most of what it is shown, which is the point: the unassigned attempt beside it is exactly
        what a user comes here to clear up.
        """
        if not confirm_and_delete(self, session_uid, self._sessions, self._seasons,
                                  lap_store=self._lap_store, event_store=self._event_store):
            return
        self.sessions_changed.emit()
        self.reload()
