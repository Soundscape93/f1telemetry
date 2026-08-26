"""The deleted-sessions manager - what was deleted, and the two ways a row can leave this list.

A plain table rather than the overview's cards: a tombstone is four descriptive fields and a file
name, with nothing to fold open. The two actions are row buttons *and* a right-click menu - the
buttons because a page nobody can find is a page nobody uses, the menu because the weekend picker
already taught that idiom for a table of sessions.

**Restore is asked for here, never performed here.** Re-reading a league capture is minutes of
parsing, so it belongs on ``RestoreWorker``'s thread, and the window owns workers, not pages
(E1/E2 plan -> Restore orchestration). This page does only the parts that need a person and
therefore the GUI thread: confirm, and choose the capture when more than one holds the session.

**It refuses nothing itself.** A missing archive, a stale capture row, a session no capture
mentions - every refusal is decided in ``pipeline.restore_session`` and worded once, in
``formatting.restore_message``, so what this page offers and what the restore accepts cannot drift
apart. The capture column and the chooser both read ``pipeline.restorable_captures``: the same
list the restore itself resolves through, for exactly that reason.

**Forget is not Restore's sibling.** It clears the tombstone and stops - nothing comes back now,
but the session is no longer skipped, so a later import or re-read of that recording will store it
again. It exists because a session with no capture row can never be restored, and without it that
row could never leave the list (DECISIONS -> UI).
"""
from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ... import paths
from ...pipeline import restorable_captures
from ..components import cell, fit_columns, tidy_table
from ..formatting import capture_choice_label, deleted_capture_label, deleted_session_cells
from ..style import MUTED_TEXT_QSS, apply_heading

_COLUMNS = ("Session", "Track", "Recorded", "Capture", "")
_SESSION_COLUMN = 0
_CAPTURE_COLUMN = 4
_ACTION_COLUMN = 5

_EMPTY = "No deleted sessions."

# The honest limitation, stated where it is read rather than buried in a doc. The tombstone keeps
# session_type and the game reports RACE for both a Sprint Race and a Race - only the weekend
# a session sat in separates them (core invariant #5), and that went with the session. Widening the
# tombstone to carry weekend_structure is not worth it (DECISIONS -> UI).
_SPRINT_CAVEAT = (
    "A deleted Sprint Race reads as “Race” here. The game reports the same session type for a "
    "sprint and a  Race, and only the weekend it ran in tells them apart — which is gone "
    "along with the session."
)
_NO_CAPTURE_TIP = (
    "No recording in the database mentions this session, so it can never be restored. Forget "
    "removes the row; if you import or re-read that recording later, the session comes back on "
    "its own."
)
_MISSING_TIP = (
    "The recording that held this session is known, but its file can't be found. Try "
    "Help → Find moved captures, or import it again."
)
_ONE_TIP = "Restore reads this recording again."
_SEVERAL_TIP = "Several recordings hold this session. Restore will ask which one to read."

_RESTORE_TIP = "Read this session's recording again and put the session back."
_FORGET__TIP = "Stop remembering this session as deleted, without bringing it back."


