"""Launch the f1telemetry desktop UI.

Run with:

    python -m f1telemetry.src.ui.app
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from ..crash import install_excepthook, install_threading_excepthook
from ..logging_setup import configure_logging
from ..paths import data_root
from ..version import __version__
from .main_window import MainWindow


def _install_theme_refresh(app: QApplication) -> None:
    """Re-polish every widget when Windows switches light/dark at runtime.

    Qt updates the application palette on a live OS theme change but doesn't always repaint
    every widget (item views like the sidebar can keep their old ground). Re-polishing the
    whole tree forces them to pick up the new palette.
    """
    def _repolish(_scheme=None):
        for w in app.allWidgets():
            w.style().unpolish(w)
            w.style().polish(w)
            w.update()
    app.styleHints().colorSchemeChanged.connect(_repolish)


def main() -> None:
    log_file = configure_logging()
    logging.getLogger(__name__).info(
        "Starting f1telemetry %s (data root: %s)", __version__, data_root()
    )

    app = QApplication(sys.argv)
    app.setApplicationName("f1telemetry")
    app.setOrganizationName("f1telemetry")
    app.setApplicationVersion(__version__)

    # Both hooks, and both after the QApplication: install_excepthook builds the GUI-thread relay
    # that lets a worker-thread crash reach a dialog without touching Qt off-thread.
    install_excepthook(log_file)
    install_threading_excepthook(log_file)
    _install_theme_refresh(app)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
