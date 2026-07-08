"""Shared, view-agnostic UI widgets and table primitives.

The durable home for pieces reused across surfaces (seasons, sessions, laps, ...): the pure Qt
table primitives in ``tables``, the session classification table in ``classification_table``, and
the lap-detail widgets (tyre box, damage / setup panels, single-lap telemetry plot).
"""

from __future__ import annotations

from .classification_table import build_classification_table, display_name_fn
from .damage_panel import build_damage_table
from .setup_panel import build_setup_table
from .tables import build_kv_table, cell, clear_layout, fit_table_height, tidy_table
from .trace_plot import TracePlot
from .tyre_box import TyreBox

__all__ = [
    "build_classification_table",
    "display_name_fn",
    "build_damage_table",
    "build_setup_table",
    "build_kv_table",
    "cell",
    "clear_layout",
    "fit_table_height",
    "tidy_table",
    "TracePlot",
    "TyreBox",
]