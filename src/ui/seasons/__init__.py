"""The seasons surface: a thin `SeasonsView` container plus its per-page widgets.

Each page (overview, create, detail, weekend) lives in its own module and coordinates with the
others only through navigation signals wired up in ``view.py``. Shared season-label helpers live
in ``labels.py``.
"""

from __future__ import annotations

from .view import SeasonsView

__all__ = ["SeasonsView"]
