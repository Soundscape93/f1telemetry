"""The application's main window - a sidebar shell with the record control always in reach.

A single QMainWindow hosts everything: a slim header carrying the record/stop button and a 
status line (shown on every page, so a capture can be started or stopped without navigating
back), a left sidebar selecting the active section, and a stacked content area that swaps pages
in place rather than opening new windows. Recording still runs on a background thread and stops
cleanly; when it ends the capture is parsed, assembled, and persisted in a DB (the .f1cap is kept,
for later re-ingest if desired) and the status line shows what was stored.

Of the sibebar section, Seasons is the first view, the rest are placeholders for future work.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from f1telemetry.src.capabilities import log_capabilities

from .workers import ImportWorker, IngestWorker, RecorderWorker, ReingestWorker, RelocateWorker
from ..storage.seasons import SeasonStore
from ..storage.sessions import SessionStore
from ..storage.laps import LapStore
from ..storage.captures import CaptureStore
from .seasons import SeasonsView
from .sessions import SessionsView
from .laps import LapsView
from .help_page import HelpPage
from .style import MUTED_TEXT_QSS, apply_heading
from .. import paths

# Data paths (DB, captures, lap traces, rosters) resolve through ``paths`` so a frozen build
# writes to the per-user data dir while dev keeps using the workspace-root layout.
_HOST = "0.0.0.0"
_PORT = 20777
# How long a recording may sit at zero datagrams before the status line stops saying "waiting" and
# starts naming likely causes. Long enough not to fire between sessions on track, short enough that
# a tester notices before filing a bug (docs/PACKAGING.md, C8b).
_NO_TELEMETRY_HINT_MS = 25_000

log = logging.getLogger(__name__)

# sidebar sections, on order. Seasons is real; reast are placeholders for future work.
_SECTIONS = ["Dashboard", "Seasons", "Sessions", "Laps", "Analytics", "Help", "Bug report"]


class _PlaceholderPage(QWidget):
    """A placeholder page for a sidebar section that isn't implemented yet."""
    def __init__(self,  title: str, subtitle: str = "Coming soon", parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        heading = QLabel(title)
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        apply_heading(heading, size_px=20)
        sub = QLabel(subtitle)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(MUTED_TEXT_QSS)
        layout.addWidget(heading)
        layout.addWidget(sub)
        layout.addStretch(1)


class MainWindow(QMainWindow):
    """The main window of the application, with a sidebar and a stacked content area."""
    def __init__(self) -> None:
        """Initialize the main window and its UI components."""
        super().__init__()
        self.setWindowTitle("F1 Telemetry")
        self.resize(900, 600)

        self._recorder: RecorderWorker | None = None
        self._ingest: IngestWorker | None = None
        self._reingest: ReingestWorker | None = None
        self._reingest_dialog: QProgressDialog | None = None
        self._relocate: RelocateWorker | None = None
        self._relocate_dialog: QProgressDialog | None = None
        self._import: ImportWorker | None = None
        self._import_dialog: QProgressDialog | None = None

        # Resolve the per user data pahts once; the workers reuse them on their own threads.
        self._db_url = paths.db_url()
        self._trace_dir = str(paths.trace_dir())

        # Stores the UI reads on the GUI thread. The IngestWorker keeps its own store on its
        # own thread (SQLite dislikes a connecetion shared across threads); these point to the same DB file.
        self._season_store = SeasonStore(self._db_url)
        self._session_store = SessionStore(self._db_url)
        # The UI reads lap/traces on the GUI thread from its own LapStore (same DB file and
        # trace_dir the IngestWorker writes to). Consumed by the LapsView; disposed on close.
        self._lap_store = LapStore(self._db_url, trace_dir=self._trace_dir)
        # The sessions detail page resolves "which capture did this come from?" on the GUI
        # thread; the workers keep building their own short-lived stores on their own threads.
        self._capture_store = CaptureStore(self._db_url)

        self.setCentralWidget(self._build_central())

        # Two deferred checks, in this order: what this build can *do*, then whether its stored
        # data needs rebuilding. A build that lost pyqtgraph is worth saying before offering a
        # multi-minute re-ingest. Both wait one event-loop turn so the window is painted before
        # any dialog appears - and the pipeline one must additionally run after every store's
        # constructor has done create_all + ensure_schema (the silent additive migration must
        # precede the pipeline-version comparison).
        QTimer.singleShot(0, self._check_capabilities)
        QTimer.singleShot(0, self._check_pipeline_version)

    # --- layout ------------------------------------------------------------

    def _build_central(self) -> QWidget:
        """Build the central widget with a header, sidebar, and stacked content area."""
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())
        root.addWidget(_line(QFrame.Shape.HLine))

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._sidebar = QListWidget()
        self._sidebar.setFixedWidth(170)
        self._sidebar.setFrameShape(QFrame.Shape.NoFrame)
        # Row metrics without a stylesheet. Any stylesheet hands the widget to QStyleSheetStyle,
        # which caches a palette at apply time - which is why these labels stayed white on a light
        # theme and black on a dark one (A4b). The size hint reproduces the old
        # "padding: 8px 4px" exactly: 8px above and below the text, 4px either side.
        row_height = self._sidebar.fontMetrics().height() + 16
        for name in _SECTIONS:
            item = QListWidgetItem(name)
            item.setSizeHint(QSize(0, row_height))
            self._sidebar.addItem(item)
        self._sidebar.setViewportMargins(4, 0, 4, 0)
        body.addWidget(self._sidebar)
        body.addWidget(_line(QFrame.Shape.VLine))

        self._stack = QStackedWidget()
        self._build_pages()
        body.addWidget(self._stack, 1)

        body_host = QWidget()
        body_host.setLayout(body)
        root.addWidget(body_host, 1)

        self._sidebar.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._sidebar.setCurrentRow(0)      # land on dashboard
        return central
    
    def _build_header(self) -> QWidget:
        """Build the header with a record button and a status label.
        The header is always visible, so a capture can be started or stopped from any page.
        """
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(12, 8, 12, 8)

        self._record_button = QPushButton("Record session(s)")
        self._record_button.setMinimumHeight(36)
        self._record_button.clicked.connect(self._on_button_clicked)

        self._status = QLabel("Idle")
        self._status.setWordWrap(True)

        layout.addWidget(self._record_button)
        layout.addSpacing(12)
        layout.addWidget(self._status, 1)
        return header
    
    def _build_pages(self) -> None:
        """Build the sidebar and the stacked content area with pages for each section."""
        self._seasons_view = SeasonsView(self._season_store, self._session_store, lap_store=self._lap_store)
        self._stack.addWidget(_PlaceholderPage(
            "Dashboard", "The recent sessions, laps, and analytics will be shown here."))
        self._stack.addWidget(self._seasons_view)
        self._sessions_view = SessionsView(self._session_store, self._season_store,
                                           capture_store=self._capture_store,
                                           lap_store=self._lap_store)
        self._stack.addWidget(self._sessions_view)
        self._laps_view = LapsView(self._session_store, self._lap_store)
        # Deleting a session's stored results changes which laps exist, so the laps surface's
        # canonical track-map cache has to go the same way it does after an ingest. The weekend
        # page can't reach the laps view itself - pages never reference siblings (PRIORITIES -> A1).
        self._seasons_view.sessions_changed.connect(self._laps_view.invalidate_caches)
        self._stack.addWidget(self._laps_view)
        self._stack.addWidget(_PlaceholderPage(
            "Analytics", "The analytics will be shown here, with charts and graphs."))
        self._help_page = HelpPage()
        self._help_page.reingest_requested.connect(self._on_manual_reingest)
        self._help_page.import_captures_requested.connect(self._on_import_captures)
        self._help_page.find_moved_captures_requested.connect(self._on_find_moved_captures)
        self._help_page.prune_captures_requested.connect(self._on_prune_captures)
        self._help_page.backup_requested.connect(self._on_backup_database)
        self._stack.addWidget(self._help_page)
        self._stack.addWidget(_PlaceholderPage(
            "Bug report", "The bug report form will be shown here."))
        
    # --- button / state machine ------------------------------------------------------------

    def _busy(self) -> bool:
        """Whether a job that owns stores on its own thread is running.

        One predicate rather than one copy per handler: every new worker has to be added here
        exactly once, and a guard that forgot one would let two jobs write the same SQLite file
        from two threads.
        """
        return any(worker is not None for worker in
                   (self._recorder, self._ingest, self._reingest, self._relocate, self._import))

    def _on_button_clicked(self) -> None:
        """Handle the record button click; start or stop recording depending on the current state."""
        if self._recorder is None:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self) -> None:
        """Start recording live telemetry to a .f1cap file in the captures directory."""
        capture_dir = paths.captures_dir()
        path = str(capture_dir / f"{datetime.now():%Y%m%d_%H%M%S}.f1cap")

        self._recorder = RecorderWorker(path, host=_HOST, port=_PORT)
        self._recorder.status.connect(self._on_record_status)
        self._recorder.done.connect(self._on_record_done)
        self._recorder.failed.connect(self._on_failed)
        self._recorder.start()

        self._record_packets = 0
        self._record_button.setText("Stop recording")
        self._status.setText("Recording - waiting for telemetry ...")
        # The recorder reports status only when a datagram arrives (Recorder.record loops over the
        # source), so a socket that receives nothing produces no updates at all and the label sits
        # on "waiting" forever. One deferred check turns that silence into an actionable hint.
        QTimer.singleShot(_NO_TELEMETRY_HINT_MS, self._hint_if_no_telemetry)

    def _stop_recording(self) -> None:
        """Stop recording live telemetry; the RecorderWorker will finish and emit a done signal."""
        if self._recorder is not None:
            self._record_button.setEnabled(False)
            self._status.setText("Stopping recording ...")
            self._recorder.stop()

    def _on_record_status(self, packets: int, byte_count: int, elapsed: float) -> None:
        """Update the status label with the current recording progress."""
        self._record_packets = packets
        kb = byte_count / 1024
        self._status.setText(f"Recording - {packets} packets, {kb:.0f} KB, {elapsed:.0f}s")

    def _hint_if_no_telemetry(self) -> None:
        """Name the likely causes when a recording has run a while with nothing arriving.

        The restart case is why this exists: the installer's firewall rule is not effective until
        Windows restarts, so a user who declines Setup's restart sees a recording that looks
        perfectly healthy and receives nothing (docs/PACKAGING.md, C8b). Setup asks for the
        restart, but a request that can be declined needs a backstop.

        Deliberately one line, and it points at Help - Setup rather than repeating the setup steps
        in transient status text. A stale timer from a previous recording can only fire while the
        current one is still at zero packets, in which case the hint is correct anyway.
        """
        if self._recorder is None or self._record_packets:
            return
        self._status.setText(
            "Recording - no telemetry yet. If you just installed F1 Telemetry, restart Windows. "
            "Otherwise check the game is sending, and that your network is set to Private "
            "(Help - Setup / Configuration)."
        )
    
    def _on_record_done(self, path: str, packet_count: int) -> None:
        """Handle the RecorderWorker's done signal; start ingesting the capture."""
        worker, self._recorder = self._recorder, None
        if worker is not None:
            worker.wait()  # ensure the thread has finished before deleting it

        if packet_count == 0:
            self._reset_button()
            self._status.setText(
                f"No packets captured - check that the game is running and sending telemetry to {_HOST}:{_PORT} ( set UDP to Broadcast for 0.0.0.0).")
            return
        
        self._status.setText(f"Saved {packet_count} packets. Processing capture ...")
        self._start_ingest(path)

    def _start_ingest(self, capture_path: str) -> None:
        """Start ingesting the capture file in a background thread."""
        self._ingest = IngestWorker(capture_path, self._db_url, trace_dir=self._trace_dir)
        self._ingest.done.connect(self._on_ingest_done)
        self._ingest.failed.connect(self._on_failed)
        self._ingest.start()

    def _on_ingest_done(self, descriptions: list, archive_path: str, archive_error: str) -> None:
        """Handle the IngestWorker's done signal; update the status and refresh the seasons view."""
        worker, self._ingest = self._ingest, None
        if worker is not None:
            worker.wait()  # ensure the thread has finished before deleting it
        
        self._reset_button()
        if descriptions:
            message = f"Stored {len(descriptions)} session(s): " + " ".join(descriptions)
        else:
            message = "Capture saved, but no complete session(s) found."
        if archive_path:
            message += f"Archived capture to {Path(archive_path).name}."
        elif archive_error:
            message += f"Capture kept uncompressed: {archive_error}"
        self._status.setText(message)
        self._refresh_current_view()

    def _on_failed(self, message: str) -> None:
        """Handle a failure from any worker; reset the button and show the error."""
        for attr in ("_recorder", "_ingest", "_reingest", "_relocate", "_import"):
            worker = getattr(self, attr)
            if worker is not None:
                worker.wait()  # ensure the thread has finished before deleting it
            setattr(self, attr, None)
        self._close_reingest_dialog()
        self._close_relocate_dialog()
        self._close_import_dialog()
        self._reset_button()
        self._status.setText(f"Error: {message}")

    def _reset_button(self) -> None:
        """Reset the record button to its initial state."""
        self._record_button.setText("Record session(s)")
        self._record_button.setEnabled(True)

    def _refresh_current_view(self) -> None:
        """Refresh whichever data surface is showing, after stored sessions changed.
        
        Cache invalidation runs first and unconditionally: the laps surface memoises a canonical
        track map per race weekend, and refreshing only the visible page would leave that cache
        stale unit the next launch (PRIORITIES -> ALL).
        """
        self._laps_view.invalidate_caches()
        current = self._stack.currentWidget()
        if current is self._seasons_view:
            self._seasons_view.refresh()
        elif current is self._sessions_view:
            self._sessions_view.refresh()
        elif current is self._laps_view:
            self._laps_view.refresh()

    def _check_capabilities(self) -> None:
        """Log what this build can do, and say so once when a piece is missing.
        
        A packaged build can silently lose a lazily-imported dependency or a bundled asset
        (docs/PACKAGING.md "Risks & fallbacks"); the user then meets the fallback with no
        explanation and reports it as a bug in the feature. Logged every launch, dialogued only
        wehen something is actually degraded: the log line is what a tester report needs, the 
        dialog is what stops a silent downgrade going unnoticed.
        """
        from ..capabilities import check_capabilities, degraded, log_capabilities

        capabilities = check_capabilities()
        log_capabilities(capabilities)
        missing = degraded(capabilities)
        if not missing:
            return

        details = "\n\n".join(f"{c.label}: {c.consequence}" for c in missing)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Some features are unavailable")
        box.setText("This build is missing part of what it needs, so some features won't work.")
        box.setInformativeText(
            f"{details}\n\nEverything else works normally. Please report this along with the "
            "newest file from your logs folder (Help -> Open logs folder)."
        )
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()

    # --- pipeline version / guieded re-ingest ------------------------------------------------------------

    def _check_pipeline_version(self) -> None:
        """Offer a guided re-ingest when this build derives data the stored rows lack.

        Never a silent start-up gate (docs/PACKAGING.md -> Phase 2): the app is fully usable
        whatever the answer, and a failure here is logged and ignored rather than blocking
        launch. ``pipeline`` is imported inside the method, not at module scope, so the
        parse/assemble stack stays out of the start-up path (same reason as ``IngestWorker``).
        """
        from ..pipeline import PipelineState, check_pipeline_version
        from ..storage.meta import MetaStore

        try:
            with MetaStore(self._db_url) as meta_store:
                check = check_pipeline_version(meta_store, self._session_store)
        except Exception as exc:
            log.exception("Pipeline-version check failed; continuing without it")
            return

        log.info("Pipeline version: stored %s, this build %s (%s)",
                 check.stored, check.current, check.state.name)
        if check.state is PipelineState.UPGRADE_AVAILABLE:
            self._offer_reingest()
        elif check.state is PipelineState.AHEAD:
            # Written by a newer build: re-ingesting here would *downgrade* the derived data, 
            # so say nothing and touch nothing
            log.warning("Database was written by a newer pipeline (%s > %s)",
                        check.stored, check.current)

    def _offer_reingest(self) -> None:
        """Ask - never force - whether to rebuild stored data from the archived captures."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Update stored data")
        box.setText("This version reads more from your captures than your stored data holds.")
        box.setInformativeText(
            "Your saved captures can be re-read to fill in the new details. Your seasons, round "
            "assignments and rosters are kept.\n\n"
            "A full weekend can take a few minutes. The app keeps working while it runs and you "
            "can cancel at any time — or start it later from Help.")
        update_btn = box.addButton("Update now", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
        skip_btn = box.addButton("Don't ask again", QMessageBox.ButtonRole.DestructiveRole)
        box.exec()

        clicked = box.clickedButton()
        if clicked is update_btn:
            self._start_reingest()
        elif clicked is skip_btn:
            self._stamp_pipeline_version()

    def _stamp_pipeline_version(self) -> None:
        """Record this build's PIPELINE_VERSION without rebuilding anything.

        The escape hatch for someone who no longer has the capture archives (or simply doesn't
        want the rebuild): without it, a database that can never be fully rebuilt would be
        offered the same upgrade on every single launch.
        """
        from ..storage.meta import MetaStore
        from ..version import PIPELINE_VERSION

        try:
            with MetaStore(self._db_url) as meta_store:
                meta_store.set_pipeline_version(PIPELINE_VERSION)
        except Exception:
            log.exception("Could not stamp the pipeline version")

    def _on_manual_reingest(self) -> None:
        """Help -> "Re-read captures": the same guided rebuild, on demand."""
        if self._busy():
            self._status.setText("Busy - wait for the current job to finish.")
            return
        self._start_reingest()

    # --- league captures import ------------------------------------------------------------

    def _on_import_captures(self) -> None:
        """Help -> "Import captures…": pull league members' recordings into this database.

        The other half of the capture-as-interchange design (DECISIONS -> Storage), and now the
        supported way to import a capture someone sent you - it replaces the dev-only
        "Ingest .f1cap (test)" header button.

        **Scanning is synchronous, copying is not.** The scan is a directory walk, one ``stat``
        per capture and a single ``known_files()`` query, so the user is told the count and the
        size before any thread starts; the copy and the ingest are what run on a worker.

        The "Recorded by" prompt **is** the confirmation - one modal, not two. Its label already
        states what will be copied and where, so OK is the agreement and Cancel the refusal. The
        field is optional by design (PRIORITIES -> Cycle 2): blank is a good answer, and a later
        re-import can still fill it in.
        """
        from ..pipeline import find_importable_captures
        from ..storage.captures import CaptureStore

        if self._busy():
            self._status.setText("Busy - wait for the current job to finish.")
            return

        source_dir = QFileDialog.getExistingDirectory(
            self, "Choose the folder holding the captures to import", str(Path.home()))
        if not source_dir:
            return

        try:
            with CaptureStore(self._db_url) as store:
                candidates = find_importable_captures(source_dir, store)
        except Exception as exc:
            log.exception("Could not scan %s for importable captures", source_dir)
            self._status.setText(f"Error: could not read that folder: {exc}")
            return

        if not candidates:
            self._status.setText(
                "No new captures were found there, everything in that folder is already "
                "imported.")
            return

        noun = "capture" if len(candidates) == 1 else "captures"
        total_size = _format_size(sum(c.file_size for c in candidates))
        recorded_by, accepted = QInputDialog.getText(
            self, "Import captures",
            f"{len(candidates)} new {noun} found ({total_size}).\n"
            "They will be copied into your captures folder and read. The originals are left "
            "where they are.\n\n"
            "Who recorded them?  (optional — leave blank if you don't know)")
        if not accepted:
            return

        self._record_button.setEnabled(False)

        dialog = QProgressDialog(
            "Importing captures …\nLarge captures take a while — the app hasn't frozen.",
            "Cancel", 0, len(candidates), self)
        dialog.setWindowTitle("Import captures")
        dialog.setWindowModality(Qt.WindowModality.NonModal)        # the rest of the app stays usable
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)          # closed when the worker reports, not when the bar fills
        dialog.setAutoReset(False)
        dialog.canceled.connect(self._cancel_import)
        dialog.show()
        self._import_dialog = dialog

        self._import = ImportWorker(
            self._db_url, candidates, trace_dir=self._trace_dir, 
            captures_dir=str(paths.captures_dir()), 
            recorded_by=recorded_by.strip() or None)
        self._import.progress.connect(self._on_import_progress)
        self._import.done.connect(self._on_import_done)
        self._import.failed.connect(self._on_failed)
        self._import.start()
        self._status.setText(f"Importing {len(candidates)} capture(s) ...")

    def _cancel_import(self) -> None:
        """Ask the import to stop; it finishes the capture it's on so nothing is left partial."""
        if self._import is not None:
            self._import.cancel()
            self._status.setText("Finishing the current capture, then stopping ...")

    def _on_import_progress(self, index: int, total: int, file_name: str) -> None:
        if self._import_dialog is None:
            return
        self._import_dialog.setMaximum(total)
        self._import_dialog.setValue(index - 1)         # index-1 finished; this one is in progress
        self._import_dialog.setLabelText(
            f"Importing capture {index} of {total}: {file_name}\n"
            "Large captures take a while — the app can be used while it runs.")

    def _on_import_done(self, summary) -> None:
        worker, self._import = self._import, None
        if worker is not None:
            worker.wait()  # ensure the thread has finished before deleting it

        self._close_import_dialog()
        self._reset_button()
        self._status.setText(_import_message(summary))
        # Unlike the prune and the search, this one really did store sessions.
        self._refresh_current_view(
        )
    
    def _close_import_dialog(self) -> None:
        if self._import_dialog is not None:
            self._import_dialog.close()
            self._import_dialog = None
        
    # --- find captures that moved ------------------------------------------------------------

    def _on_find_moved_captures(self) -> None:
        """Help -> "Find moved captures…": re-point metadata at files that moved, not vanished.

        The step that belongs *before* the prune (docs/ROADMAP -> Capture compression). A moved
        capture and a deleted one look identical at the row level, so the app offers to go and
        look before it offers to forget.

        Threaded, unlike the prune: name and size only say "worth reading", and the content hash
        that actually decides costs a decompression pass per candidate - so a captures folder
        that moved wholesale is minutes of work, not milliseconds.
        """
        if self._busy():
            self._status.setText("Busy - wait for the current job to finish.")
            return

        search_dir = QFileDialog.getExistingDirectory(
            self, "Choose a folder to search for your captures", str(paths.captures_dir()))
        if not search_dir:
            return

        self._record_button.setEnabled(False)

        dialog = QProgressDialog(
            f"Looking for your captures in\n{search_dir}", "Cancel", 0, 0, self)
        dialog.setWindowTitle("Find moved captures")
        dialog.setWindowModality(Qt.WindowModality.NonModal)        # the rest of the app stays usable
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)          # closed when the worker reports, not when the bar fils
        dialog.setAutoReset(False)
        dialog.canceled.connect(self._cancel_relocate)
        dialog.show()
        self._relocate_dialog = dialog

        self._relocate = RelocateWorker(
            self._db_url, search_dir, captures_dir=str(paths.captures_dir()))
        self._relocate.progress.connect(self._on_relocate_progress)
        self._relocate.done.connect(self._on_relocate_done)
        self._relocate.failed.connect(self._on_failed)
        self._relocate.start()
        self._status.setText("Searching for captures that moved ...")

    def _cancel_relocate(self) -> None:
        if self._relocate is not None:
            self._relocate.cancel()
            self._status.setText("Finishing the current file, then stopping ...")

    def _on_relocate_progress(self, found: int, total: int, file_name: str) -> None:
        if self._relocate_dialog is None:
            return
        self._relocate_dialog.setMaximum(total)
        self._relocate_dialog.setValue(found)
        self._relocate_dialog.setLabelText(
            f"Found {found} of {total} missing capture(s).\nChecking {file_name} …")

    def _on_relocate_done(self, summary) -> None:
        worker, self._relocate = self._relocate, None
        if worker is not None:
            worker.wait()  # ensure the thread has finished before deleting it

        self._close_relocate_dialog()
        self._reset_button()
        # No view refresh: only capture metadata moved, no session, lap or standing was touched
        self._status.setText(_relocate_message(summary))

    def _close_relocate_dialog(self) -> None:
        if self._relocate_dialog is not None:
            self._relocate_dialog.close()
            self._relocate_dialog = None
        
    # --- missing-captures prune ------------------------------------------------------------

    def _on_prune_captures(self) -> None:
        """Help -> "Clean up missing captures": forget rows whose archive can't be found.
        
        Deliberately synchronous and unthreaded: the whole pass is a handfull of DB reads plus one
        ``os.path.isfile()`` per capture, so there is nothing to keep a progress dialog busy. Its
        own short-lived ``CaptureStore`` (the ``MetaStore`` patternn from ``check_pipeline_version()``)
        - the main window doesn't otherwise hold one, and a store opened and closed inside the handler
        can't outlive the action.

        **Excplicit only** (docs/ROADMAP -> Capture compression): never on start-up, never folded
        into a re-ingest. A moved capture and a deleted one look identical at the row level, so a
        human confirms every prune.
        """
        from ..pipeline import find_missing_captures, prune_missing_captures
        from ..storage.captures import CaptureStore

        if self._busy():
            self._status.setText("Busy - wait for the current job to finish.")
            return

        captures_dir = str(paths.captures_dir())
        try:
            with CaptureStore(self._db_url) as store:
                total = len(store.list_captures())
                missing = find_missing_captures(store, captures_dir)
                if not missing:
                    self._status.setText(
                        "No captures are recorded yet - nothing to clean up." if total == 0
                        else f"All {total} recorded capture(s) were found - nothing to clean up.")
                    return
                if not self._confirm_prune(missing, total):
                    return
                summary = prune_missing_captures(
                    store, [meta.content_hash for meta in missing], captures_dir=captures_dir)
        except Exception as exc:
            log.exception("Could not clean up missing captures")
            self._status.setText(f"Error: {exc}")
            return

        # No view refresh: noting a data surface shows was touched - only capture metadata
        self._status.setText(_prune_message(summary))

    def _confirm_prune(self, missing: list, total: int) -> bool:
        """Show exactly what would be forgotten and that no file is deleted."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Clean up missing captures")
        box.setText(f"{len(missing)} of {total} recorded capture(s) can't be found.")

        info = (
            "Their entries can be removed, so re-reading your captures stops listing them.\n\n"
            "No files are deleted - this only clears the app's record of captures that are "
            "already gone. Your sessions, seasons, standings and rosters are not affected.\n\n"
            "If a capture was only moved, use \"Find moved captures…\" first and point it at "
            "the folder they're in now - then nothing is lost.")
        if len(missing) == total:
            # Every row missing is far more often a removed/disconneted drive than a mass delete.
            info = ("Every capture the app knows about is missing. That usually means the "
                    "captures folder itself moved, or is on a drive that isn't connected - "
                    "check Help -> Open captures folder before continuing.\n\n") + info
        box.setInformativeText(info)
        box.setDetailedText(
            "\n".join(f"{meta.file_name}\n    last seen: {meta.path}" for meta in missing))

        forget_btn = box.addButton(
            f"Forget {len(missing)} {'entry' if len(missing) == 1 else 'entries'}",
            QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel_btn)            # the safe answer is the one Enter picks
        box.exec()
        return box.clickedButton() is forget_btn

    def _on_backup_database(self) -> None:
        """Help -> "Back up database…": write a consistent copy wherever the user chooses.

        Deliberately **not** guarded against a running ingest, unlike the prune action. That guard
        exists because pruning mutates capture metadata a running job is also touching; a backup
        only reads, and on a WAL database ``VACUUM INTO`` takes one read transaction that neither
        blocks the writer nor tears - it simply captures the database as of the moment it began.
        Being able to do this on a busy database is the point of pairing C3 with C2.

        Synchronous for the same reason the prune is: one statement over a database measured in
        megabytes, with nothing for a progress dialog to say. Defaults to the home folder rather
        than ``data_root()`` - the data folder is hidden on Windows, and a backup you can't find
        is not a backup you can send.
        """
        from ..storage.backup import backup_database, default_backup_name

        suggested = str(Path.home() / default_backup_name())
        path, _ = QFileDialog.getSaveFileName(
            self, "Back up database", suggested, "Database files (*.db);;All files (*)")
        if not path:
            return
        try:
            # overwrite=True: getSaveFileName has already asked about an existing file.
            written = backup_database(self._db_url, path, overwrite=True)
        except Exception as exc:
            log.exception("Database backup failed")
            self._status.setText(f"Error: could not back up the database: {exc}")
            return
        size_mb = written.stat().st_size / (1024 * 1024)
        self._status.setText(f"Backed up the database to {written} ({size_mb:.1f} MB).")

    def _start_reingest(self) -> None:
        """Rebuild every stored session from its capture archive on a background thread."""
        if self._busy():
            return
        self._record_button.setEnabled(False)

        dialog = QProgressDialog(
            "Re-reading your captures …\nThis can take a few minutes — the app hasn't frozen.",
            "Cancel", 0, 0, self
        )
        dialog.setWindowTitle("Updating stored data")
        dialog.setWindowModality(Qt.WindowModality.NonModal)        # the rest of the app stays usable    
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)          # closed when the worker reports, not when the bar fills
        dialog.setAutoReset(False)
        dialog.canceled.connect(self._cancel_reingest)
        dialog.show()
        self._reingest_dialog = dialog

        self._reingest = ReingestWorker(
            self._db_url, trace_dir=self._trace_dir, captures_dir=str(paths.captures_dir()))
        self._reingest.progress.connect(self._on_reingest_progress)
        self._reingest.done.connect(self._on_reingest_done)
        self._reingest.failed.connect(self._on_failed)
        self._reingest.start()
        self._status.setText("Updating stored data from your captures ...")

    def _cancel_reingest(self) -> None:
        """Ask the pass to stop; it finishes the capture it's on so no session is left partial."""
        if self._reingest is not None:
            self._reingest.cancel()
            self._status.setText("Finishing the current capture, then stopping ...")

    def _on_reingest_progress(self, index: int, total: int, file_name: str) -> None:
        if self._reingest_dialog is None:
            return
        self._reingest_dialog.setMaximum(total)
        self._reingest_dialog.setValue(index - 1)       # index-1 finished; this one is in progress
        self._reingest_dialog.setLabelText(
             f"Re-reading capture {index} of {total}: {file_name}\n"
            "This can take a few minutes — the app can be used while it runs.")

    def _on_reingest_done(self, summary) -> None:
        worker, self._reingest = self._reingest, None
        if worker is not None:
            worker.wait()  # ensure the thread has finished before deleting it

        self._close_reingest_dialog()
        self._reset_button()
        self._status.setText(_reingest_message(summary))
        self._refresh_current_view()

    def _close_reingest_dialog(self) -> None:
        if self._reingest_dialog is not None:
            self._reingest_dialog.close()
            self._reingest_dialog = None

    # --- shutdown ------------------------------------------------------------

    def closeEvent(self, event) -> None:
        """Handle the window close event; stop any running workers and close the stores."""
        if self._recorder is not None:
            self._recorder.stop()
            self._recorder.wait()
        if self._reingest is not None:
            self._reingest.wait()
            self._reingest.wait()
        if self._relocate is not None:
            self._relocate.wait()
        if self._import is not None:
            self._import.wait()
        if self._ingest is not None:
            self._ingest.wait()
        self._session_store.close()
        self._season_store.close()
        self._lap_store.close()
        self._capture_store.close()
        super().closeEvent(event)


