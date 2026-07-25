"""Top-level exception handling: log every uncaught error and show a crash dialog.

A frozen build has no console, so an unhandled exception would otherwise crash silently. This
installs a ``sys.excepthook`` that logs the traceback and (if a QApplication is running) shows a
dialog pointing the user at the log file. Install it *after* the QApplication is created.

Scope note: worker threads (RecorderWorker / IngestWoker) already catch their own errors and
emit ``failed``; a ``threading.excepthook`` for other background threads is a deliberate later
addition.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import TracebackType

_logger = logging.getLogger("f1telemetry.crash")


def _show_dialog(exc: BaseException, log_file: Path) -> None:
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
    except Exception:
        return
    if QApplication.instance() is None:
        return
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle("F1 Telemetry - unexpected error")
    box.setText("The app hit an unexpected error and may be unstable")
    box.setInformativeText(
        f"{type(exc).__name__}: {exc}\n\n"
        f"Details were written to the log:\n{log_file}"
    )
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()


def install_excepthook(log_file: Path) -> None:
    """Route uncaught exceptions to the log and crash dialog, then the previous hook."""
    previous = sys.excepthook

    def hook(
            exc_type: type[BaseException],
            exc: BaseException,
            tb: TracebackType | None
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            previous(exc_type, exc, tb)
            return
        _logger.critical("Uncaught exception", exc_info=(exc_type, exc, tb))
        _show_dialog(exc, log_file)
        previous(exc_type, exc, tb)
    
    sys.excepthook = hook