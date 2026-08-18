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

from ...domain.calendars import calendar_rules, official_calendar
from ...domain.season import SeasonMode
from ..components.calendar_picker import CalendarPicker
from ..style import apply_heading
from .labels import mode_label


class CreatePage(QWidget):
    """Form for authoring a new season.

    Owns the create mutation: on submit it writes the season, then emits
    ``season_requested(season_id)`` so the container opens its detail. Cancel emits ``cancelled``.

    The calendar section is authored by an embedded ``CalendarPicker`` whose constraints depend on
    the chosen (mode, game format); the Create button follows the picker's validity.
    """

    season_requested = Signal(int)
    cancelled = Signal()

    def __init__(self, season_store, parent=None) -> None:
        """Initialize the create page."""
        super().__init__(parent)
        self._seasons = season_store

        outer = QVBoxLayout(self)

        title = QLabel("Create a new season")
        apply_heading(title, size_px=20)
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

        self._fmt_group = QButtonGroup(self)
        self._rb_25 = QRadioButton("F1 25")
        self._rb_26 = QRadioButton("F1 26")
        self._rb_25.setChecked(True)
        fmt_row = QHBoxLayout()
        for rb in (self._rb_25, self._rb_26):
            self._fmt_group.addButton(rb)
            fmt_row.addWidget(rb)
        fmt_row.addStretch(1)
        form.addRow("Game format:", fmt_row)
        outer.addLayout(form)

        self._picker = CalendarPicker()
        outer.addWidget(self._picker, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.cancelled)
        self._create_btn = QPushButton("Create season")
        self._create_btn.setDefault(True)
        self._create_btn.clicked.connect(self._create_season)
        buttons.addWidget(cancel)
        buttons.addWidget(self._create_btn)
        outer.addLayout(buttons)

        # Re-derive the calendar rules whenever the mode or format changes, and gate Create on the
        # picker's validity. buttonClicked / currentIndexChanged fire only on real changes, so the
        # one-off configuration below runs exactly once at startup.
        self._mode_combo.currentIndexChanged.connect(self._reconfigure_picker)
        self._fmt_group.buttonClicked.connect(self._reconfigure_picker)
        self._picker.validityChanged.connect(self._create_btn.setEnabled)
        self._reconfigure_picker()

    def _game_format(self) -> int:
        """Return the selected game format."""
        return 2025 if self._rb_25.isChecked() else 2026

    def _reconfigure_picker(self, *_args) -> None:
        """Re-seed the calendar picker for the current mode and format."""
        mode = self._mode_combo.currentData()
        game_format = self._game_format()
        rules = calendar_rules(mode, game_format)
        seed = [r.track_id for r in official_calendar(game_format)]
        self._picker.set_rules(rules, seed)

    def reset(self) -> None:
        """Reset the form to its default state."""
        self._mode_combo.setCurrentIndex(0)
        self._number_spin.setValue(1)
        self._nickname_edit.clear()
        self._rb_25.setChecked(True)
        self._reconfigure_picker()

    def _create_season(self) -> None:
        """Create a new season from the form values and request its detail page."""
        if not self._picker.is_valid():
            return
        mode = self._mode_combo.currentData()
        number = self._number_spin.value()
        nickname = self._nickname_edit.text().strip() or None
        game_format = self._game_format()
        rounds = self._picker.rounds()

        season = self._seasons.create_season(
            mode=mode,
            number=number,
            game_format=game_format,
            nickname=nickname,
            rounds=rounds,
        )
        self.season_requested.emit(season.season_id)
