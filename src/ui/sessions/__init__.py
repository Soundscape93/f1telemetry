"""The Sessions surface: a thin `SessionView` container plus its per-page widgets.

Each page lives in its own module and coordinates with the others only through navigation
signals wired up in ``view.py`` - pages never reference each other.
"""

from __future__ import annotations

from .view import SessionsView

__all__ = ["SessionsView"]
