"""The Help / About page: version, data location, and the notify-only update check.

Lives in the existing "Help" sidebar slot. The update check runs on a background
:class:`UpdateCheckWorker``, so clicking the button never blocks the GUI and the app is fully
usable offline (a failed check just shows a message).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import paths
from ..update_check import CheckStatus, releases_page
from ..user_guide import resolve_guide, resolve_notices
from ..version import __version__
from .style import MUTED_TEXT_QSS, apply_heading
from .workers import UpdateCheckWorker

_ROSTER_CSV_TEMPLATE = "name,race_number,online_names\n"

# (button text, the noun a failure message uses, tooltip, paths accessor). %LOCALAPPDATA% is
# hidden in Explorer by default, so the app opens it for the user rather than the data moving.
# Deliberately NO "Open database" action - the DB is rebuildable, not user-serviceable
# (docs/PACKAGING.md "Data layout & the database").
_FOLDER_ACTIONS = (
    ("Open data folder", "data folder",
     "Everything the app stores: database, captures, lap traces, rosters and logs.",
     paths.data_root),
    ("Open captures folder", "captures folder",
     "Your saved .f1cap recordings - these are what you can share with the league.",
     paths.captures_dir),
    ("Open logs folder", "logs folder",
     "Attach the newest log file when you report a bug.",
     paths.logs_dir),
)

_SETUP_HTML = (
    "<b>In-game telemetry settings:</b> (F1 game → Settings → Telemetry Settings):<br>"
    "- Supported Telemetry Formats: <b>2025</b> and <b>2026</b> (older formats not supported) <br>"
    "- UDP Telemetry <b>On</b> <br>"
    "- UDP Broadcast Mode <b>On</b> <br>"
    "- UDP Port <b>20777</b> <br>"
    "- Set your online name/id to <b>Public</b> so online names come through. <br><br>"
    "<b>Windows Firewall:</b> if you used the <b>installer</b>, the rule is already in place — "
    "nothing to do. With the <b>zip</b> build, Windows prompts the first time you record: click "
    "<b>Allow</b>. If you dismissed or denied it, delete the <i>f1telemetry</i> rule under "
    "Windows Defender Firewall → Inbound Rules, then press Record again.<br>"
    "Either way the rule covers <b>private</b> networks only. If Windows has your home network "
    "set to <b>Public</b>, no packets arrive and there is no error — set it to "
    "<b>Private network</b> under Settings → Network &amp; internet.<br><br>"

    "<b>League / multiplayer rostering:</b> if members don't set their online name to <b>Public</b>, "
    "import a driver roster CSV (Seasons → pick a season → import roster). <br>" 
    "The CSV needs a <b>header row</b> with columns <code>name</code>, <code>race_number</code>, "
    "and <code>online_names</code> (optional, multiple online names separated by semicolons). "
    "Column names are case-insensitive. "
    "<a href='#save-template'>Save a blank template CSV…</a><br> "    
    "<b>name</b> = canonical name shown in standings<br> "
    "<b>race_number</b> = the stable anchor <br> "
    "<b>online_names</b> = are used for standings if they are provided either by the telemetry data or the roster CSV. "
)

# The trademark/affiliation and data-responsibility notices, kept short enough to actually be
# read. The full text (incl. the LGPL notice for the bundled Qt) is in NOTICE.md - shipped
# beside the exe and opened by the Licences & notices button.
_ABOUT_HTML = (
    "F1 Telemetry is an <b>unofficial fan-made tool</b>, not affiliated with or endorsed by "
    "Formula 1, the FIA, EA or Codemasters. F1 and related marks, and all team, driver and "
    "circuit names, belong to their owners.<br><br>"
    "Results and telemetry are read from the game's UDP stream on a best-effort basis and can be "
    "incomplete — they are <b>not official results</b>. Captures can contain other players' "
    "online names; you are responsible for how you share them.<br><br>"
    "© 2026 Kevin Fust (Soundscape93). All rights reserved."
)


class HelpPage(QWidget):
    """About + notify-only update check page.
    The page asks; MainWindow owns the worker (it also owns the record/ingest jobs this must
    not run alongside) - the same emit-and-let-the-container-act split as the seasons pages. 
    """
    reingest_requested = Signal()
    import_captures_requested = Signal()
    find_moved_captures_requested = Signal()
    prune_captures_requested = Signal()
    backup_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._worker: UpdateCheckWorker | None = None

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(8)

        title = QLabel(f"F1 Telemetry")
        apply_heading(title, size_px=20)

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

        self._import_btn = QPushButton("Import captures…")
        self._import_btn.setMinimumHeight(32)
        self._import_btn.setToolTip(
            "Bring in captures a league member shared with you. Pick the folder they're in - "
            "everything new is copied into your own captures folder and read.")
        self._import_btn.clicked.connect(self.import_captures_requested)

        self._reingest_btn = QPushButton("Re-read captures")
        self._reingest_btn.setMinimumHeight(32)
        self._reingest_btn.setToolTip(
            "Rebuild your stored sessions from the saved capture files. Needed after an update "
            "that reads more from a capture; your seasons and rosters are kept.")
        self._reingest_btn.clicked.connect(self.reingest_requested)

        self._find_moved_btn = QPushButton("Find moved captures")
        self._find_moved_btn.setMinimumHeight(32)
        self._find_moved_btn.setToolTip(
            "Search a folder for capture files the app has lost track of, and point it at them "
            "again. Use this before cleaning up - a moved capture isn't a lost one.")
        self._find_moved_btn.clicked.connect(self.find_moved_captures_requested)

        self._prune_btn = QPushButton("Clean up missing captures")
        self._prune_btn.setMinimumHeight(32)
        self._prune_btn.setToolTip(
            "Forget capture files the app can no longer find, so re-reading stops listing them. "
            "Shows you the list first. No files are deleted and no sessions are lost.")
        self._prune_btn.clicked.connect(self.prune_captures_requested)

        self._backup_btn = QPushButton("Back up database…")
        self._backup_btn.setMinimumHeight(32)
        self._backup_btn.setToolTip(
            "Save a copy of your database wherever you choose - safe to do while the app is "
            "working. Attach it when you report a bug; your captures are the real source of truth.")
        self._backup_btn.clicked.connect(self.backup_requested)

        self._guide_btn = QPushButton("Open user guide")
        self._guide_btn.setMinimumHeight(32)
        self._guide_btn.setToolTip(
            "Open the full user guide - the PDF shipped next to the app, or the online copy.")
        self._guide_btn.clicked.connect(self._on_open_guide)

        self._notices_btn = QPushButton("Licences && notices")
        self._notices_btn.setMinimumHeight(32)
        self._notices_btn.setToolTip(
            "The licence for this app and the licences of the components it bundles.")
        self._notices_btn.clicked.connect(self._on_open_notices)

        folder_row = QHBoxLayout()
        folder_row.setContentsMargins(0, 0, 0, 0)
        folder_row.setSpacing(8)
        for text, noun, tip, accessor in _FOLDER_ACTIONS:
            btn = QPushButton(text)
            btn.setMinimumHeight(32)
            btn.setToolTip(tip)
            # Bind the loop variables as defaults - a late-binding closure would give every button the last folder.
            btn.clicked.connect(
                lambda _checked=False, a=accessor, n=noun: self._on_open_folder(a, n))
            folder_row.addWidget(btn)
        folder_row.addStretch(1)
        
        setup_title = QLabel("Setup / Configuration")
        apply_heading(setup_title, size_px=18)
        setup_body = QLabel(_SETUP_HTML)
        setup_body.setWordWrap(True)
        setup_body.setStyleSheet(MUTED_TEXT_QSS)
        setup_body.linkActivated.connect(self._on_setup_link)

        about_title = QLabel("About")
        apply_heading(about_title, size_px=18)
        about_body = QLabel(_ABOUT_HTML)
        about_body.setWordWrap(True)
        about_body.setStyleSheet(MUTED_TEXT_QSS)

        layout.addWidget(title)
        layout.addWidget(version)
        layout.addWidget(data_dir)
        layout.addSpacing(6)
        layout.addWidget(self._check_btn, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._status)
        layout.addSpacing(6)
        layout.addWidget(self._import_btn, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addSpacing(6)
        layout.addWidget(self._reingest_btn, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addSpacing(6)
        layout.addWidget(self._find_moved_btn, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addSpacing(6)
        layout.addWidget(self._prune_btn, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addSpacing(6)
        layout.addWidget(self._backup_btn, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addSpacing(6)
        layout.addWidget(self._guide_btn, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addSpacing(6)
        layout.addWidget(self._notices_btn, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addSpacing(6)
        layout.addLayout(folder_row)
        layout.addSpacing(6)
        layout.addWidget(setup_title)
        layout.addWidget(setup_body)
        layout.addSpacing(6)
        layout.addWidget(about_title)
        layout.addWidget(about_body)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _on_setup_link(self, href: str) -> None:
        if href == "#save-template":
            self._save_roster_template()

    def _save_roster_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save blank roster template", "roster_template.csv", "CSV files (*.csv)")
        if not path:
            return
        try:
            Path(path).write_text(_ROSTER_CSV_TEMPLATE, encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Could not save template", str(exc))

    # --- user guide + folder actions ----------------------------------------------------------------------
    
    def _on_open_guide(self) -> None:
        target = resolve_guide()
        url = QUrl.fromLocalFile(str(target.path)) if target.is_local else QUrl(target.url)
        self._open(url, "user guide")

    def _on_open_notices(self) -> None:
        target = resolve_notices()
        url = QUrl.fromLocalFile(str(target.path)) if target.is_local else QUrl(target.url)
        self._open(url, "licences and notices")

    def _on_open_folder(self, accessor, noun: str) -> None:
        try:
            folder = accessor()         # the paths accessors also create the folder
        except OSError as exc:
            QMessageBox.warning(self, "Could not open folder", str(exc))
            return
        self._open(QUrl.fromLocalFile(str(folder)), noun)

    def _open(self, url: QUrl, noun: str) -> None:
        """Hand a file or URL to the desktop, reporting the failure QDesktopServices only
        signals by returning a False (a windowed build has no console to notice it in)."""
        if not QDesktopServices.openUrl(url):
            QMessageBox.information(
                self, "Could not open",
                f"Couldn't open the {noun} automatically. It is here:\n"
                f"{url.toLocalFile() or url.toString()}")


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