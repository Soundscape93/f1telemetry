"""Shared, view-agnostic UI widgets and table primitives.

The durable home for pieces reused across surfaces (seasons, sessions, laps, ...): the pure
Qt table primitives in ``tables`` and the session classification table in
``classification_table``.
"""

from __future__ import annotations

from .classification_table import build_classification_table, display_name_fn
from .tables import cell, clear_layout, fit_table_height, tidy_table

__all__ = [
    "build_classification_table",
    "display_name_fn",
    "cell",
    "clear_layout",
    "fit_table_height",
    "tidy_table",
]
