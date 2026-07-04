"""The custom-calendar picker - a rules-driven widget for authoring a season's calendar.

One widget, two faces, chosen by the domain ``CalendarRules`` for the season's (mode, format):

- a **checklist** for a preset subset (Career / My Team): tick a fixed-length subset of the
  official calendar, whose order is frozen; valid only at exactly one of the allowed lengths.
- a **sandbox** for Grand Prix / League: add tracks from a pool into an ordered, drag-reorderable
  list, repeats allowed, bounded by the rules' min/max.

Both expose the same contract, so ``CalendarPicker`` just swaps between them and forwards
``rounds()``. It emits ``validityChanged(bool)`` whenever the current selection crosses the
valid/invalid line so a host form can enable or disable its submit button. The widget is
view-agnostic and store-agnostic: it deals only in track IDs and hands back ``SeasonRound``s, so
the create page (and, later, an edit-calendar surface) can reuse it unchanged.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...domain.calendars import CalendarRules, CalendarStyle, calendar_from_track_ids
from ...domain.season import SeasonRound
from ...protocol.reference import track_name

_TRACK_ID_ROLE = Qt.ItemDataRole.UserRole


def _track_item(track_id: int, text: str | None = None) -> QListWidgetItem:
    """A list item carrying a track ID in its data role, labelled by track name unless overridden."""
    item = QListWidgetItem(text if text is not None else track_name(track_id))
    item.setData(_TRACK_ID_ROLE, track_id)
    return item


class _ChecklistPicker(QWidget):
    """Preset-subset face: check a fixed-length subset of the official calendar (order frozen)."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._allowed_lengths: tuple[int, ...] = ()
        self._configuring = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._hint = QLabel()
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)
        self._list = QListWidget()
        layout.addWidget(self._list)
        self._count = QLabel()
        layout.addWidget(self._count)

        self._list.itemChanged.connect(self._on_changed)

    def configure(self, rules: CalendarRules, seed_track_ids) -> None:
        """Rebuild the checklist from ``rules.pool`` (in canonical order), pre-checking the seed."""
        self._configuring = True
        self._allowed_lengths = rules.allowed_lengths or ()
        seed = set(seed_track_ids)
        self._hint.setText(
            "Pick the tracks for this season. The order is fixed to the official calendar; "
            f"the count must be exactly {', '.join(map(str, self._allowed_lengths))}."
        )
        self._list.clear()
        for track_id in rules.pool:
            item = _track_item(track_id)
            item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            item.setCheckState(
                Qt.CheckState.Checked if track_id in seed else Qt.CheckState.Unchecked
            )
            self._list.addItem(item)
        self._configuring = False
        self._refresh()

    def _checked_ids(self) -> list[int]:
        return [
            self._list.item(i).data(_TRACK_ID_ROLE)
            for i in range(self._list.count())
            if self._list.item(i).checkState() == Qt.CheckState.Checked
        ]

    def _on_changed(self, _item) -> None:
        if self._configuring:
            return
        self._refresh()
        self.changed.emit()

    def _refresh(self) -> None:
        count = len(self._checked_ids())
        suffix = "" if self.is_valid() else "  —  pick exactly " + ", ".join(
            map(str, self._allowed_lengths)
        )
        self._count.setText(f"{count} selected{suffix}")

    def is_valid(self) -> bool:
        return len(self._checked_ids()) in self._allowed_lengths

    def rounds(self) -> tuple[SeasonRound, ...]:
        return calendar_from_track_ids(self._checked_ids())


