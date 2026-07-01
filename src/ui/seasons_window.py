"""The seasons surface - browse, create, and drill into user-authored seasons.

A single QWidget backed by an internal QStackedWidget with three pages: on overview of all
seasons (or empty state), a create form, and a per-season detail showing its calendar and
current standings. All navigation stays inside this widget, and inside the one application
window - nothing opens a new window.

Scope 1: browse and create (with all-Track-25/26 presets) plus a read-only detail.
Scope 2: Assign captured seasons to rounds, weekend drill-down, custom-calendar picker, and
roster-resolved league standings.
"""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
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
    QVBoxLayout,
    QWidget,
)

from ..analysis.standings import standings_for_rounds
from ..domain.calendars import official_calendar
from ..domain.season import SeasonMode
from ..protocol.reference import track_name
 
_MODE_LABELS = {
    SeasonMode.MY_TEAM: "My Team",
    SeasonMode.DRIVER_CAREER: "Driver Career",
    SeasonMode.SOLO_CHAMPIONSHIP: "Solo Championship",
    SeasonMode.LEAGUE: "Multiplayer (League)",
}


def _format_label(game_format: int) -> str:
    """Return a human-readable label for a game format number."""
    return {2025: "F1 25", 2026: "F1 26"}.get(game_format, f"F1 {game_format}")
 
 
def _season_title(season) -> str:
    """Return a human-readable title for a season, e.g. "My Team · Season 1 · “Wednesday League”"."""
    bits = [_MODE_LABELS.get(season.mode, season.mode.name), f"Season {season.number}"]
    if season.nickname:
        bits.append(f"\u201c{season.nickname}\u201d")
    return "   \u00b7   ".join(bits)
 
 
class SeasonsView(QWidget):
    """Browse / create / inspect seasons, swapping pages inside one widget."""
 
    _OVERVIEW, _CREATE, _DETAIL = 0, 1, 2
 
    def __init__(self, season_store, session_store, parent=None) -> None:
        """Initialize the seasons view."""
        super().__init__(parent)
        self._seasons = season_store
        self._sessions = session_store
        self._current_season_id: int | None = None
 
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_overview())     # _OVERVIEW
        self._stack.addWidget(self._build_create())       # _CREATE
        self._stack.addWidget(self._build_detail())        # _DETAIL
 
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
        if self._stack.currentIndex() == self._DETAIL and self._current_season_id is not None:
            self._show_detail(self._current_season_id)
        elif self._stack.currentIndex() == self._OVERVIEW:
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
            self._mode_combo.addItem(_MODE_LABELS[mode], mode)
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

        cal_caption = QLabel("Calendar")
        cal_caption.setStyleSheet("font-weight: 600; margin-top: 12px;")
        outer.addWidget(cal_caption)
        self._calendar_table = QTableWidget(0, 3)
        self._calendar_table.setHorizontalHeaderLabels(["Round", "Track", "Results"])
        _tidy_table(self._calendar_table)
        outer.addWidget(self._calendar_table, 3)

        st_caption = QLabel("Standings")
        st_caption.setStyleSheet("font-weight: 600; margin-top: 6px;")
        outer.addWidget(st_caption)
        self._standings_table = QTableWidget(0, 4)
        self._standings_table.setHorizontalHeaderLabels(["Pos", "Driver", "No.", "Points"])
        _tidy_table(self._standings_table)
        outer.addWidget(self._standings_table, 2)

        self._standings_empty = QLabel(
            "No results yet \u2014 assign captured race weekends tho this season's round to "
            "see standings."
        )
        self._standings_empty.setStyleSheet("color: palette(mid);")
        self._standings_empty.setWordWrap(True)
        outer.addWidget(self._standings_empty)
        return page
    
    def _show_detail(self, season_id: int) -> None:
        """Switch to the detail page for a season, showing its calendar and standings."""
        season = self._seasons.get_season(season_id)
        if season is None:
            return
        self._current_season_id = season_id
        self._detail_title.setText(_season_title(season))

        rounds = self._seasons.rounds_with_results(season_id, self._sessions)

        self._calendar_table.setRowCount(len(rounds))
        for i, round in enumerate(rounds):
            n = len(round.sessions)
            self._calendar_table.setItem(i, 0, _cell(str(round.round_number)))
            self._calendar_table.setItem(i, 1, _cell(track_name(round.track_id)))
            self._calendar_table.setItem(i, 2, _cell(str(n) if n else "\u2014"))

        rows = standings_for_rounds(rounds)
        self._standings_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self._standings_table.setItem(i, 0, _cell(str(row.position)))
            self._standings_table.setItem(i, 1, _cell(row.driver_name))
            self._standings_table.setItem(i, 2, _cell(str(row.race_number)))
            self._standings_table.setItem(i, 3, _cell(str(row.points)))
        self._standings_table.setVisible(bool(rows))
        self._standings_empty.setVisible(not rows)

        self._stack.setCurrentIndex(self._DETAIL)

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