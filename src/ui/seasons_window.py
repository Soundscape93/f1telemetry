"""The seasons surface - browse, create, and drill into user-authored seasons.

A single QWidget backed by an internal QStackedWidget with three pages: on overview of all
seasons (or empty state), a create form, and a per-season detail showing its calendar and
current standings. All navigation stays inside this widget, and inside the one application
window - nothing opens a new window.

Scope 1: browse and create (with all-Track-25/26 presets) plus a read-only detail.
Scope 2a: weekend drill-down + round-centric session assignment (standings fill, name-keyed).
Later: roster resolved league standingds (2b) and the custom-calender picker (2c).
"""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..analysis.standings import standings_for_rounds
from ..domain.calendars import official_calendar
from ..domain.season import SeasonMode
from ..protocol.reference import track_name, team_name
from ..protocol.enums import SessionType
from .formatting import is_race, non_race_result, race_result, race_winner_summary
 
_MODE_LABELS = {
    SeasonMode.MY_TEAM: "My Team",
    SeasonMode.DRIVER_CAREER: "Driver Career",
    SeasonMode.SOLO_CHAMPIONSHIP: "Solo Championship",
    SeasonMode.LEAGUE: "Multiplayer (League)",
}


def _mode_label(mode) -> str:
    """ Return a human-readable label for a SeasonMode, tolerant of enum renames."""
    return _MODE_LABELS.get(mode, mode.name)


def _format_label(game_format: int) -> str:
    """Return a human-readable label for a game format number."""
    return {2025: "F1 25", 2026: "F1 26"}.get(game_format, f"F1 {game_format}")
 
 
def _season_title(season) -> str:
    """Return a human-readable title for a season, e.g. "My Team · Season 1 · “Wednesday League”"."""
    bits = [_mode_label(season.mode), f"Season {season.number}"]
    if season.nickname:
        bits.append(f"\u201c{season.nickname}\u201d")
    return "   \u00b7   ".join(bits)


def _slot_label(sesson_type) -> str:
    """Return prettified session-type name, e.g. RACE -> Race, SHORT_QUALIFYING -> Short Qualifying."""
    name = getattr(sesson_type, "name", None)
    return name.replace("_", " ").title() if name else str(sesson_type)

 