class _SandboxPicker(QWidget):
    """Sandbox face: add tracks from a pool into an ordered, reorderable list (repeats allowed)."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._min_rounds = 1
        self._max_rounds: int | None = None
        self._configuring = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._hint = QLabel()
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        lists = QHBoxLayout()
        self._pool = QListWidget()
        self._pool.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._pool.itemDoubleClicked.connect(lambda _: self._add_selected())
        lists.addWidget(self._pool, 1)

        mid = QVBoxLayout()
        mid.addStretch(1)
        self._add_btn = QPushButton("Add →")
        self._add_btn.clicked.connect(self._add_selected)
        mid.addWidget(self._add_btn)
        mid.addStretch(1)
        lists.addLayout(mid)

        right = QVBoxLayout()
        self._calendar = QListWidget()
        self._calendar.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._calendar.model().rowsInserted.connect(self._on_rows_changed)
        self._calendar.model().rowsRemoved.connect(self._on_rows_changed)
        right.addWidget(self._calendar)
        row_btns = QHBoxLayout()
        for text, slot in (
            ("↑", self._move_up),
            ("↓", self._move_down),
            ("Remove", self._remove_selected),
        ):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            row_btns.addWidget(btn)
        right.addLayout(row_btns)
        lists.addLayout(right, 1)
        layout.addLayout(lists)

        self._count = QLabel()
        layout.addWidget(self._count)

    def configure(self, rules: CalendarRules, seed_track_ids) -> None:
        """Fill the pool from ``rules.pool`` and seed the ordered calendar list."""
        self._configuring = True
        self._min_rounds = rules.min_rounds
        self._max_rounds = rules.max_rounds
        cap = "no fixed limit" if self._max_rounds is None else f"up to {self._max_rounds}"
        self._hint.setText(
            f"Add tracks in any order ({cap}); the same track may appear more than once. "
            "Drag rows or use ↑/↓ to reorder."
        )
        self._pool.clear()
        for track_id in rules.pool:
            self._pool.addItem(_track_item(track_id))
        self._calendar.clear()
        for track_id in seed_track_ids:
            self._calendar.addItem(_track_item(track_id))
        self._configuring = False
        self._refresh()

    def _at_capacity(self) -> bool:
        return self._max_rounds is not None and self._calendar.count() >= self._max_rounds

    def _add_selected(self) -> None:
        for item in self._pool.selectedItems():
            if self._at_capacity():
                break
            self._calendar.addItem(_track_item(item.data(_TRACK_ID_ROLE)))

    def _remove_selected(self) -> None:
        for item in self._calendar.selectedItems():
            self._calendar.takeItem(self._calendar.row(item))

    def _move_up(self) -> None:
        self._move(-1)

    def _move_down(self) -> None:
        self._move(+1)

    def _move(self, delta: int) -> None:
        row = self._calendar.currentRow()
        target = row + delta
        if row < 0 or not (0 <= target < self._calendar.count()):
            return
        item = self._calendar.takeItem(row)
        self._calendar.insertItem(target, item)
        self._calendar.setCurrentRow(target)

    def _on_rows_changed(self, *_args) -> None:
        if self._configuring:
            return
        self._refresh()
        self.changed.emit()

    def _refresh(self) -> None:
        count = self._calendar.count()
        for i in range(count):
            item = self._calendar.item(i)
            item.setText(f"{i + 1}. {track_name(item.data(_TRACK_ID_ROLE))}")
        self._add_btn.setEnabled(not self._at_capacity())
        cap = "" if self._max_rounds is None else f" / {self._max_rounds}"
        self._count.setText(f"{count}{cap} rounds")

    def is_valid(self) -> bool:
        count = self._calendar.count()
        if count < self._min_rounds:
            return False
        return self._max_rounds is None or count <= self._max_rounds

    def rounds(self) -> tuple[SeasonRound, ...]:
        ids = [self._calendar.item(i).data(_TRACK_ID_ROLE) for i in range(self._calendar.count())]
        return calendar_from_track_ids(ids)


class CalendarPicker(QWidget):
    """Rules-driven calendar authoring widget; swaps between the checklist and sandbox faces.

    ``set_rules(rules, seed_track_ids)`` configures the matching face; ``rounds()`` returns the
    authored calendar; ``validityChanged(bool)`` fires when the selection crosses valid/invalid.
    """

    validityChanged = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rules: CalendarRules | None = None
        self._seed: tuple[int, ...] = ()
        self._last_valid: bool | None = None

        self._stack = QStackedWidget()
        self._checklist = _ChecklistPicker()
        self._sandbox = _SandboxPicker()
        self._stack.addWidget(self._checklist)
        self._stack.addWidget(self._sandbox)
        for face in (self._checklist, self._sandbox):
            face.changed.connect(self._emit_validity)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

    def set_rules(self, rules: CalendarRules, seed_track_ids) -> None:
        """Configure the face matching ``rules.style`` and seed it, then re-announce validity."""
        self._rules = rules
        self._seed = tuple(seed_track_ids)
        face = self._checklist if rules.style is CalendarStyle.PRESET_SUBSET else self._sandbox
        face.configure(rules, self._seed)
        self._stack.setCurrentWidget(face)
        self._last_valid = None  # force a fresh announcement for the newly-shown face
        self._emit_validity()

    def reset(self) -> None:
        """Re-apply the last rules and seed, if any."""
        if self._rules is not None:
            self.set_rules(self._rules, self._seed)

    def _current(self):
        return self._stack.currentWidget()

    def _emit_validity(self) -> None:
        valid = self._current().is_valid()
        if valid != self._last_valid:
            self._last_valid = valid
            self.validityChanged.emit(valid)

    def is_valid(self) -> bool:
        return self._current().is_valid()

    def rounds(self) -> tuple[SeasonRound, ...]:
        return self._current().rounds()
