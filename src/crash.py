"""Top-level exception handling: log every uncaught error and show a crash dialog.

A frozen build has no console, so an unhandled exception would otherwise crash silently. This
installs a ``sys.excepthook`` that logs the traceback and (if a QApplication is running) shows a
dialog pointing the user at the log file. Install it *after* the QApplication is created.

**Two hooks, because Python has two.** ``sys.excepthook`` covers the main thread, and is also
where PySide6 routes an exception that escapes a ``QThread.run`` body. ``threading.excepthook``
covers plain ``threading.Thread`` workers, which ``sys.excepthook`` never sees — the interpreter
calls it from ``Thread._bootstrap_inner`` instead, and its default prints to a stderr that a
windowed build does not have.

**The dialog is only ever built on the GUI thread.** Constructing a QWidget on a worker thread is
undefined behaviour in Qt and can abort the process — which would turn a survivable error into a
crash inside the crash handler. An off-thread report is queued to the GUI thread instead, and only
plain strings cross the boundary (never the exception, whose traceback pins worker frames alive).

Scope note: the QThread workers (RecorderWorker / IngestWorker / …) catch their own errors and
emit ``failed``. These hooks are the net for what escapes that — notably a ``finally`` block, which
sits outside the workers' ``except``.
"""
from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from types import TracebackType

_logger = logging.getLogger("f1telemetry.crash")

# Built by install_excepthook, on the GUI thread, so the object *lives* on the GUI thread. None
# when Qt is unavailable (tests) - then a report is logged and nothing more.
_relay = None


def _make_relay(log_file: Path) -> None:
    """Return a QObject on the calling thread that turns a report into a dialog, or None.
    
    Qt's doucmented way to hop threads: emit from any thread, and a queued connection delivers
    the call on the thread receiving object lives on. Built lazily so this module stays
    importable without PySide6. 
    """
    try:
        from PySide6.QtCore import QObject, Qt, Signal
    except Exception:
        return None

    class _CrashRelay(QObject):
        reported = Signal(str, str)         # exception class name, str(exception)

        def __init__(self) -> None:
            super().__init__()
            self.reported.connect(self._show, Qt.ConnectionType.QueuedConnection)

        def _show(self, name: str, detail: str) -> None:
            _show_dialog(name, detail, log_file)

    return _CrashRelay()


def _on_gui_thread() -> bool:
    """True when the caller is running on the thread the QApplication lives on."""
    try:
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QApplication
    except Exception:
        return False
    app = QApplication.instance()
    return app is not None and QThread.currentThread() is app.thread()


def _show_dialog(name: str, detail: str, log_file: Path) -> None:
    """Show the crash dialog. Callers must guarantee this runs on the GUI thread."""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
    except Exception:
        return
    if QApplication.instance() is None:
        return
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle("F1 Telemetry unexpected error")
    box.setText("The app hit an unexpected error and may be unstable.")
    box.setInformativeText(
        f"{name}: {detail}\n\n"
        f"Details were written to the log file:\n{log_file}"
    )
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()


def _report(exc: BaseException, log_file: Path) -> None:
    """Surface an already-logged exception to the user, from whichever thread raised it.
    
    On the GUI thread the dialog is shown directly rather than queued: a crash during start-up
    happens before ``app.exec()`` runs, and a queued call would never be delivered.
    """
    name, detail = type(exc).__name__, str(exc)
    if _on_gui_thread():
        _show_dialog(name, detail, log_file)
    elif _relay is not None:
        _relay.reported.emit(name, detail)      # returns at once; the dialog is build on the GUI thread


def install_excepthook(log_file: Path) -> None:
    """Route uncaught exceptions to the log and crash dialog, then the previous hook.
    
    Call this on the GUI thread and after the QApplication exists - the relay is a QObject and
    must be created on the thread it will live on.
    """
    global _relay
    _relay = _make_relay(log_file)
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
        _report(exc, log_file)
        previous(exc_type, exc, tb)
    
    sys.excepthook = hook


def install_threading_excepthook(log_file: Path) -> None:
    """Do the same for plain ``threading.Thread`` workers, which ``sys.excepthook`` never sees.

    Nothing in the app uses a bare Thread today (every worker is a QThread), so this is a net for
    future workers and for third-party threads. ``SystemExit`` is passed straight through, matching
    the stdlib default, which ignores it silently.
    """
    previous = threading.excepthook

    def hook(args: threading.ExceptHookArgs) -> None:
        if issubclass(args.exc_type, SystemExit):
            previous(args)
            return
        thread_name = args.thread.name if args.thread is not None else "<unknown>"
        _logger.critical(
            "Uncaught exception in thread %s", thread_name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        if args.exc_value is not None:
            _report(args.exc_value, log_file)
        previous(args)
    
    threading.excepthook = hook
