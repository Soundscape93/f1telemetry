"""The weekend page - round-centric session assignment.

Shows each session already assigned to a round (as a foldable classification table) and a picker
of assignable captures filtered to the round's track. Roster-aware for LEAGUE seasons.
"""

from __future__ import annotations

from datetime import datetime
from functools import partial

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...domain.roster import LeagueRoster
from ...domain.season import SeasonMode, slot_for_session, weekend_slots
from ...protocol.reference import track_name
from ..components import (
    build_classification_table,
    cell,
    clear_layout,
    confirm_and_delete,
    display_name_fn,
    tidy_table,
)
from ..formatting import slot_label
from ..style import MUTED_TEXT_QSS, apply_bold, apply_heading
from .labels import season_title


def _recorded_label(recorded_at: datetime | None) -> str:
    """Local-time 'YYYY-MM-DD HH:MM' for a session's recorded_at, or an em dash if unset.

    ``recorded_at`` is stored as UTC; a tz-aware value is converted to local time, while a
    naive value (older rows) is shown as-is.
    """
    if recorded_at is None:
        return "—"
    if recorded_at.tzinfo is not None:
        recorded_at = recorded_at.astimezone()
    return recorded_at.strftime("%Y-%m-%d %H:%M")


class WeekendPage(QWidget):
    """Assign / unassign captures for one round and inspect each assigned session.

    ``load(season_id, round_number)`` populates the page. Emits ``detail_requested(season_id)``
    for the back button and when the round has vanished, and ``overview_requested`` when the
    season has vanished underneath it.
    """

    detail_requested = Signal(int)
    overview_requested = Signal()
    sessions_changed = Signal()      # Stored sessions data was deleted - other surfaces must re-read

    def __init__(self, season_store, session_store, season_rosters, lap_store=None, parent=None) -> None:
        """Initialize the weekend page."""
        super().__init__(parent)
        self._seasons = season_store
        self._sessions = session_store
        self._season_rosters = season_rosters
        self._laps = lap_store              # deleting a session takes its laps + traces with it
        self._season_id: int | None = None
        self._round_number: int | None = None
        self._track_id: int | None = None
        self._assigned_uids: set[int] = set()
        self._collapsed_session_uids: set[int] = set()

        outer = QVBoxLayout(self)

        header = QHBoxLayout()
        back = QPushButton("← Season")
        back.clicked.connect(self._on_back)
        self._title = QLabel()
        apply_heading(self._title, size_px=20)
        header.addWidget(back)
        header.addSpacing(12)
        header.addWidget(self._title)
        header.addStretch(1)
        outer.addLayout(header)

        sess_caption = QLabel("Sessions")
        apply_bold(sess_caption)
        sess_caption.setContentsMargins(0, 8, 0, 0)
        outer.addWidget(sess_caption)

        self._assigned_body = QVBoxLayout()
        assigned_host = QWidget()
        assigned_host.setLayout(self._assigned_body)
        assigned_scroll = QScrollArea()
        assigned_scroll.setWidgetResizable(True)
        assigned_scroll.setFrameShape(QFrame.Shape.NoFrame)
        assigned_scroll.setWidget(assigned_host)
        outer.addWidget(assigned_scroll, 1)

        pick_header = QHBoxLayout()
        pick_header.setContentsMargins(0, 4, 0, 0)
        pick_header.setSpacing(12)

        pick_caption = QLabel("Assign a capture")
        apply_bold(pick_caption)
        pick_header.addWidget(pick_caption)

        self._show_all_tracks = QCheckBox("Show captures from all tracks (not just this round's)")
        self._show_all_tracks.toggled.connect(lambda _checked: self._reload_capture_picker())
        pick_header.addWidget(self._show_all_tracks)

        pick_header.addStretch(1)

        assign_btn = QPushButton("Assign selected to this round")
        assign_btn.clicked.connect(self._assign_selected)
        pick_header.addWidget(assign_btn)

        outer.addLayout(pick_header)

        self._capture_table = QTableWidget(0, 5)
        self._capture_table.setHorizontalHeaderLabels(
            ["Session", "Track", "Drivers", "Recorded", "Session ID"]
        )
        tidy_table(self._capture_table)
        self._capture_table.setMinimumHeight(135)
        self._capture_table.setMaximumHeight(165)
        self._capture_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._capture_table.customContextMenuRequested.connect(self._show_capture_menu)
        outer.addWidget(self._capture_table)

    def _on_back(self) -> None:
        """Return to the season detail page."""
        if self._season_id is not None:
            self.detail_requested.emit(self._season_id)
        else:
            self.overview_requested.emit()

    def load(self, season_id: int, round_number: int) -> None:
        """Populate the page for a given season/round."""
        self._season_id = season_id
        self._round_number = round_number
        self.reload()

    def reload(self) -> None:
        """Re-query the current round."""
        season = self._seasons.get_season(self._season_id)
        if season is None:
            self.overview_requested.emit()
            return
        rounds = self._seasons.rounds_with_results(self._season_id, self._sessions)
        round = next((r for r in rounds if r.round_number == self._round_number), None)
        if round is None:
            self.detail_requested.emit(self._season_id)
            return
        name_of = display_name_fn(self._league_roster_for_weekend(season, rounds))

        self._track_id = round.track_id
        self._assigned_uids = {s.session_uid for s in round.sessions}
        self._title.setText(f"Round {round.round_number} — {track_name(round.track_id)}")

        clear_layout(self._assigned_body)
        if not round.sessions:
            empty = QLabel("No sessions assigned to this round yet — add one below.")
            empty.setStyleSheet(MUTED_TEXT_QSS)
            self._assigned_body.addWidget(empty)
        else:
            slots = weekend_slots(round.sessions)
            # An uncaptured slot reads differently depending on where it sits: one still to come
            # (after the latest captured session) is "not captured yet", while an earlier gap - a
            # session deliberately skipped, e.g. Practice 3 - is "Skipped" once you've moved past
            # it. It flips back to a real table if you later capture and assign it.
            last_captured = max(
                (slot.order for slot in slots if slot.session is not None), default=-1
            )
            for slot in slots:
                if slot.session is not None:
                    self._assigned_body.addWidget(self._session_block(slot, name_of))
                else:
                    self._assigned_body.addWidget(
                        self._pending_slot_row(slot, skipped=slot.order < last_captured)
                    )
        self._assigned_body.addStretch(1)

        self._reload_capture_picker()

    def _league_roster_for_weekend(self, season, rounds) -> LeagueRoster | None:
        """Return a roster for LEAGUE weekend tables (read-only). Non-LEAGUE seasons return
        None."""
        if season.mode != SeasonMode.LEAGUE:
            return None
        try:
            return self._season_rosters.roster_for(season, rounds, self._seasons.list_seasons)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "League roster", f"Could not load roster:\n\n{exc}")
            return LeagueRoster()

    def _pending_slot_row(self, slot, skipped: bool = False) -> QWidget:
        """A greyed placeholder for a weekend slot the game expects but that isn't captured.

        Keeps the Sprint Race / Race (and the sessions around them) in their real running order so
        an empty spot reads as intentional. ``skipped`` marks a slot already passed (a session you
        chose not to record) as "Skipped"; otherwise it's an upcoming "not captured yet".
        """
        state = "Skipped" if skipped else "not captured yet"
        label = QLabel(f"{slot_label(slot.session_type, slot.is_sprint_race)}  —  {state}")
        label.setStyleSheet(f"{MUTED_TEXT_QSS} font-style: italic; padding: 4px 0;")
        return label

    def _session_block(self, slot, name_of=lambda entry: entry.driver_name) -> QWidget:
        """A labelled classification table for one assigned session, with an Unassign button.

        ``slot`` is the session's :class:`WeekendSlot`, so the header reads "Sprint Race" vs
        "Race" from the weekend context rather than the (identical) raw session type.
        """
        session = slot.session
        block = QWidget()
        vbox = QVBoxLayout(block)
        vbox.setContentsMargins(0, 0, 0, 0)

        header = QHBoxLayout()
        toggle = QToolButton()
        toggle.setCheckable(True)
        toggle.setChecked(session.session_uid not in self._collapsed_session_uids)
        toggle.setText(slot_label(slot.session_type, slot.is_sprint_race))
        toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toggle.setArrowType(
            Qt.ArrowType.DownArrow if toggle.isChecked() else Qt.ArrowType.RightArrow
        )
        # No stylesheet - it would freeze the button's text colour at apply time (A4b).
        # border: none -> setAutoRaise, font-weight: 600 -> apply_bold, padding -> minimum height.
        toggle.setAutoRaise(True)
        apply_bold(toggle)
        toggle.setMinimumHeight(toggle.sizeHint().height() + 4)
        toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        unassign = QPushButton("Unassign")
        unassign.clicked.connect(partial(self._unassign, session.session_uid))
        header.addWidget(toggle)
        if session.classification is not None and session.classification.is_reconstructed:
            recon = QLabel("reconstructed")
            recon.setToolTip("No Final Classification packet was captured; this table was rebuilt "
                             "from telemetry. Points are estimated, not official.")
            recon.setStyleSheet(f"{MUTED_TEXT_QSS} font-style: italic; padding-left: 8px;")
            header.addWidget(recon)
        header.addStretch(1)
        header.addWidget(unassign)
        vbox.addLayout(header)

        table = build_classification_table(session, name_of, is_sprint_race=slot.is_sprint_race)
        table.setVisible(toggle.isChecked())
        toggle.toggled.connect(partial(self._toggle_session_table, session.session_uid, table, toggle))
        vbox.addWidget(table)
        return block

    def _toggle_session_table(
        self,
        session_uid: int,
        table: QTableWidget,
        toggle: QToolButton,
        expanded: bool,
    ) -> None:
        """Fold/unfold an assigned session's classification table."""
        table.setVisible(expanded)
        toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        if expanded:
            self._collapsed_session_uids.discard(session_uid)
        else:
            self._collapsed_session_uids.add(session_uid)

    def _reload_capture_picker(self) -> None:
        """Fill the picker with captures assignable to this round.

        Sessions already in *this* round are left out - they are listed above. Sessions assigned
        to another round, or another season, deliberately stay: assigning one **moves** it here,
        which is the repair for a misfiled session, and hiding them would make that session
        unfindable. They are marked instead - and the marker doubles as the warning that Delete
        will refuse them (``pipeline.delete_session``).
        """
        show_all = self._show_all_tracks.isChecked()
        all_sessions = self._sessions.list_sessions()
        candidates = [
            s for s in all_sessions
            if (show_all or s.track_id == self._track_id) and s.session_uid not in self._assigned_uids
        ]
        # One query for the set. The per-row placement and the season names are looked up only when at least one visible row actually needs them.
        elsewhere = self._seasons.assigned_uids() - self._assigned_uids
        marked = [s for s in candidates if s.session_uid in elsewhere]
        seasons_by_id = ({s.season_id: s for s in self._seasons.list_seasons()} if marked else {})

        self._capture_table.setRowCount(len(candidates))
        for i, session in enumerate(candidates):
            drivers = len(session.classification.entries) if session.classification else 0
            slot = slot_for_session(session, all_sessions)
            label = slot_label(slot.session_type, slot.is_sprint_race)
            placement = (self._seasons.assignment_for(session.session_uid)
                         if session.session_uid in elsewhere else None)
            if placement is not None:
                label = f"{label} — assigned to R{placement[1]}"
            first = cell(label)
            if placement is not None:
                first.setToolTip(self._assigned_tooltip(seasons_by_id, *placement))
            first.setData(Qt.ItemDataRole.UserRole, str(session.session_uid))
            self._capture_table.setItem(i, 0, first)
            self._capture_table.setItem(i, 1, cell(track_name(session.track_id)))
            self._capture_table.setItem(i, 2, cell(str(drivers)))
            self._capture_table.setItem(i, 3, cell(_recorded_label(session.recorded_at)))
            self._capture_table.setItem(i, 4, cell(str(session.session_uid)))

    @staticmethod
    def _assigned_tooltip(seasons_by_id, season_id: int, round_number: int) -> str:
        """Spell out a marker: which season that round belongs to, and what Delete will do.

        The marker itself is only "R*n*", which stops being unambiguous the moment a second
        season exists - the tooltip is where the season gets named.
        """
        season = seasons_by_id.get(season_id)
        where = (f"round {round_number} of {season_title(season)}" if season is not None
                 else f"round {round_number} of another season")
        return (f"Already assigned to {where}.\n"
                "Assigning it here moves it; deleting it is refused until it is unassigned.")

    def _assign_selected(self) -> None:
        """Assign the selected capture to the current round, then re-query the weekend."""
        selected = self._capture_table.selectionModel().selectedRows()
        if not selected:
            return
        uid = int(self._capture_table.item(selected[0].row(), 0).data(Qt.ItemDataRole.UserRole))
        self._seasons.assign_session(int(uid), self._season_id, self._round_number)
        self.reload()

    def _unassign(self, session_uid: int) -> None:
        """Remove a session from its round, then re-query the weekend."""
        self._seasons.unassign_session(int(session_uid))
        self.reload()

    def _show_capture_menu(self, pos) -> None:
        """Right-click menu for the capture picker: delete an unassigned capture's results."""
        item = self._capture_table.itemAt(pos)
        if item is None:
            return
        uid = int(self._capture_table.item(item.row(), 0).data(Qt.ItemDataRole.UserRole))
        menu = QMenu(self)
        delete = menu.addAction("Delete from database…")
        chosen = menu.exec(self._capture_table.viewport().mapToGlobal(pos))
        if chosen is delete:
            self._delete_capture(uid)

    def _delete_capture(self, session_uid: int) -> None:
        """Confirm, then delete a session's stored results (the recording is kept).

        Both halves are shared - the dialogs in ``components.session_actions``, the write in
        ``pipeline.delete_session`` - so this page and the Sessions surface cannot drift apart
        on the wording or on the assigned-session guard. A refusal or a cancel changes nothing,
        so neither needs a re-query.
        """
        if not confirm_and_delete(self, session_uid, self._sessions, self._seasons,
                                  lap_store=self._laps):
            return
        self.sessions_changed.emit()  # laps surface caches a layout built from these laps
        self.reload()
