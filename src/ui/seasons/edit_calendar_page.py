"""Re-author an existing season's calendar, with the rounds that hold results locked in place."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...domain.calendars import (
    CalendarConflictError,
    calendar_rules,
    describe_conflicts,
    locked_rounds,
)
from ...protocol.reference import track_name
from ..components.calendar_picker import CalendarPicker
from ..style import MUTED_TEXT_QSS, apply_heading
from .labels import season_title


class EditCalendarPage(QWidget):
    """Edit one season's calendar; emits ``saved`` / ``cancelled`` with the season id.

    **Calendar only, by design** (PRIORITIES -> E6). Mode, number, nickname and game format stay
    fixed: changing the format would move the track pool out from under the calendar (Madrid is
    2026-only), which is a separate feature. A season created with the wrong mode or format is
    deleted and recreated.

    Validation happens on save rather than while editing. ``SeasonStore.set_calendar`` is the one
    enforcement point and raises ``CalendarConflictError``, so this page cannot forget the rule and
    a future caller cannot bypass it. The locked rounds are *also* named up front, so the
    constraint is visible before the user invests effort in an edit that will be refused.
    """

    saved = Signal(int)
    cancelled = Signal(int)

    def __init__(self, season_store, parent=None):
        super().__init__(parent)
        self._seasons = season_store
        self._season_id: int | None = None

        outer = QVBoxLayout(self)

        header = QHBoxLayout()
        back = QPushButton("← Season")
        back.clicked.connect(self._cancel)
        self._title = QLabel()
        apply_heading(self._title, size_px=20)
        header.addWidget(back)
        header.addSpacing(12)
        header.addWidget(self._title)
        header.addStretch(1)
        outer.addLayout(header)

        self._locked_notes = QLabel()
        self._locked_notes.setWordWrap(True)
        self._locked_notes.setStyleSheet(MUTED_TEXT_QSS)
        outer.addWidget(self._locked_notes)

        self._picker = CalendarPicker()
        outer.addWidget(self._picker, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self._cancel)
        self._save_btn = QPushButton("Save calendar")
        self._save_btn.setDefault(True)
        self._save_btn.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(self._save_btn)
        outer.addLayout(buttons)

        self._picker.validityChanged.connect(self._save_btn.setEnabled)

    def load(self, season_id: int) -> None:
        """Seed the picker from the season's stored calendar and name its locked rounds."""
        season = self._seasons.get_season(season_id)
        if season is None:
            self.cancelled.emit(season_id)
            return
        self._season_id = season_id
        self._title.setText(f"Edit calendar — {season_title(season)}")

        rules = calendar_rules(season.mode, season.game_format)
        self._picker.set_rules(rules, [r.track_id for r in season.rounds])

        assigned = {number for number, _uid in self._seasons.assignments_for_season(season_id)}
        self._locked_notes.setText(_locked_note_text(locked_rounds(season.rounds, assigned)))

    
    def _cancel(self) -> None:
        if self._season_id is not None:
            self.cancelled.emit(self._season_id)

    def _save(self) -> None:
        """Write the authored calendar, refusing an edit that would break a stored result."""
        if self._season_id is None or not self._picker.is_valid():
            return
        try:
            self._seasons.set_calendar(self._season_id, self._picker.rounds())
        except CalendarConflictError as exc:
            QMessageBox.warning(
                self,
                "Calendar can't be changed",
                "These rounds already have sessions assigned, so they have to keep both their "
                "position and their track:\n\n"
                f"{describe_conflicts(exc.conflicts)}\n\n"
                "Put them back where they were, or unassign their sessions first — open the "
                "round's weekend to do that.",
            )
            return
        self.saved.emit(self._season_id)


def _locked_note_text(locked: tuple) -> str:
    """The note shown before any edit, so the constraint isn't first met as a rejected save."""
    if not locked:
        return "No sessions are assigned yet, so this calendar can be freely edited."
    rounds = ", ".join(f"round {r.round_number} ({track_name(r.track_id)})" for r in locked)
    verb = "has" if len(locked) == 1 else "have"
    return (
        f"{rounds} already {verb} sessions assigned and must keep both position and track. "
        "Everything else can be added, removed or reordered."
    )