def _line(shape: QFrame.Shape) -> QFrame:
    """Create a horizontal or vertical line for separating sections of the UI."""
    line = QFrame()
    line.setFrameShape(shape)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line


def _reingest_message(summary) -> str:
    """One status line describing what a re-ingest pass managed to rebuild.

    Deliberately explicit about what it could NOT do: only captures whose archive is still on
    disk can be rebuilt, and the sessions behind a missing archive silently keep their old data
    unless we say so (docs/PACKAGING.md -> "Honest limit").
    """
    if summary.captures_total == 0:
        return "No captures were found to re-read - nothing to update."

    parts = [f"Updated {summary.sessions_rebuilt} of {summary.sessions_total} stored session(s) "
             f"from {summary.captures_ingested} capture(s)."]
    if summary.missing:
        parts.append(f"{len(summary.missing)} capture file(s) could not be found, so their "
                     "sessions keep the old data.")
    if summary.errors:
        parts.append(f"{len(summary.errors)} capture(s) failed: {summary.errors[0]}")
    return " ".join(parts)


def _prune_message(summary) -> str:
    """One status line for a prune pass - explicit that it removed records, not recordings."""
    if not summary.pruned:
        return (f"Nothing was removed - {len(summary.kept)} capture(s) turned up again."
                if summary.kept else "Nothing was removed.")

    noun = "entry" if len(summary.pruned) == 1 else "entries"
    parts = [f"Removed {len(summary.pruned)} missing capture {noun} from the app's records. "
             "No files were deleted."]
    if summary.kept:
        parts.append(f"{len(summary.kept)} capture(s) turned up again and were kept.")
    return " ".join(parts)


