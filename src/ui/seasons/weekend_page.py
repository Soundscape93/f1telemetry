"""The weekend page - round-centric session assignment.

Shows each session already assigned to a round (as a foldable classification table) and a picker
of assignable captures filtered to the round's track. Roster-aware for LEAGUE seasons.
"""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...domain.roster import LeagueRoster
from ...domain.season import SeasonMode
from ...protocol.reference import track_name
from ..components import (
    build_classification_table,
    cell,
    clear_layout,
    display_name_fn,
    tidy_table,
)
from ..formatting import slot_label


class WeekendPage(QWidget):
    """Assign / unassign captures for one round and inspect each assigned session.

    ``load(season_id, round_number)`` populates the page. Emits ``detail_requested(season_id)``
    for the back button and when the round has vanished, and ``overview_requested`` when the
    season has vanished underneath it.
    """

    detail_requested = Signal(int)
    overview_requested = Signal()

    def __init__(self, season_store, session_store, season_rosters, parent=None) -> None:
        """Initialize the weekend page."""
        super().__init__(parent)
        self._seasons = season_store
        self._sessions = session_store
        self._season_rosters = season_rosters
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
        self._title.setStyleSheet("font-size: 20px; font-weight: 600")
        header.addWidget(back)
        header.addSpacing(12)
        header.addWidget(self._title)
        header.addStretch(1)
        outer.addLayout(header)

        sess_caption = QLabel("Sessions")
        sess_caption.setStyleSheet("font-weight: 600; margin-top: 8px;")
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
        pick_caption.setStyleSheet("font-weight: 600;")
        pick_header.addWidget(pick_caption)

        self._show_all_tracks = QCheckBox("Show captures from all tracks (not just this round's)")
        self._show_all_tracks.toggled.connect(lambda _checked: self._reload_capture_picker())
        pick_header.addWidget(self._show_all_tracks)

        pick_header.addStretch(1)

        assign_btn = QPushButton("Assign selected to this round")
        assign_btn.clicked.connect(self._assign_selected)
        pick_header.addWidget(assign_btn)

        outer.addLayout(pick_header)

        self._capture_table = QTableWidget(0, 4)
        self._capture_table.setHorizontalHeaderLabels(["Session", "Track", "Drivers", "Session ID"])
        tidy_table(self._capture_table)
        self._capture_table.setMinimumHeight(135)
        self._capture_table.setMaximumHeight(165)
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
            empty.setStyleSheet("color: palette(mid);")
            self._assigned_body.addWidget(empty)
        else:
            for session in sorted(round.sessions, key=lambda s: int(s.session_type)):
                self._assigned_body.addWidget(self._session_block(session, name_of))
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

    def _session_block(self, session, name_of=lambda entry: entry.driver_name) -> QWidget:
        """A labelled classification table for one assigned session, with an Unassign button."""
        block = QWidget()
        vbox = QVBoxLayout(block)
        vbox.setContentsMargins(0, 0, 0, 0)

        header = QHBoxLayout()
        toggle = QToolButton()
        toggle.setCheckable(True)
        toggle.setChecked(session.session_uid not in self._collapsed_session_uids)
        toggle.setText(slot_label(session.session_type))
        toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toggle.setArrowType(
            Qt.ArrowType.DownArrow if toggle.isChecked() else Qt.ArrowType.RightArrow
        )
        toggle.setStyleSheet("QToolButton { font-weight: 600; border: none; padding: 4px 0; }")
        toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        unassign = QPushButton("Unassign")
        unassign.clicked.connect(partial(self._unassign, session.session_uid))
        header.addWidget(toggle)
        header.addStretch(1)
        header.addWidget(unassign)
        vbox.addLayout(header)

        table = build_classification_table(session, name_of)
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
        """Fill the picker with captures assignable to this round."""
        show_all = self._show_all_tracks.isChecked()
        candidates = [
            s for s in self._sessions.list_sessions()
            if (show_all or s.track_id == self._track_id)
            and s.session_uid not in self._assigned_uids
        ]
        self._capture_table.setRowCount(len(candidates))
        for i, session in enumerate(candidates):
            drivers = len(session.classification.entries) if session.classification else 0
            first = cell(slot_label(session.session_type))
            first.setData(Qt.ItemDataRole.UserRole, str(session.session_uid))
            self._capture_table.setItem(i, 0, first)
            self._capture_table.setItem(i, 1, cell(track_name(session.track_id)))
            self._capture_table.setItem(i, 2, cell(str(drivers)))
            self._capture_table.setItem(i, 3, cell(str(session.session_uid)))

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
