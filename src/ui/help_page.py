"""The Help / About page: version, data location, and the notify-only update check.

Lives in the existing "Help" sidebar slot. The update check runs on a background
:class:`UpdateCheckWorker``, so clicking the button never blocks the GUI and the app is fully
usable offline (a failed check just shows a message).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import paths
from ..update_check import CheckStatus, releases_page
from ..version import __version__
from .style import MUTED_TEXT_QSS
from .workers import UpdateCheckWorker


class HelpPage(QWidget):
    """About + notify-only update check page."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._worker: UpdateCheckWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(8)

        title = QLabel(f"F1 Telemetry")
        title.setStyleSheet("font-size: 20pt; font-weight: 600;")

        version = QLabel(f"Version {__version__}")
        version.setStyleSheet(MUTED_TEXT_QSS)

        data_dir = QLabel(f"Data Folder: {paths.data_root()}")
        data_dir.setStyleSheet(MUTED_TEXT_QSS)
        data_dir.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self._check_btn = QPushButton("Check for updates")
        self._check_btn.setMinimumHeight(32)
        self._check_btn.clicked.connect(self._on_check)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setOpenExternalLinks(True)         # clickable release link in the label
        self._status.setStyleSheet(MUTED_TEXT_QSS)

        layout.addWidget(title)
        layout.addWidget(version)
        layout.addWidget(data_dir)
        layout.addSpacing(12)
        layout.addWidget(self._check_btn, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._status)
        layout.addStretch(1)

    # --- update check ---------------------------------------------------------------------------------

    def _on_check(self) -> None:
        if self._worker is not None:        # a chcek is already running
            return
        self._check_btn.setEnabled(False)
        self._status.setText("Checking for updates...")

        self._worker = UpdateCheckWorker(__version__)
        self._worker.result_ready.connect(self._on_result)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()
    
    def _on_worker_finished(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        self._check_btn.setEnabled(True)
    
    def _on_result(self, result) -> None:
        if result.status is CheckStatus.UP_TO_DATE:
            self._status.setText(f"You're up to date (version {__version__}).")
        elif result.status is CheckStatus.UPDATE_AVAILABLE:
            rel = result.release
            self._status.setText(
                f"A newer version is available: <b>{rel.version}</b> — "
                f"<a href='{rel.html_url}'>Open the download page</a>."
            )
            self._show_update_dialog(rel)
        else:
            self._status.setText(result.message or "Could not check for updates right now.")
    
    def _show_update_dialog(self, rel) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Update Available")
        box.setText(f"A newer version is available: {rel.version}")
        info = f"You have {__version__}. Latest is {rel.version}."
        if rel.notes:
            info += "\n\n" + rel.notes
        box.setInformativeText(info)
        open_btn = box.addButton("Open download page", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Close", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            QDesktopServices.openUrl(QUrl(rel.html_url))