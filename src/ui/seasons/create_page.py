"""The create-season form page."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...domain.calendars import official_calendar
from ...domain.season import SeasonMode
from .labels import mode_label


class CreatePage(QWidget):
    """Form for authoring a new season.

    Owns the create mutation: on submit it writes the season, then emits
    ``season_requested(season_id)`` so the container opens its detail. Cancel emits ``cancelled``.
    """

    season_requested = Signal(int)
    cancelled = Signal()

    def __init__(self, season_store, parent=None) -> None:
        """Initialize the create page."""
        super().__init__(parent)
        self._seasons = season_store

        outer = QVBoxLayout(self)

        title = QLabel("Create a new season")
        title.setStyleSheet("font-size: 20px; font-weight: 600")
        outer.addWidget(title)

        form = QFormLayout()
        self._mode_combo = QComboBox()
        for mode in SeasonMode:
            self._mode_combo.addItem(mode_label(mode), mode)
        form.addRow("Game mode:", self._mode_combo)

        self._number_spin = QSpinBox()
        self._number_spin.setRange(1, 99)
        form.addRow("Season number:", self._number_spin)

        self._nickname_edit = QLineEdit()
        self._nickname_edit.setPlaceholderText("optional")
        form.addRow("Nickname:", self._nickname_edit)
        outer.addLayout(form)

        self._cal_group = QButtonGroup(self)
        self._rb_25 = QRadioButton("All tracks — F1 25 (24 rounds)")
        self._rb_26 = QRadioButton("All tracks — F1 26 (24 rounds)")
        self._rb_custom = QRadioButton("Custom calendar — coming soon")
        self._rb_custom.setEnabled(False)
        self._rb_25.setChecked(True)
        for rb in (self._rb_25, self._rb_26, self._rb_custom):
            self._cal_group.addButton(rb)
            outer.addWidget(rb)

        outer.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.cancelled)
        create = QPushButton("Create season")
        create.setDefault(True)
        create.clicked.connect(self._create_season)
        buttons.addWidget(cancel)
        buttons.addWidget(create)
        outer.addLayout(buttons)

    def reset(self) -> None:
        """Reset the form to its default state."""
        self._mode_combo.setCurrentIndex(0)
        self._number_spin.setValue(1)
        self._nickname_edit.clear()
        self._rb_25.setChecked(True)

    def _create_season(self) -> None:
        """Create a new season from the form values and request its detail page."""
        mode = self._mode_combo.currentData()
        number = self._number_spin.value()
        nickname = self._nickname_edit.text().strip() or None
        game_format = 2025 if self._rb_25.isChecked() else 2026
        rounds = official_calendar(game_format)

        season = self._seasons.create_season(
            mode=mode,
            number=number,
            game_format=game_format,
            nickname=nickname,
            rounds=rounds,
        )
        self.season_requested.emit(season.season_id)