def _relocate_message(summary) -> str:
    """One status line for a search pass - what came back, and what to do about the rest."""
    if summary.scanned == 0 and not summary.still_missing:
        return "Every capture the app knows about is already where it expects - nothing to find."

    if summary.relocated:
        noun = "capture" if len(summary.relocated) == 1 else "captures"
        parts = [f"Found {len(summary.relocated)} moved {noun}; the app now looks in the right "
                 "place for them."]
    else:
        parts = [f"No moved captures were found there ({summary.scanned} capture file(s) "
                 "checked)."]
    if summary.still_missing:
        parts.append(f"{len(summary.still_missing)} capture(s) are still missing - try another "
                     "folder, or use \"Clean up missing captures\" to forget them.")
    if summary.errors:
        parts.append(f"{len(summary.errors)} file(s) could not be read: {summary.errors[0]}")
    if summary.cancelled:
        parts.append("The search was canceled.")
    return " ".join(parts)


def _format_size(num_bytes: int) -> str:
    """Bytes as MB/GB, an import moves hundreds of MBs and the user should know first."""
    mb = num_bytes / (1024 * 1024)
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{mb:.0f} MB"


def _import_message(summary) -> str:
    """One status line for an import pass - what came in, and what was already here.

    Says "already imported" out loud rather than staying silent about it: re-running an import on
    a synced folder is the normal case, and a pass that reports nothing looks like a pass that
    failed.
    """
    parts = []
    if summary.imported:
        noun = "capture" if len(summary.imported) == 1 else "captures"
        parts.append(f"Imported {len(summary.imported)} new {noun} "
                     f"({summary.sessions_stored} session(s) stored).")
    if summary.recovered:
        parts.append(f"{len(summary.recovered)} capture(s) missing from your captures folder "
                     "were copied back in.")
    if summary.updated:
        parts.append(f"Updated who recorded {len(summary.updated)} already-imported capture(s).")
    if summary.skipped:
        parts.append(f"{len(summary.skipped)} were already imported.")
    if summary.errors:
        parts.append(f"{len(summary.errors)} failed: {summary.errors[0]}")
    if summary.cancelled:
        parts.append("The import was cancelled.")
    return " ".join(parts) if parts else "Nothing was imported."
