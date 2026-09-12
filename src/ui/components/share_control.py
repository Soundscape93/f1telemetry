"""Getting a share image out of the app - onto the clipboard, or into a PNG file (E19).

**The clipboard is the real path.** A result goes straight into the league chat, so **Copy image**
puts the rendered image on the clipboard and touches no file. **Save image…** is the fallback, and
opens in ``paths.exports_dir()`` - per-user data like ``rosters/`` and ``logs/``.

**A save never overwrites without asking.** The name it offers is always free
(``share_document.unique_path``), so saving the same session twice proposes ``…-2.png``; replacing a
file takes choosing it in the dialog, whose own confirmation is left on. The write goes through
``QSaveFile``, so a failed save leaves neither a truncated PNG nor a damaged file it was replacing.

**Both say whether they worked.** Success is a muted note beside the button that clears itself after
a few seconds, since the page carries on and nothing should need dismissing. Failure is a message
box, because a result that silently never reached the chat is the failure that matters. A copy only
counts as done when the clipboard hands the image back: on Windows another program can hold the
clipboard open, the copy then fails without a word, and the clipboard still holds what it held.

**One control, reused.** ``ShareControl`` builds its document through a callable when clicked, so the
image is of what is stored at that moment and the page hosting it keeps no state for it. It is the
Laps page's "Compare ▾" button again - a tool button with an instant-popup menu and no stylesheet
(core invariant #11, A4b) - and a later export adds a menu entry rather than a second control.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QIODevice, QSaveFile, QTimer
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QToolButton,
    QWidget,
)

from ... import paths
from ..style import MUTED_TEXT_QSS
from .share_document import ShareDocument, unique_path
from .share_image import render_document

_STATUS_MS = 6000           # how long "Copied" / "Saved" stays beside the button
_PNG_FILTER = "PNG image (*.png)"


def copy_image(image: QImage) -> bool:
    """Put ``image`` on the clipboard; True only if the clipboard then hands it back.

    Compared by size rather than tested for "not empty", because a copy that failed leaves the
    clipboard's previous content in place - quite possibly an earlier image.
    """
    clipboard = QGuiApplication.clipboard()
    clipboard.setImage(image)
    held = clipboard.image()
    return not held.isNull() and held.size() == image.size()


def save_image(parent: QWidget, image: QImage, stem: str) -> Path | None:
    """Ask where to save ``image`` and write it there as a PNG.

    The dialog opens in the exports folder on a name nothing has taken yet. Returns the path
    written, or None when the user cancelled or the write failed - a failure is said, in a message
    box, before returning.
    """
    path = _ask_save_path(parent, unique_path(paths.exports_dir(), stem))
    if path is None:
        return None
    problem = _write_png(image, path)
    if problem is not None:
        QMessageBox.warning(parent, "Image not saved",
                            f"The image couldn't be written to\n{path}\n\n{problem}\n\n"
                            "Choose another folder and try again.")
        return None
    return path


class ShareControl(QWidget):
    """"Share" - copy or save a result as an image - and a note saying what happened."""

    def __init__(self, document_fn: Callable[[], ShareDocument | None], parent=None) -> None:
        super().__init__(parent)
        self._document_fn = document_fn

        self._status = QLabel()
        # MUTED_TEXT_QSS states its colour outright - the one stylesheet invariant #11 allows.
        self._status.setStyleSheet(MUTED_TEXT_QSS)
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(_STATUS_MS)
        self._status_timer.timeout.connect(self._clear_status)

        button = QToolButton()
        button.setText("Share ▾")
        button.setToolTip("Copy this image to the clipboard, or save it as a PNG.")
        # No stylesheet - it would freeze the button's text colour at apply time (A4b). The same
        # minimum size off the natural hint as the Laps page's "Compare ▾".
        button.setMinimumHeight(button.sizeHint().width() + 12, button.sizeHint().height() + 4)
        menu = QMenu(button)
        menu.addAction("Copy image").triggered.connect(self._copy)
        menu.addAction("Save image…").triggered.connect(self._save)
        button.setMenu(menu)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._status)
        layout.addWidget(button)

    def _copy(self) -> None:
        rendered = self._rendered()
        if rendered is None:
            return
        if copy_image(rendered[1]):
            self._show_status("Copied to clipboard")
            return
        QMessageBox.warning(self, "Image not copied",
                            "The clipboard didn't take the image - another program may be using "
                            "it. Try again, or use Save image… instead.")

    def _save(self) -> None:
        rendered = self._rendered()
        if rendered is None:
            return
        document, image = rendered
        path = save_image(self, image, document.name)
        if path is not None:
            self._show_status(f"Saved {path.name}", tooltip=str(path))

    def _rendered(self) -> tuple[ShareDocument, QImage] | None:
        """The document as it stands now, and its image - or None if there is nothing to share.

        None only when the page's subject has gone, and the page's own reload deals with that. An
        image that could not be drawn is left to fail visibly downstream: an empty clipboard reads
        as a failed copy, and a PNG that will not encode as a failed save.
        """
        document = self._document_fn()
        if document is None:
            return None
        return document, render_document(document)

    def _show_status(self, text: str, tooltip: str = "") -> None:
        self._status.setText(text)
        self._status.setToolTip(tooltip)
        self._status_timer.start()          # restarted by a second action, so each gets its time

    def _clear_status(self) -> None:
        self._status.clear()
        self._status.setToolTip("")


def _ask_save_path(parent: QWidget, suggested: Path) -> Path | None:
    """The save dialog for one PNG, opened on ``suggested``.
    
    Qt's overwrite confirmation is left on: the suggestion is always free, so the only way onto an
    existing file is to pick, and then the dialog asks.
    """
    dialog = QFileDialog(parent, "Save image", str(suggested.parent), _PNG_FILTER)
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    dialog.setDefaultSuffix("png")
    dialog.selectFile(suggested.name)
    return dialog


def _write_png(image: QImage, path: Path) -> str | None:
    """Write ``image`` to ``path`` as a PNG, all or nothing; why it failed, or None if it did not."""
    file = QSaveFile(str(path))
    if not file.open(QIODevice.OpenModeFlag.WriteOnly):
        return file.errorString()
    if not image.save(file, "PNG"):
        file.cancelWriting()
        return "The image could not be encoded as a PNG."
    if not file.commit():
        return file.errorString()
    return None
