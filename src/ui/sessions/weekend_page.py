"""The weekend-filtered sessions overview - one round's weekend, in running order.

Where a season's calendar lands (E1d): double-clicking a round opens *this*, because the Sessions
surface is where sessions belong. Same spine as the plain overview - ``weekend_view`` decides the
rows, ``components.session_card`` renders them - and only the chrome differs: a round header
instead of a heading, no deleted-sessions button and no filter (the weekend *is* the filter), and
cards open on their summary line rather than folded shut.

**The full classifications are the weekend's races', not every card's.** A table per session was
height without an answer - a nine-session sprint weekend opened as nine full grids, and what a
practice card needs to say is already its summary line. So the races get one each, side by side
beneath the cards in the half-width boxes the session detail page reads in. Which sessions earn
one is ``weekend_view.race_rows``, not a rule this page keeps.

**It shows the weekend's stored sessions, not the round's assigned ones**, and the two are
deliberately not the same list. The round's assigned sessions (``rounds_with_results``) leave out
an attempt nobody assigned; filtering stored sessions by ``weekend_link_id`` shows every attempt at
every slot, which is what a weekend actually held. In this database that is one visible row:
weekend `3602002284` stores eight sessions and has seven assigned, the odd one out being the first
of Practice 2's two attempts.

**So a card has to say which of the two it is.** Only the rows that are *not* in this round carry a
note - "not assigned", or the round they are in - because the ordinary row is the assigned one and
marking 52 of this database's 64 rows would be noise. The action beside it says the same thing a
second way: Unassign, Assign, or Move here.

**This page is the writer of ``season_assignments``** (E1b): assign, unassign and move all happen
here, and nowhere else since the round-centric page was retired (v0.11.0). A write is followed by
the automatic proposal - the rest of the weekend the assigned session belongs to, offered once and
declinable (DECISIONS -> Storage). What may be proposed is ``assignment``, a Qt-free rule module
with its own tests; this page only asks the question and performs the writes.

**A round with nothing assigned has no weekend**, because the only link from a round to a weekend
runs through its assigned sessions - and that is 87 of this database's 96 rounds, so the empty
state is the common case and has to read as deliberate. Guessing from the round's track was
rejected: a track is not a weekend (Suzuka has three here), so it would show a weekend the round
has nothing to do with. ``AssignDialog`` is the way out of that state, and it lists sessions
rather than a weekend precisely so it works when there is nothing to draw.

**Names resolve through ``SessionRosters``**, which gates on ``ROSTER_SEASON_MODES`` - LEAGUE
*and* GRAND_PRIX. This database's only real league is a GRAND_PRIX season, so this page names it
where the round-centric page it replaced showed raw captured names (DECISIONS -> UI, E1c).
"""
from __future__ import annotations

from collections import Counter
from functools import partial

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget
)

from ...domain.season import Season
from ...protocol.reference import track_name
from ..components import (
    CardAction,
    SessionCard,
    build_classification_table,
    clear_layout,
    confirm_and_delete,
    display_name_fn,
    panel_box,
    season_phrase,
)
from ..formatting import recorded_label
from ..season_roster import SeasonRosterFiles
from ..style import MUTED_TEXT_QSS, apply_heading
from .assign_dialog import AssignDialog
from .assignment import weekend_proposal
from .league_names import SessionRosters
from .weekend_view import SessionRow, SlotRow, race_rows, weekend_of, weekend_rows


