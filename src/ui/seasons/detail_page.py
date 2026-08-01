"""The per-season detail page - calendar plus player/constructor standings.

Roster-aware for LEAGUE seasons: loads-or-seeds the season roster read-only and offers explicit
Create/Import buttons. Double-clicking a calendar round asks the container to open its weekend.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ...analysis.standings import (
    constructor_standings_for_rounds,
    league_standings_for_rounds,
    standings_for_rounds,
)
from ...domain.roster import LeagueRoster
from ...domain.season import ROSTER_SEASON_MODES, grand_prix_session
from ...protocol.reference import team_display_name, track_name
from ..components import cell, display_name_fn, fit_table_height, tidy_table
from ..components.flags import flag_icon
from ..formatting import race_winner_summary
from ..style import MUTED_TEXT_QSS
from .labels import season_title


class DetailPage(QWidget):
    """Calendar + standings for one season, with LEAGUE roster management.

    ``load(season_id)`` populates the page. Emits ``weekend_requested(season_id, round_number)``
    when a round is activated and ``overview_requested`` for the back button (or when the season
    has vanished underneath it).
    """

    overview_requested = Signal()
    weekend_requested = Signal(int, int)

    def __init__(self, season_store, session_store, season_rosters, parent=None) -> None:
        """Initialize the detail page."""
        super().__init__(parent)
        self._seasons = season_store
        self._sessions = session_store
        self._season_rosters = season_rosters
        self._season_id: int | None = None

        outer = QVBoxLayout(self)

        header = QHBoxLayout()
        back = QPushButton("← Seasons")
        back.clicked.connect(self.overview_requested)
        self._title = QLabel()
        self._title.setStyleSheet("font-size: 20px; font-weight: 600")

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.addWidget(back)
        title_row.addSpacing(12)
        title_row.addWidget(self._title)
        title_row.addStretch(1)
        title_host = QWidget()
        title_host.setLayout(title_row)

        st_caption = QLabel("Player Standings")
        st_caption.setStyleSheet("font-weight: 600;")

        header.addWidget(title_host, 3)
        header.addWidget(st_caption, 2)
        outer.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(16)

        calendar_panel = QWidget()
        calendar_layout = QVBoxLayout(calendar_panel)
        calendar_layout.setContentsMargins(0, 0, 0, 0)
        cal_caption = QLabel("Calendar")
        cal_caption.setStyleSheet("font-weight: 600; margin-top: 0px;")
        calendar_layout.addWidget(cal_caption)
        hint = QLabel("Double-click a round to open its weekend and assign sessions.")
        hint.setStyleSheet(MUTED_TEXT_QSS)
        calendar_layout.addWidget(hint)

        self._calendar_table = QTableWidget(0, 3)
        self._calendar_table.setHorizontalHeaderLabels(["Round", "Track", "Results"])
        tidy_table(self._calendar_table)
        self._calendar_table.cellDoubleClicked.connect(self._on_calendar_activated)
        calendar_layout.addWidget(self._calendar_table)
        calendar_layout.addStretch(1)

        standings_panel = QWidget()
        standings_layout = QVBoxLayout(standings_panel)
        standings_layout.setContentsMargins(0, 0, 0, 0)
        standings_layout.setSpacing(6)

        self._roster_panel = QWidget()
        roster_layout = QVBoxLayout(self._roster_panel)
        roster_layout.setContentsMargins(0, 0, 0, 0)
        roster_layout.setSpacing(4)
        self._roster_status = QLabel()
        self._roster_status.setStyleSheet(MUTED_TEXT_QSS)
        self._roster_status.setWordWrap(True)
        roster_buttons = QHBoxLayout()
        self._roster_create_btn = QPushButton("Create roster file")
        self._roster_create_btn.clicked.connect(self._create_roster_file)
        roster_buttons.addWidget(self._roster_create_btn)
        self._roster_import_btn = QPushButton("Import roster CSV")
        self._roster_import_btn.clicked.connect(self._import_roster_csv)
        roster_buttons.addWidget(self._roster_import_btn)
        roster_buttons.addStretch(1)
        roster_layout.addWidget(self._roster_status)
        roster_layout.addLayout(roster_buttons)
        standings_layout.addWidget(self._roster_panel)

        self._standings_table = QTableWidget(0, 4)
        self._standings_table.setHorizontalHeaderLabels(["Pos", "Driver", "No.", "Points"])
        tidy_table(self._standings_table)
        standings_layout.addWidget(self._standings_table)

        self._standings_empty = QLabel(
            "No results yet — assign captured race weekends to this season's round to "
            "see standings."
        )
        self._standings_empty.setStyleSheet(MUTED_TEXT_QSS)
        self._standings_empty.setWordWrap(True)
        standings_layout.addWidget(self._standings_empty)

        ct_caption = QLabel("Constructor Standings")
        ct_caption.setStyleSheet("font-weight: 600; margin-top: 0px;")
        standings_layout.addWidget(ct_caption)
        self._constructor_table = QTableWidget(0, 3)
        self._constructor_table.setHorizontalHeaderLabels(["Pos", "Team", "Points"])
        tidy_table(self._constructor_table)
        standings_layout.addWidget(self._constructor_table)

        self._constructor_empty = QLabel(
            "No results yet — assign captured race weekends to this season's round to "
            "see standings."
        )
        self._constructor_empty.setStyleSheet(MUTED_TEXT_QSS)
        self._constructor_empty.setWordWrap(True)
        standings_layout.addWidget(self._constructor_empty)

        standings_layout.addStretch(1)

        body.addWidget(calendar_panel, 3)
        body.addWidget(standings_panel, 2)

        body_host = QWidget()
        body_host.setLayout(body)
        body_scroll = QScrollArea()
        body_scroll.setWidgetResizable(True)
        body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        body_scroll.setWidget(body_host)
        outer.addWidget(body_scroll, 1)

    def reload(self) -> None:
        """Re-query the currently loaded season."""
        if self._season_id is not None:
            self.load(self._season_id)

    def load(self, season_id: int) -> None:
        """Populate the page for a season, showing its calendar and standings."""
        season = self._seasons.get_season(season_id)
        if season is None:
            self.overview_requested.emit()
            return
        self._season_id = season_id
        self._title.setText(season_title(season))

        rounds = self._seasons.rounds_with_results(season_id, self._sessions)
        roster = self._league_roster_for_detail(season, rounds)
        name_of = display_name_fn(roster)

        self._calendar_table.setRowCount(len(rounds))
        for i, round in enumerate(rounds):
            self._calendar_table.setItem(i, 0, cell(str(round.round_number)))
            self._calendar_table.setItem(i, 1, cell(track_name(round.track_id)))
            self._calendar_table.setItem(i, 2, cell(_round_result_summary(round, name_of)))
        fit_table_height(self._calendar_table)

        rows = (
            league_standings_for_rounds(rounds, roster)
            if roster is not None
            else standings_for_rounds(rounds)
        )

        self._standings_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self._standings_table.setItem(i, 0, cell(str(row.position)))
            driver_item = cell(row.driver_name)
            flag = flag_icon(row.nationality_id)
            if flag is not None:
                driver_item.setIcon(flag)
            self._standings_table.setItem(i, 1, driver_item)
            self._standings_table.setItem(i, 2, cell(str(row.race_number)))
            self._standings_table.setItem(i, 3, cell(str(row.points)))
        fit_table_height(self._standings_table)
        self._standings_table.setVisible(bool(rows))
        self._standings_empty.setVisible(not rows)

        constructor_rows = constructor_standings_for_rounds(rounds)
        self._constructor_table.setRowCount(len(constructor_rows))
        for i, row in enumerate(constructor_rows):
            self._constructor_table.setItem(i, 0, cell(str(row.position)))
            self._constructor_table.setItem(i, 1, cell(team_display_name(row.team_id)))
            self._constructor_table.setItem(i, 2, cell(str(row.points)))
        fit_table_height(self._constructor_table)
        self._constructor_table.setVisible(bool(constructor_rows))
        self._constructor_empty.setVisible(not constructor_rows)

    def _league_roster_for_detail(self, season, rounds) -> LeagueRoster | None:
        """Return a roster for roster-aware seasons and update the roster status panel.

        Roster-aware modes are LEAGUE and GRAND_PRIX (see ``ROSTER_SEASON_MODES``); both are run
        against other people and resolve standings by roster. Read-only: a saved file is loaded,
        otherwise a capture-seeded roster is shown without writing. The file is created only by the
        Create/Import buttons.
        """
        is_roster_mode = season.mode in ROSTER_SEASON_MODES
        self._roster_panel.setVisible(is_roster_mode)
        if not is_roster_mode:
            return None

        try:
            roster = self._season_rosters.roster_for(
                season, rounds, self._seasons.list_seasons
            )
        except (OSError, ValueError) as exc:
            self._roster_status.setText("Roster could not be loaded.")
            self._roster_create_btn.setVisible(False)
            QMessageBox.warning(self, "League roster", f"Could not load roster:\n\n{exc}")
            return LeagueRoster()

        saved = self._season_rosters.has_roster(season.season_id)
        self._roster_create_btn.setVisible(not saved)
        if saved:
            path = self._season_rosters.path_for(season.season_id)
            self._roster_status.setText(f"Roster: {path} ({len(roster.members)} members)")
        else:
            self._roster_status.setText(
                f"No roster file yet — showing {len(roster.members)} members seeded from "
                "captures. Create the file to hand-edit names and aliases."
            )
        return roster

    def _create_roster_file(self) -> None:
        """Write the capture-seeded roster to its canonical JSON so it can be hand-edited."""
        if self._season_id is None:
            return
        season = self._seasons.get_season(self._season_id)
        if season is None:
            return
        rounds = self._seasons.rounds_with_results(self._season_id, self._sessions)

        try:
            roster = self._season_rosters.create_from_captures(
                season, rounds, self._seasons.list_seasons
            )
        except (OSError, ValueError) as exc:
            QMessageBox.warning(
                self, "Create roster file", f"Could not create roster file:\n\n{exc}"
            )
            return

        QMessageBox.information(
            self,
            "Create roster file",
            f"Created a roster file with {len(roster.members)} members:\n\n"
            f"{self._season_rosters.path_for(self._season_id)}",
        )
        self.load(self._season_id)

    def _import_roster_csv(self) -> None:
        """Import a user-selected CSV into the current season's canonical roster JSON."""
        if self._season_id is None:
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import roster CSV",
            "",
            "CSV files (*.csv);;All files (*)",
        )
        if not path:
            return

        try:
            roster = self._season_rosters.import_csv(self._season_id, path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(
                self,
                "Import roster CSV",
                f"Could not import roster CSV:\n\n{exc}",
            )
            return

        QMessageBox.information(
            self,
            "Import roster CSV",
            f"Imported {len(roster.members)} roster members.",
        )
        self.load(self._season_id)

    def _on_calendar_activated(self, row: int, _column: int) -> None:
        """Request the weekend view for the activated round."""
        if self._season_id is None:
            return
        item = self._calendar_table.item(row, 0)
        if item is None:
            return
        try:
            round_number = int(item.text())
        except ValueError:
            return
        self.weekend_requested.emit(self._season_id, round_number)


def _round_result_summary(round, name_of=lambda entry: entry.driver_name) -> str:
    """Return the calendar result cell: the Grand Prix winner/team, pending, or dash.

    Only the Grand Prix counts here - a Sprint Race is a separate result and must not stand in
    for the main race (both report ``SessionType.RACE``, so they're told apart by their position
    in the weekend). A captured Sprint with the Grand Prix still to come reads "Race pending".
    """
    gp = grand_prix_session(round.sessions)
    if gp is not None and (summary := race_winner_summary(gp, name_of)) is not None:
        return summary
    if round.sessions:
        return "Race pending"
    return "—"
