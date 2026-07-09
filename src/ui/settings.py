"""Leightweight persistent user settings via QSettings.

A Thin wrappr so preferences survive app restarts without every view knowing the storage-key
layout. QSetting writes to the platform's native per-user store (an INI file under ~/.config on
Linux) under an org+app identity. We pass that identity explicitly here, so it resolves the same
whether or not app.py has called setOrganizationName/setApplicationName (e.g. in the test suite).
"""
from __future__ import annotations

from PySide6.QtCore import QSettings

_ORG = "f1telemetry"
_APP = "f1telemetry"

_TRACE_COLORBLIND = "laps/trace_colorblind"


def _setting() -> QSettings:
    return QSettings(_ORG, _APP)


def trace_colorblind() -> bool:
    """Whether the throttle/brake trace uses the colour-blind palette (default False)."""
    return _setting().value(_TRACE_COLORBLIND, False, type=bool)


def set_trace_colorblind(enabled: bool) -> None:
    """Persist the throttle/brake trace palette preference."""
    _setting().setValue(_TRACE_COLORBLIND, enabled)