"""The picker that puts a session into a round - and the only way into a round with no weekend.

The weekend-filtered overview shows a *weekend*, resolved from the sessions already assigned to
the round. A round with nothing assigned therefore has no weekend to show, and that is 87 of this
database's 96 rounds - the common case, and exactly the state a user needs to assign out of. This
dialog is the way in: it lists stored sessions rather than a weekend, so it works when the page
behind it has nothing to draw.

**Defaults to the round's own track, with a checkbox for the rest.** Carried over from the
round-centric page's capture picker, which had it for a good reason: a track is the one thing a
round and a recording obviously share, and it cuts the list from every stored session to a handful.
It is a filter and not a rule - the box shows everything, because a track is not a weekend.

**A session already in another round stays listed, and says so.** Picking it *moves* it, which is
the repair for a misfiled weekend; hiding it would make that session unfindable from here. The
marker doubles as the warning that Delete will refuse it (core invariant #4).

Which rows exist, in what order, and which of them are suggested is ``assignment.picker_rows`` -
a Qt-free rule with its own tests, the way ``weekend_view`` is for the page behind this. The
dialog only renders them and hands back the one that was chosen.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTableWidget,
    QVBoxLayout,
)

from ..components import cell, season_phrase, tidy_table
from ..formatting import recorded_label
from ..style import MUTED_TEXT_QSS
from .assignment import picker_rows

_SUGGESTED_TIP = ("This session's own identifiers point at this round: it was recorded in the "
                  "same career as sessions already in this season, at this round's track.")
_ATTEMPTS_TIP = ("This slot was recorded more than once. Nothing stored says which attempt "
                 "counts, so the app will not choose - assign the one you mean.")
_MOVE_TIP = ("Already assigned. Choosing it moves it here and out of that round; deleting it is "
             "refused until it is unassigned.")
_MOVE_NOTE = "A session already in another round is moved here, not copied - it belongs to one round."
_NO_TRACK_NOTE = ("Nothing stored was recorded at this round's track. Tick the box above to see "
                  "every stored session.")
_NOTHING_NOTE = "Every stored session is already in this round."


class AssignDialog(QDialog):
    """Pick one stored session to put in a round; the page then offers the rest of its weekend."""

    def __init__(self, parent, *, all_sessions, seasons, placements, target, track_id,
                 round_title: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign a session")
        self.resize(820, 440)
        self._all_sessions = all_sessions
        self._seasons = seasons
        self._seasons_by_id = {season.season_id: season for season in seasons}
        self._placements = placements
        self._target = target
        self._track_id = track_id

        layout = QVBoxLayout(self)

        question = QLabel(
            f"Which stored session belongs to {round_title}?\n\nAssigning one offers the rest of "
            "its weekend afterwards, so a whole weekend is usually one pick and one confirmation.")
        question.setWordWrap(True)
        layout.addWidget(question)

        self._all_tracks = QCheckBox("Show sessions from all tracks")
        self._all_tracks.toggled.connect(lambda _checked: self._fill())
        layout.addWidget(self._all_tracks)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Session", "Track", "Recorded", "Weekend", "Assigned to"])
        tidy_table(self._table)
        self._table.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self._table, 1)

        self._note = QLabel()
        self._note.setWordWrap(True)
        self._note.setStyleSheet(MUTED_TEXT_QSS)
        layout.addWidget(self._note)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Assign")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._fill()

    @property
    def chosen_uid(self) -> int | None:
        """The selected session's uid, or None when nothing is selected.

        A property rather than a method, and deliberately so: as a method, a caller who dropped
        the parentheses gets the bound method back, which is the silent failure that made the
        capture chooser appear to do nothing (``deleted_page._CaptureChooser.content_hash``). The
        uid is read back off the row rather than tracked, so a re-filter cannot stale it.
        """
        item = self._table.item(self._table.currentRow(), 0)
        return None if item is None else int(item.data(Qt.ItemDataRole.UserRole))

    def _fill(self) -> None:
        """(Re)build the table for the current filter, selecting the first row."""
        rows = picker_rows(self._all_sessions, self._seasons, self._placements, self._target,
                            track_id=None if self._all_tracks.isChecked() else self._track_id)
        self._table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            first = cell(f"{row.label}  —  suggested" if row.suggested else row.label)
            # The uid as a string: session uids are uint64 and the row index is not identity.
            first.setData(Qt.ItemDataRole.UserRole, str(row.session.session_uid))
            if row.suggested:
                first.setToolTip(_SUGGESTED_TIP)
            elif row.attempts > 1:
                first.setToolTip(_ATTEMPTS_TIP)
            self._table.setItem(index, 0, first)
            self._table.setItem(index, 1, cell(row.track))
            self._table.setItem(index, 2, cell(recorded_label(row.session.recorded_at)))
            self._table.setItem(index, 3, cell(row.weekend))
            where = cell(self._where(row.placement))
            if row.placement is not None:
                where.setToolTip(_MOVE_TIP)
            self._table.setItem(index, 4, where)
        if rows:
            self._table.selectRow(0)
        self._note.setText(self._footnote(rows))

    def _where(self, placement) -> str:
        """Where a session is assigned now - the marker that makes picking it a *move*."""
        if placement is None:
            return ""
        season = self._seasons_by_id.get(placement[0])
        return f"Round {placement[1]}  —  {season_phrase(season)}"

    def _footnote(self, rows) -> str:
        """The muted line under the table: why it is empty, or what picking a marked row does."""
        if not rows:
            return _NO_TRACK_NOTE if not self._all_tracks.isChecked() else _NOTHING_NOTE
        return _MOVE_NOTE if any(row.placement is not None for row in rows) else ""
