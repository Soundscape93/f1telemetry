"""File (and, in dev, console) logging for the app.

A windowed frozen build has no console, so rotating file log under ``data_root()/logs`` is the
only window into errors for the author/testers/users (see docs/PACKAGING.md "What's easy to
forget" #1). Call :func:`configure_logging` once at startup, before anything might log.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .paths import is_frozen, logs_dir

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_MAX_BYTES = 2 * 1024 * 1024  # 2 MB per file
_BACKUP_COUNT = 5  # keep ~10 MB of history


def configure_logging(level: int = logging.INFO) -> Path:
    """Configure the root logger and return the path of the active log file.
    
    Idempotent: replaces any handlers a previous call installed, so repeated calls in tests or a reloaded
    process don't multiply output.
    """
    log_file = logs_dir() / "f1telemetry.log"

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    
    file_handler = RotatingFileHandler(
        log_file, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(file_handler)

    # In a source run there IS no console - mirror there too for a live dev view.
    if not is_frozen():
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        root.addHandler(console_handler)
    
    return log_file