class DeletedPage(QWidget):
    """Every tombstonded session, with Restore and Forget."""

    overview_requested = Signal()
    restore_requested = Signal(str, str)        # session_uid (uint64-safe), capture_path

    def __init__(self, session_store, capture_store=None, parent=None):
        super().__init__(parent)
        self._sessions = session_store
        self._captures = capture_store
        self._rows: list = []           # one DeletedSession per table row, in table order

        outer = QVBoxLayout(self)

        header = QHBoxLayout()
        back = QPushButton("← Sessions")
        back.clicked.connect(self.overview_requested.emit)
        title = QLabel("Deleted Sessions")
        apply_heading(title, size_px=20)
        header.addWidget(back)
        header.addSpacing(12)
        header.addWidget(title)
        header.addStretch(1)
        outer.addLayout(header)

        # Both carry stretch: a hidden widget can take no space, so whichever of the two is showing
        # gets the whole body without the layout spreading the other one's share around.
        self._empty = QLabel(_EMPTY)
        self._empty.setStyleSheet(MUTED_TEXT_QSS)
        outer.addWidget(self._empty, 1, Qt.AlignmentFlag.AlignTop)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        tidy_table(self._table)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_row_menu)
        session_header = self._table.horizontalHeaderItem(_SESSION_COLUMN)
        if session_header is not None:
            session_header.setToolTip(_SPRINT_CAVEAT)
        outer.addWidget(self._table, 1)

    # --- build -----------------------------------------------------------------------------------
    def reload(self) -> None:
        """Re-read the tombstones and rebuild every row (newest deletion first, from the store)."""
        self._rows = self._sessions.deleted_sessions()
        self._table.setRowCount(0)
        self._table.setRowCount(len(self._rows))
        for index, tomb in enumerate(self._rows):
            self._fill_row(index, tomb)
        fit_columns(self._table, stretch={_CAPTURE_COLUMN})         # the file name takes the slack
        self._table.resizeRowsToContents()                          # the rows carry buttons
        self._table.setVisible(bool(self._rows))
        self._empty.setVisible(not self._rows)

    def _fill_row(self, row: int, tomb) -> None:
        for column, text in enumerate(deleted_session_cells(tomb)):
            item = cell(text)
            if column == _SESSION_COLUMN:
                item.setToolTip(_SPRINT_CAVEAT)
            self._table.setItem(row, column, item)

        known, found = self._captures_for(tomb.session_uid)
        capture = cell(deleted_capture_label([meta.file_name for meta in known],
                                             [meta.file_name for meta, _path in found]))
        capture.setToolTip(_capture_tip(known, found))
        self._table.setItem(row, _CAPTURE_COLUMN, capture)
        self._table.setCellWidget(row, _ACTION_COLUMN, self._actions(tomb))

    def _captures_for(self, session_uid: int) -> tuple[list, list]:
        """Every capture row mentioning the session, and the subset whose archive is findable.

        Two reads rather than one, because the column has to tell "no recording was ever recorded"
        from "the file is gone": they are different answers with different ways out, and only the
        second is something Help → Find moved captures can fix.

        The findable half is ``pipeline.restorable_captures`` and is never re-derived here - it is
        the same list ``restore_session`` resolves through, so the file this page names is the file
        that actually gets read.
        """
        if self._captures is None:
            return [], []
        return (list(self._captures.for_session(str(session_uid))),
                 restorable_captures(session_uid, self._captures, str(paths.captures_dir())))

    def _actions(self, tomb) -> QWidget:
        """The row's two buttons, auto-raised so a column of them doesn't read as a wall."""
        host = QWidget()
        box = QHBoxLayout(host)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        for text, tip, handler in (("Restore", _RESTORE_TIP, self._restore),
                                   ("Forget", _FORGET__TIP, self._forget)):
            button = QToolButton()
            button.setText(text)
            button.setAutoRaise(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(tip)
            # No stylesheet - it woud freeze the button's text color at apply time
            button.clicked.connect(partial(handler, tomb))
            box.addWidget(button)
        box.addStretch(1)
        return host

    def _show_row_menu(self, pos) -> None:
        """The same two actions, on a right-click - the captures picker's idiom, kept constistent."""
        item = self._table.itemAt(pos)
        if item is None:
            return
        tomb = self._rows[item.row()]
        menu = QMenu(self)
        restore = menu.addAction("Restore...")
        forget = menu.addAction("Forget...")
        chosen = menu.exec(self._table.viewport().mapToGlobal(pos))
        if chosen is restore:
            self._restore(tomb)
        elif chosen is forget:
            self._forget(tomb)

    # --- actions ---------------------------------------------------------------------------------
    def _restore(self, tomb) -> None:
        """Confirm here, then ask the window to run the re-ingest on its own thread.

        Deliberately does not pre-empt a refusal. An archive that went missing since this page was
        drawn, or a capture row that turns out to be stale, are ``pipeline.restore_session``'s
        answers - decided in one place and worded in one place, arriving through the worker. The
        only thing that must be settled first is *which* file to read, because a worker thread
        cannot ask a person and a wrong guess picks the worse recording (DECISIONS -> UI).
        """
        _known, found = self._captures_for(tomb.session_uid)
        content_hash = ""
        if len(found) > 1:
            content_hash = self._choose_capture(found)
            # Anything that isn't one of the hashes just offered means "don't restore" - a cancel,
            # or a chooser that failed to hand one back. Never fall through with an empty hash: the
            # pipeline reads that as "no choice was made" and refuses as ambiguous, which the user
            # reads as their choice having been ignored, because it has been.
            if content_hash not in {meta.content_hash for meta, _path in found}:
                return
        elif not self._confirm_restore(found[0][0].file_name if found else ""):
            return
        self.restore_requested.emit(str(tomb.session_uid), content_hash)
    
    def _confirm_restore(self, file_name: str) -> bool:
        opening = (f"The recording {file_name} will be read again"
                   if file_name else "This session's recording will be read again")
        confirm = QMessageBox.question(
            self,
            "Restore session",
            f"{opening}, and the session put back with its laps and their saved traces.\n\n"
            "A league recording can take a few minutes to read, and nothing else can run while "
            "it does. Nothing already in the database is lost either way: if the recording turns "
            "out not to hold this session, it stays listed as deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        return confirm == QMessageBox.StandardButton.Yes

    def _choose_capture(self, found) -> str:
        """Ask which recording to read; "" if the user backed out.

        Never guessed at. Two copies of one session are usually a member's original plus an
        imported one, and they can differ in completeness - someone stopped recording early -
        which nothing here can tell without decompressing both. ``restorable_captures`` orders
        them newest ingest first, so the default selection is the most recently read file.
        """
        dialog = _CaptureChooser(self, found)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return ""
        return dialog.content_hash

    def _forget(self, tomb) -> None:
        """Clear the tombstone without restoring anything, then re-read the list.

        The only way a session with no capture row can ever leave this page, and a different thing
        from Restore in a way the dialog has to say outright: "Forget" reads just as easily as
        "delete it for good", and it is the opposite - the session stops being skipped, so a later
        import or re-read of its recording brings it back.
        """
        confirm = QMessageBox.question(
            self,
            "Forget this deleted session",
            "Stop remembering this session as deleted?\n\n"
            "It does not come back now — its stored results are still gone. What changes is that "
            "it is no longer skipped: if you import or re-read the recording that held it, the "
            "session will be stored again.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._sessions.restore(tomb.session_uid)        # clears the tombstonde, and only that
        self.reload()


class _CaptureChooser(QDialog):
    """Which of several recordings to restore from, one line each, newest ingest preselected."""

    def __init__(self, parent, found):
        super().__init__(parent)
        self.setWindowTitle("Choose a recording")
        layout = QVBoxLayout(self)

        question = QLabel(
            "More than one recording holds this session. They can differ — someone may have "
            "stopped recording early — and telling which is better means reading both, so the "
            "app won't guess.")
        question.setWordWrap(True)
        layout.addWidget(question)

        self._list = QListWidget()
        for meta, _path in found:
            item = QListWidgetItem(capture_choice_label(meta))
            # The hash, never the row index or the path: content is the identity files can move.
            item.setData(Qt.ItemDataRole.UserRole, meta.content_hash)
            self._list.addItem(item)
        self._list.setCurrentRow(0)             # restorable_captures orders newest ingest first
        self._list.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self._list)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                    | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Restore")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def content_hash(self) -> str:
        """The chosen capture's identity - the hash, never the path, because files move.

        A property rather than a method, and deliberately so: as a method, a caller who dropped the
        parentheses got the bound method back. PySide6 cannot convert one for a ``Signal(str, str)``
        and passes an **empty string** instead of raising, so the pipeline saw "no choice made" and
        refused the restore as ambiguous - the chooser appearing to do nothing at all.
        """
        item = self._list.currentItem()
        return "" if item is None else str(item.data(Qt.ItemDataRole.UserRole))


def _capture_tip(known, found) -> str:
    """Why the capture cell reads the way it does, the part that decides what the row can do."""
    if not known:
        return _NO_CAPTURE_TIP
    if not found:
        return _MISSING_TIP
    return _SEVERAL_TIP if len(found) > 1 else _ONE_TIP
