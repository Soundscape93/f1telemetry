"""Shared UI style tokens.

Fixed colours chosen to read on both the light and dark platform themes. We deliberately avoid Qt
Style Sheet palette roles for muted text: ``palette(mid)`` resolves ``QPalette.Mid``, a 3D-bevel
role (not a text role) that several platform themes - notably Ubuntu's - leave poorly defined or
re-resolve inconsistently on show/navigation, so ``color: palette(mid)`` text can render unreadable
and flip between readable/unreadable across page changes. A fixed mid-grey is stable everywhere.
"""
from __future__ import annotations

MUTED_TEXT = "#8b949e"              # muted / secondary text; reads on both light and dark grounds
MUTED_TEXT_QSS = f"color: {MUTED_TEXT};"   # drop-in replacement for "color: palette(mid);"
