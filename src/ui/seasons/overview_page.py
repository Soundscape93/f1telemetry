"""The seasons overview page - a scrollable list of season cards, or an empty state."""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..components import clear_layout
from ..style import MUTED_TEXT_QSS
from .labels import format_label, season_title


class OverviewPage(QWidget):
    """Browse all seasons (or an empty state); create and delete live here.

    Emits ``create_requested`` and ``season_requested(season_id)`` for navigation; deletion stays
    on this page (mutate the store, then reload in place).
    """

    create_requested = Signal()
    season_requested = Signal(int)

    def __init__(self, season_store, parent=None) -> None:
        """Initialize the overview page."""
        super().__init__(parent)
        self._seasons = season_store

        outer = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("Seasons")
        title.setStyleSheet("font-size: 20px; font-weight: 600")
        new_btn = QPushButton("Create new season")
        new_btn.clicked.connect(self.create_requested)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(new_btn)
        outer.addLayout(header)

        self._body = QVBoxLayout()
        body_host = QWidget()
        body_host.setLayout(self._body)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(body_host)
        outer.addWidget(scroll, 1)

    def reload(self) -> None:
        """Rebuild the body with current seasons or the empty state."""
        clear_layout(self._body)
        seasons = self._seasons.list_seasons()

        if not seasons:
            self._body.addStretch(1)
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
            blurb.setStyleSheet(f"font-size: 14px; {MUTED_TEXT_QSS}")
            self._body.addWidget(heading)
            self._body.addWidget(blurb)
            self._body.addStretch(1)
            return

        for season in seasons:
            self._body.addWidget(self._season_card(season))
        self._body.addStretch(1)

    def _season_card(self, season) -> QWidget:
        """Return a row with a clickable season card and a delete button."""
        subtitle = f"{format_label(season.game_format)}   ·   {len(season.rounds)} rounds"
        card = QPushButton(f"{season_title(season)}      —      {subtitle}")
        card.setStyleSheet("QPushButton { text-align: left; padding: 12px 14px; }")
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.clicked.connect(partial(self.season_requested.emit, season.season_id))

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
        """Confirm, then delete a season and reload the list."""
        season = self._seasons.get_season(season_id)
        if season is None:
            return
        confirm = QMessageBox.question(
            self,
            "Delete season",
            f"Delete {season_title(season)}?\n\nThis removes its calendar and round "
            "assignments. Your captured sessions are not deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._seasons.delete_season(season_id)
        self.reload()
