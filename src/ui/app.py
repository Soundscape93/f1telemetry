"""Launch the f1telemetry desktop UI.

Run with:

    python -m f1telemetry.src.ui.app
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from ..crash import install_excepthook
from ..logging_setup import configure_logging
from ..paths import data_root
from ..version import __version__
from .main_window import MainWindow


def main() -> None:
    log_file = configure_logging()
    logging.getLogger(__name__).info(
        "Starting f1telemetry %s (data root: %s)", __version__, data_root()
    )

    app = QApplication(sys.argv)
    app.setApplicationName("f1telemetry")
    app.setOrganizationName("f1telemetry")
    app.setApplicationVersion(__version__)
    
    install_excepthook(log_file)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
