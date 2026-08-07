"""The crash hooks: what gets logged, what gets passed on, and what never builds a widget.

Qt-free, like every suite here. Without a QApplication there is no GUI thread and no relay, so
``_report`` must be inert rather than reaching for QMessageBox — that inertness is the regression
this file guards.
"""
from __future__ import annotations

import logging
import sys
import threading
import unittest
from pathlib import Path

from f1telemetry.src import crash

_LOG = Path("nowhere/f1telemetry.log")


class _Hooks:
    """Restore both hooks and the relay, whatever a test did to them."""

    def __enter__(self):
        self._sys, self._thread, self._relay = sys.excepthook, threading.excepthook, crash._relay
        return self

    def __exit__(self, *exc):
        sys.excepthook, threading.excepthook = self._sys, self._thread
        crash._relay = self._relay
        return False


class ThreadingExceptHookTest(unittest.TestCase):
    def test_logs_and_chains_for_a_thread_failure(self):
        seen = []
        with _Hooks():
            threading.excepthook = lambda args: seen.append(args)
            crash.install_threading_excepthook(_LOG)

            def boom():
                raise ValueError("thread went bang")

            with self.assertLogs("f1telemetry.crash", level=logging.CRITICAL) as logged:
                t = threading.Thread(target=boom, name="worker-1")
                t.start()
                t.join()

        self.assertIn("worker-1", logged.output[0])
        self.assertIn("thread went bang", logged.output[0])
        self.assertEqual(1, len(seen), "the previous hook must still run")

    def test_system_exit_is_passed_through_unlogged(self):
        """Matches the stdlib default, which ignores SystemExit silently."""
        seen = []
        with _Hooks():
            threading.excepthook = lambda args: seen.append(args)
            crash.install_threading_excepthook(_LOG)

            def quit_():
                raise SystemExit(0)

            logger = logging.getLogger("f1telemetry.crash")
            with self.assertNoLogs(logger, level=logging.CRITICAL):
                t = threading.Thread(target=quit_)
                t.start()
                t.join()

        self.assertEqual(1, len(seen))


class SysExceptHookTest(unittest.TestCase):
    def test_logs_and_chains(self):
        seen = []
        with _Hooks():
            sys.excepthook = lambda *a: seen.append(a)
            crash.install_excepthook(_LOG)
            with self.assertLogs("f1telemetry.crash", level=logging.CRITICAL) as logged:
                sys.excepthook(ValueError, ValueError("main went bang"), None)

        self.assertIn("main went bang", logged.output[0])
        self.assertEqual(1, len(seen))

    def test_keyboard_interrupt_is_not_logged(self):
        seen = []
        with _Hooks():
            sys.excepthook = lambda *a: seen.append(a)
            crash.install_excepthook(_LOG)
            logger = logging.getLogger("f1telemetry.crash")
            with self.assertNoLogs(logger, level=logging.CRITICAL):
                sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)

        self.assertEqual(1, len(seen))


class ReportThreadSafetyTest(unittest.TestCase):
    def test_report_builds_no_dialog_off_the_gui_thread(self):
        """The whole point of the change: a worker-thread report must not touch QWidget."""
        built = []
        with _Hooks():
            crash._relay = None
            original = crash._show_dialog
            crash._show_dialog = lambda *a: built.append(a)
            try:
                crash._report(ValueError("off thread"), _LOG)
            finally:
                crash._show_dialog = original

        self.assertEqual([], built, "no QApplication means no GUI thread and no dialog")


if __name__ == "__main__":
    unittest.main()