class WeekendPage(QWidget):
    """One round's weekend as session cards, with its uncaptured slots kept in running order.

    ``load(season_id, round_number)`` populates the page. Emits ``season_requested(season_id)``
    for the back button and when the round has vanished underneath it.
    """

    session_requested = Signal(str)     # session_uid (str, uint64-safe)
    sessions_changed = Signal()         # a delete removed stored data - other surfaces re-read
    season_requested = Signal(int)      # leave Sessions for this season's detail page

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

        # Read once per paint and used by the card markers. Not a cache: ``reload`` rebuilds both
        # every time.
        self._placed: dict[int, tuple[int, int]] = {}  # session_uid -> (season_id, round_number)
        self._seasons_by_id: dict[int, Season] = {}

        # Cards open by default here, unlike the plain overview: this page replaced one that
        # showed every classification table outright, and a weekend is a handful of sessions
        # rather than the whole store. So the page remembers what was *closed*.
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
        # A local, like ``back`` above: nothing outside this method touches it, and an attribute
        # named ``_assign`` would shadow the method of that name.
        assign = QPushButton("Assign sessions…")
        assign.setToolTip(
            "Put a stored session in this round - the way into a round with no weekend yet")
        assign.clicked.connect(self._on_assign)
        header.addWidget(assign)
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
        self._title.setText(f"Round {round.round_number} — {track_name(round.track_id)}")

        all_sessions = self._sessions.list_sessions()
        seasons = self._seasons.list_seasons()
        self._seasons_by_id = {season.season_id: season for season in seasons}
        self._placed = self._read_placements(seasons)
        target = self._target()
        assigned = {uid for uid, placement in self._placed.items() if placement == target}
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
            # resolve. A weekend that resolved always has at least the session that named it.
            empty = QLabel(
                f"No sessions are assigned to round {round.round_number} yet, so there is no "
                "weekend to show. Use “Assign sessions…” to put this round's sessions in it.")
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

    def _target(self) -> tuple[int, int] | None:
        """This page's ``(season_id, round_number)``, or None before ``load`` has run."""
        if self._season_id is None or self._round_number is None:
            return None
        return (self._season_id, self._round_number)

    def _read_placements(self, seasons) -> dict[int, tuple[int, int]]:
        """Every assigned session uid mapped to the round it sits in, across all seasons.

        One query per season rather than one per row: a card has to know not just *whether* a
        session is assigned, but *where*, down to the round. ``assigned_seasons`` drops the round,
        and ``assignment_for`` per card is a query per card. Note the pair order coming back from
        ``assignments_for_season`` is ``(round_number, session_uid)``, which reads backwards.
        """
        placements: dict[int, tuple[int, int]] = {}
        for season in seasons:
            for round_number, session_uid in self._seasons.assignments_for_season(season.season_id):
                placements[session_uid] = (season.season_id, round_number)
        return placements

    def _card(self, row: SessionRow) -> QWidget:
        """The shared card, titled with the slot alone - the track is in the page header.

        Two attempts at one slot are two of these in a row, identical but for the recorded time on
        the meta line and, usually, for one of them carrying the "not assigned" note. Nothing
        numbers them: which one counts is a judgement about the session (core invariant #5).
        """
        uid = str(row.session.session_uid)
        placement = self._placed.get(row.session.session_uid)
        name_of = display_name_fn(self._rosters.roster_for_session(row.session.session_uid))
        card = SessionCard(
            row.session,
            title=row.label,
            label=row.label,
            name_of=name_of,
            note=self._note(placement),
            actions=(
                self._placement_action(int(row.session.session_uid), placement),
                CardAction(
                    "Delete…",
                    "Delete this session's stored results (the recording is kept)",
                    partial(self._delete, int(row.session.session_uid)),
                ),
            ),
            expanded=uid not in self._collapsed,
        )
        card.activated.connect(partial(self.session_requested.emit, uid))
        card.toggled.connect(partial(self._remember, uid))
        return card

    def _note(self, placement) -> str:
        """The marker separating this round's rows from the ones the page merely *shows*.

        Empty for a session in this round, which is the ordinary case and says nothing worth the
        width. The two exceptions are what a user comes here to resolve: an attempt nobody
        assigned, and one filed under a different round.
        """
        if placement == self._target():
            return ""
        if placement is None:
            return "not assigned"
        season = self._seasons_by_id.get(placement[0])
        return f"assigned to round {placement[1]} of {season_phrase(season)}"

    def _placement_action(self, session_uid: int, placement) -> CardAction:
        """The one action that changes where a session lives, worded for the state it is in."""
        if placement == self._target():
            return CardAction(
                "Unassign",
                "Take this session out of this round. It stays stored, and can be re-assigned.",
                partial(self._unassign, session_uid))
        if placement is None:
            return CardAction(
                "Assign",
                "Put this session in this round",
                partial(self._assign, session_uid))
        return CardAction(
            "Move here",
            f"Move this session out of round {placement[1]} and into this one - a session "
            "belongs to one round at a time.",
            partial(self._assign, session_uid))


    # --- write the assignments ------------------------------------------------
    def _on_assign(self) -> None:
        """Pick a stored session for this round - the only way into a round with no weekend yet."""
        target, round = self._target(), self._round()
        if target is None or round is None:
            return
        seasons = self._seasons.list_seasons()
        dialog = AssignDialog(
            self,
            all_sessions=self._sessions.list_sessions(),
            seasons=seasons,
            placements=self._read_placements(seasons),
            target=target,
            track_id=round.track_id,
            round_title=f"round {round.round_number} at {track_name(round.track_id)}",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = dialog.chosen_uid
        if chosen is not None:
            self._assign(chosen)

    def _assign(self, session_uid: int) -> None:
        """Put one session in this round, then offer the rest of its weekend.

        ``assign_session`` moves rather than duplicates, so this is also the Move here action -
        the store enforces one round per session and this page does not have to.
        """
        target = self._target()
        if target is None:
            return
        self._seasons.assign_session(int(session_uid), *target)
        self._propose_weekend(int(session_uid))
        self.reload()

    def _unassign(self, session_uid: int) -> None:
        """Take one session out of this round. Unconfirmed: nothing stored is lost by it.

        Unassigning the round's *last* session leaves it with no weekend to resolve, so the page
        drops to its empty state - correct rather than surprising, since the round genuinely holds
        nothing now. Re-filing a weekend is better done the other way round, from the round it is
        moving to, where one pick and one confirmation carry the whole weekend across.
        """
        self._seasons.unassign_session(int(session_uid))
        self.reload()

    def _propose_weekend(self, anchor_uid: int) -> None:
        """Offer the rest of the weekend the just-assigned session came from.

        Proposed and never written silently: a wrong automatic assignment is invisible, survives
        into standings, and freezes the calendar around itself through ``set_calendar``'s
        locked-round rule (DECISIONS -> Storage). No dialog appears when there is nothing to
        offer - a modal saying "nothing happened" is worse than the page simply reloading, and a
        held-back slot needs no announcement here because both its attempts are cards on the page.
        """
        target = self._target()
        if target is None:
            return
        all_sessions = self._sessions.list_sessions()
        anchor = next((s for s in all_sessions if s.session_uid == anchor_uid), None)
        if anchor is None:
            return
        proposal = weekend_proposal(
            anchor, all_sessions, self._read_placements(self._seasons.list_seasons()), target)
        if not proposal.sessions or not self._confirm_proposal(proposal):
            return
        for proposed in proposal.sessions:
            self._seasons.assign_session(int(proposed.session.session_uid), *target)

    def _confirm_proposal(self, proposal) -> bool:
        """Ask before assigning the rest of a weekend, spelling out everything a Yes does."""
        count = len(proposal.sessions)
        listed = "\n".join(f"    {p.label}  ·  {recorded_label(p.session.recorded_at)}"
                           for p in proposal.sessions)
        parts = [
            f"{count} other stored session{'' if count == 1 else 's'} "
            f"{'was' if count == 1 else 'were'} recorded in the same race weekend. Assign "
            f"{'it' if count == 1 else 'them'} to round {self._round_number} as well?",
            listed,
        ]
        moving = [p for p in proposal.sessions if p.placement is not None]
        if moving:
            parts.append(self._moves_warning(moving))
        if proposal.held_back:
            parts.append(
                f"{self._held_back_phrase(proposal.held_back)} recorded more than once and "
                "not offered: nothing stored says which attempt counts, so that slot is yours "
                "to choose. Both attempts are listed on the page.")
        parts.append("Nothing is assigned if you say No - you can still assign any of them one "
                     "at a time.")
        # A proposal that only adds defaults to Yes; one that would empty another round does not.
        default = (QMessageBox.StandardButton.No if moving
                   else QMessageBox.StandardButton.Yes)
        answer = QMessageBox.question(
            self, "Assign the rest of this weekend?", "\n\n".join(parts),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, default)
        return answer == QMessageBox.StandardButton.Yes

    def _moves_warning(self, moving) -> str:
        """Name the rounds a Yes would take sessions out of - the one thing here that removes."""
        rounds = Counter(p.placement for p in moving)
        where = "; ".join(
            f"{count} from round {placement[1]} of "
            f"{season_phrase(self._seasons_by_id.get(placement[0]))}"
            for placement, count in sorted(rounds.items()))
        return (f"This moves sessions out of another round — {where}. A session belongs to one "
                 "round at a time, so those rounds lose them.")

    @staticmethod
    def _held_back_phrase(labels) -> str:
        """'Practice 2 was' / 'Practice 2, Race were' - the subject of the held-back sentence."""
        joined = ", ".join(labels)
        return f"{joined} was" if len(labels) == 1 else f"{joined} were"

    # --- rendering -----------------------------------------------------
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
        label = QLabel(f"{row.label}  —  {row.state.value}")
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