class SeasonsView(QWidget):
    """Browse / create / inspect seasons and drill into weekends, all in one widget."""
 
    _OVERVIEW, _CREATE, _DETAIL, _WEEKEND = 0, 1, 2, 3
 
    def __init__(self, season_store, session_store, parent=None) -> None:
        """Initialize the seasons view."""
        super().__init__(parent)
        self._seasons = season_store
        self._sessions = session_store
        self._current_season_id: int | None = None
        self._current_round_number: int | None = None
        self._detail_rounds: list = []          # 
        self._weekend_track_id: int | None = None
        self._weekend_assigned_uids: set[int] = set()
        self._collapsed_session_uids: set[int] = set()
 
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_overview())     # _OVERVIEW
        self._stack.addWidget(self._build_create())       # _CREATE
        self._stack.addWidget(self._build_detail())        # _DETAIL
        self._stack.addWidget(self._build_weekend())        # _WEEKEND
 
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)
 
        self._show_overview()
 
    def showEvent(self, event) -> None:
        """Refresh the overview when the widget is shown, in case a capture was ingested."""
        super().showEvent(event)
        self._show_overview()
 
    def refresh(self) -> None:
        """Re-query whatever page is showing (e.g. after a capture is ingested)."""
        idx = self._stack.currentIndex()
        if idx == self._WEEKEND and self._current_season_id is not None \
                and self._current_round_number is not None:
            self._reload_weekend()
        elif idx == self._DETAIL and self._current_season_id is not None:
            self._show_detail(self._current_season_id)
        elif idx == self._OVERVIEW:
            self._reload_overview()

    # --- overview ------------------------------------------------------

    def _build_overview(self) -> QWidget:
        """Build the overview page, which is either a list of seasons or an empty state."""
        page = QWidget()
        outer = QVBoxLayout(page)

        header = QHBoxLayout()
        title = QLabel("Seasons")
        title.setStyleSheet("font-size: 20px; font-weight: 600")
        new_btn = QPushButton("Create new season")
        new_btn.clicked.connect(self._show_create)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(new_btn)
        outer.addLayout(header)

        # the list of seasons cards (or empty state) is rebuilt into this layout
        self._overview_body = QVBoxLayout()
        body_host = QWidget()
        body_host.setLayout(self._overview_body)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(body_host)
        outer.addWidget(scroll, 1)
        return page
    
    def _reload_overview(self) -> None:
        """Rebuild the overview body with the current seasons or empty state."""
        _clear_layout(self._overview_body)
        seasons = self._seasons.list_seasons()

        if not seasons:
            self._overview_body.addStretch(1)
            heading = QLabel("Create your first season")
            heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
            heading.setStyleSheet("font-size: 18px; font-weight: 600")
            blurb = QLabel(
                "Track your My Team, Driver Career, and Multiplayer seasons with "
                "F1 Telemetry. Create a season, then assign your captured race weekends to "
                "its rounds."
            )
            blurb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            blurb.setWordWrap(True)
            blurb.setStyleSheet("font-size: 14px; color: palette(mid);")
            self._overview_body.addWidget(heading)
            self._overview_body.addWidget(blurb)
            self._overview_body.addStretch(1)
            return
        
        for season in seasons:
            self._overview_body.addWidget(self._season_card(season))
        self._overview_body.addStretch(1)


    def _season_card(self, season) -> QWidget:
        """Return a row with a clickable season card and a delete button."""
        subtitle = f"{_format_label(season.game_format)}   \u00b7   {len(season.rounds)} rounds"
        card = QPushButton(f"{_season_title(season)}      \u2014      {subtitle}")
        card.setStyleSheet("QPushButton { text-align: left; padding: 12px 14px; }")
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.clicked.connect(partial(self._show_detail, season.season_id))

        delete = QPushButton("Delete")
        delete.setCursor(Qt.CursorShape.PointingHandCursor)
        delete.clicked.connect(partial(self._delete_season, season.season_id))

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(card, 1)
        row_layout.addWidget(delete)
        return row

    def _delete_season(self, season_id: int) -> None:
        """Confirm, then delete a season and return to a refreshed overview."""
        season = self._seasons.get_season(season_id)
        if season is None:
            return
        confirm = QMessageBox.question(
            self,
            "Delete season",
            f"Delete {_season_title(season)}?\n\nThis removes its calendar and round "
            "assignments. Your captured sessions are not deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._seasons.delete_season(season_id)
        if self._current_season_id == season_id:
            self._current_season_id = None
        self._show_overview()

    def _show_overview(self) -> None:
        """Switch to the overview page and refresh its contents."""
        self._reload_overview()
        self._stack.setCurrentIndex(self._OVERVIEW)

    # --- create --------------------------------------------------------

    def _build_create(self) -> QWidget:
        """Build the create page, which is a form for creating a new season."""
        page = QWidget()
        outer = QVBoxLayout(page)

        title = QLabel("Create a new season")
        title.setStyleSheet("font-size: 20px; font-weight: 600")
        outer.addWidget(title)

        form = QFormLayout()
        self._mode_combo = QComboBox()
        for mode in SeasonMode:
            self._mode_combo.addItem(_mode_label(mode), mode)
        form.addRow("Game mode:", self._mode_combo)

        self._number_spin = QSpinBox()
        self._number_spin.setRange(1, 99)
        form.addRow("Season number:", self._number_spin)

        self._nickname_edit = QLineEdit()
        self._nickname_edit.setPlaceholderText("optional")
        form.addRow("Nickname:", self._nickname_edit)
        outer.addLayout(form)

        self._cal_group = QButtonGroup(page)
        self._rb_25 = QRadioButton("All tracks \u2014 F1 25 (24 rounds)")
        self._rb_26 = QRadioButton("All tracks \u2014 F1 26 (24 rounds)")
        self._rb_custom = QRadioButton("Custom calendar \u2014 coming soon")
        self._rb_custom.setEnabled(False)
        self._rb_25.setChecked(True)
        for rb in (self._rb_25, self._rb_26, self._rb_custom):
            self._cal_group.addButton(rb)
            outer.addWidget(rb)

        outer.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self._show_overview)
        create = QPushButton("Create season")
        create.setDefault(True)
        create.clicked.connect(self._create_season)
        buttons.addWidget(cancel)
        buttons.addWidget(create)
        outer.addLayout(buttons)
        return page
    
    def _reset_create_form(self) -> None:
        """Reset the create form to its default state."""
        self._mode_combo.setCurrentIndex(0)
        self._number_spin.setValue(1)
        self._nickname_edit.clear()
        self._rb_25.setChecked(True)

    def _show_create(self) -> None:
        """Switch to the create page and reset the form."""
        self._reset_create_form()
        self._stack.setCurrentIndex(self._CREATE)

    def _create_season(self) -> None:
        """Create a new season from the form values and switch to its detail page."""
        mode = self._mode_combo.currentData()
        number = self._number_spin.value()
        nickname = self._nickname_edit.text().strip() or None
        game_format = 2025 if self._rb_25.isChecked() else 2026
        rounds = official_calendar(game_format)

        season = self._seasons.create_season(
            mode=mode, number=number, game_format=game_format,
            nickname=nickname, rounds=rounds
        )
        self._show_detail(season.season_id)

    # --- detail --------------------------------------------------------

    def _build_detail(self) -> QWidget:
        """Build the detail page, which shows a season's calendar and standings."""
        page = QWidget()
        outer = QVBoxLayout(page)

        header = QHBoxLayout()
        back = QPushButton("\u2190 Seasons")
        back.clicked.connect(self._show_overview)
        self._detail_title = QLabel()
        self._detail_title.setStyleSheet("font-size: 20px; font-weight: 600")
        header.addWidget(back)
        header.addSpacing(12)
        header.addWidget(self._detail_title)
        header.addStretch(1)
        outer.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(16)

        calendar_panel = QWidget()
        calendar_layout = QVBoxLayout(calendar_panel)
        calendar_layout.setContentsMargins(0, 0, 0, 0)
        cal_caption = QLabel("Calendar")
        cal_caption.setStyleSheet("font-weight: 600; margin-top: 12px;")
        calendar_layout.addWidget(cal_caption)
        hint = QLabel("Double-click a round to open its weekend and assign sessions.")
        hint.setStyleSheet("color: palette(mid);")
        calendar_layout.addWidget(hint)

        self._calendar_table = QTableWidget(0, 3)
        self._calendar_table.setHorizontalHeaderLabels(["Round", "Track", "Results"])
        _tidy_table(self._calendar_table)
        self._calendar_table.cellDoubleClicked.connect(self._on_calendar_activated)
        calendar_layout.addWidget(self._calendar_table)
        calendar_layout.addStretch(1)

        standings_panel = QWidget()
        standings_layout = QVBoxLayout(standings_panel)
        standings_layout.setContentsMargins(0, 0, 0, 0)
        st_caption = QLabel("Standings")
        st_caption.setStyleSheet("font-weight: 600; margin-top: 12px;")
        standings_layout.addWidget(st_caption)
        standings_hint = QLabel(" ")
        standings_hint.setStyleSheet("color: palette(mid);")
        standings_layout.addWidget(standings_hint)
        self._standings_table = QTableWidget(0, 4)
        self._standings_table.setHorizontalHeaderLabels(["Pos", "Driver", "No.", "Points"])
        _tidy_table(self._standings_table)
        standings_layout.addWidget(self._standings_table)

        self._standings_empty = QLabel(
            "No results yet \u2014 assign captured race weekends to this season's round to "
            "see standings."
        )
        self._standings_empty.setStyleSheet("color: palette(mid);")
        self._standings_empty.setWordWrap(True)
        standings_layout.addWidget(self._standings_empty)
        standings_layout.addStretch(1)

        body.addWidget(calendar_panel, 3)
        body.addWidget(standings_panel, 2)
        outer.addLayout(body, 1)
        return page
    
    def _show_detail(self, season_id: int) -> None:
        """Switch to the detail page for a season, showing its calendar and standings."""
        season = self._seasons.get_season(season_id)
        if season is None:
            self._show_overview()
            return
        self._current_season_id = season_id
        self._detail_title.setText(_season_title(season))

        rounds = self._seasons.rounds_with_results(season_id, self._sessions)
        self._detail_title.setText(_season_title(season))

        self._calendar_table.setRowCount(len(rounds))
        for i, round in enumerate(rounds):
            self._calendar_table.setItem(i, 0, _cell(str(round.round_number)))
            self._calendar_table.setItem(i, 1, _cell(track_name(round.track_id)))
            self._calendar_table.setItem(i, 2, _cell(_round_result_summary(round)))
        _fit_table_height(self._calendar_table)

        rows = standings_for_rounds(rounds)
        self._standings_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self._standings_table.setItem(i, 0, _cell(str(row.position)))
            self._standings_table.setItem(i, 1, _cell(row.driver_name))
            self._standings_table.setItem(i, 2, _cell(str(row.race_number)))
            self._standings_table.setItem(i, 3, _cell(str(row.points)))
        _fit_table_height(self._standings_table)
        self._standings_table.setVisible(bool(rows))
        self._standings_empty.setVisible(not rows)

        self._stack.setCurrentIndex(self._DETAIL)

    def _on_calendar_activated(self, row: int, _column: int) -> None:
        """Open the weekend view for the activated round."""
        if self._current_season_id is None:
            return
        item = self._calendar_table.item(row, 0)
        if item is None:
            return
        try:
            round_number = int(item.text())
        except ValueError:
            return
        self._show_weekend(self._current_season_id, round_number)

    # --- weekend --------------------------------------------------------

    def _build_weekend(self) -> QWidget:
        """Build the weekend page: a round's assigned sessions plus the assignment picker."""
        page = QWidget()
        outer = QVBoxLayout(page)

        header = QHBoxLayout()
        back = QPushButton("\u2190 Season")
        back.clicked.connect(lambda: self._show_detail(self._current_season_id))
        self._weekend_title = QLabel()
        self._weekend_title.setStyleSheet("font-size: 20px; font-weight: 600")
        header.addWidget(back)
        header.addSpacing(12)
        header.addWidget(self._weekend_title)
        header.addStretch(1)
        outer.addLayout(header)

        sess_caption = QLabel("Sessions")
        sess_caption.setStyleSheet("font-weight: 600; margin-top: 8px;")
        outer.addWidget(sess_caption)

        # assigned sessions (each a results table) are rebuilt into this layout, inside a scroll
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
        _tidy_table(self._capture_table)
        self._capture_table.setMinimumHeight(135)
        self._capture_table.setMaximumHeight(165)
        outer.addWidget(self._capture_table)

        return page

    def _show_weekend(self, season_id: int, round_number: int) -> None:
        """Switch to the weekend page for a given season/round."""
        self._current_season_id = season_id
        self._current_round_number = round_number
        self._reload_weekend()
        self._stack.setCurrentIndex(self._WEEKEND)

    def _reload_weekend(self) -> None:
        """Re-query the current round: title, assigned sessions, and the capture picker."""
        season = self._seasons.get_season(self._current_season_id)
        if season is None:
            self._show_overview()
            return
        rounds = self._seasons.rounds_with_results(self._current_season_id, self._sessions)
        round = next((r for r in rounds if r.round_number == self._current_round_number), None)
        if round is None:
            self._show_detail(self._current_season_id)
            return

        self._weekend_track_id = round.track_id
        self._weekend_assigned_uids = {s.session_uid for s in round.sessions}
        self._weekend_title.setText(f"Round {round.round_number} \u2014 {track_name(round.track_id)}")

        _clear_layout(self._assigned_body)
        if not round.sessions:
            empty = QLabel("No sessions assigned to this round yet \u2014 and one below.")
            empty.setStyleSheet("color: palette(mid);")
            self._assigned_body.addWidget(empty)
        else:
            for session in sorted(round.sessions, key=lambda s: int(s.session_type)):
                self._assigned_body.addWidget(self._session_block(session))
        self._assigned_body.addStretch(1)

        self._reload_capture_picker()

    def _session_block(self, session) -> QWidget:
        """A labelled classification table for one assigned session, with an Unassign button.
        Race sessions show the winner's time and gaps; others show best-lap times."""
        block = QWidget()
        vbox = QVBoxLayout(block)
        vbox.setContentsMargins(0, 0, 0, 0)

        header = QHBoxLayout()
        toggle = QToolButton()
        toggle.setCheckable(True)
        toggle.setChecked(session.session_uid not in self._collapsed_session_uids)
        toggle.setText(_slot_label(session.session_type))
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
        
        race_session = is_race(session.session_type)
        if race_session:
            columns = ["Pos", "Driver", "No.", "Team", "Time", "Points"]
        else:
            columns = ["Pos", "Driver", "No.", "Team", "Best lap", "Laps"]
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
        _tidy_table(table)

        entries = session.classification.entries if session.classification else []
        winner = next((e for e in entries if e.position == 1), entries[0] if entries else None)
        table.setRowCount(len(entries))
        for i, entry in enumerate(entries):
            table.setItem(i, 0, _cell(str(entry.position)))
            table.setItem(i, 1, _cell(entry.driver_name))
            table.setItem(i, 2, _cell(str(entry.race_number)))
            table.setItem(i, 3, _cell(team_name(entry.team_id)))
            if race_session:
                table.setItem(i, 4, _cell(race_result(entry, winner)))
                table.setItem(i, 5, _cell(str(entry.points)))
            else:
                table.setItem(i, 4, _cell(non_race_result(entry, session.session_type)))
                table.setItem(i, 5, _cell(str(entry.num_laps)))
        _fit_table_height(table)
        table.setVisible(toggle.isChecked())
        toggle.toggled.connect(partial(self._toggle_session_table, session.session_uid, table, toggle))
        vbox.addWidget(table)
        return block

    def _toggle_session_table(self, session_uid: int, table: QTableWidget,
                              toggle: QToolButton, expanded: bool) -> None:
        """Fold/unfold an assigned session's classification table."""
        table.setVisible(expanded)
        toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        if expanded:
            self._collapsed_session_uids.discard(session_uid)
        else:
            self._collapsed_session_uids.add(session_uid)


    def _reload_capture_picker(self) -> None:
        """Fill the picker with captures assignable to this round (track-matched by default)."""
        show_all = self._show_all_tracks.isChecked()
        candidates = [
            s for s in self._sessions.list_sessions()
            if (show_all or s.track_id == self._weekend_track_id)
            and s.session_uid not in self._weekend_assigned_uids
        ]
        self._capture_table.setRowCount(len(candidates))
        for i, session in enumerate(candidates):
            drivers = len(session.classification.entries) if session.classification else 0
            first = _cell(_slot_label(session.session_type))
            first.setData(Qt.ItemDataRole.UserRole, str(session.session_uid))
            self._capture_table.setItem(i, 0, first)
            self._capture_table.setItem(i, 1, _cell(track_name(session.track_id)))
            self._capture_table.setItem(i, 2, _cell(str(drivers)))
            self._capture_table.setItem(i, 3, _cell(str(session.session_uid)))

    def _assign_selected(self) -> None:
        """Assign the selected caputure to the current round, then re-query the weekend."""
        selected = self._capture_table.selectionModel().selectedRows()
        if not selected:
            return
        uid = int(self._capture_table.item(selected[0].row(), 0).data(Qt.ItemDataRole.UserRole))
        self._seasons.assign_session(int(uid), self._current_season_id, self._current_round_number)
        self._reload_weekend()

    def _unassign(self, session_uid: int) -> None:
        """Remove a session from its round, then re-query the weekend."""
        self._seasons.unassign_session(int(session_uid))
        self._reload_weekend()


# --- small helpers --------------------------------------------------------

def _cell(text: str) -> QTableWidgetItem:
    """Return a read-only table cell with the given text."""
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    return item


def _tidy_table(table: QTableWidget) -> None:
    """Apply some common styling to a table: no vertical header, no editing, row selection, stretch columns."""
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)


def _clear_layout(layout: QVBoxLayout) -> None:
    """Remove all widgets from a layout and delete them."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


def _round_result_summary(round) -> str:
    """Return the calendar result cell: race winner/team, pending, or dash."""
    race_results = [
        summary for session in round.sessions
        if (summary := race_winner_summary(session)) is not None
    ]
    if race_results:
        return "; ".join(race_results)
    if round.sessions:
        return "Race pending"
    return "\u2014"

def _fit_table_height(table: QTableWidget) -> None:
    """Freeze a table's height to show all rows (no inner scrollbar); the outer scroll scrolls."""
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    height = table.horizontalHeader().height() + 2 * table.frameWidth()
    for i in range(table.rowCount()):
        height += table.rowHeight(i)
    table.setFixedHeight(height)
