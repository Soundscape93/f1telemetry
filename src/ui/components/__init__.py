"""Shared, view-agnostic UI widgets and table primitives.

The durable home for pieces reused across surfaces (seasons, sessions, laps, ...): the pure Qt
table primitives in ``tables``, the session classification table in ``classification_table``, and
the lap-detail widgets (tyre box, damage / setup panels, single-lap telemetry plot).
"""

from __future__ import annotations

from .car_status_graphic import CarStatusGraphic
from .classification_table import build_classification_table, display_name_fn
from .damage_panel import build_damage_table
from .session_actions import confirm_and_delete
from .setup_panel import build_setup_table
from .slider_row import SetupSliderRow, SliderMarkerBar
from .tables import (
    build_kv_table,
    build_readout_grid,
    cell, 
    clear_layout,
    fit_columns,
    fit_table_height,
    hold_column_width,
    tidy_table
)
from .trace_plot import TracePlot
from .track_map import TrackMap
from .weather import WeatherIcon, session_weather

__all__ = [
    "CarStatusGraphic",
    "build_classification_table",
    "display_name_fn",
    "build_damage_table",
    "confirm_and_delete",
    "build_setup_table",
    "SetupSliderRow",
    "SliderMarkerBar",
    "build_kv_table",
    "build_readout_grid",
    "cell",
    "clear_layout",
    "fit_columns",
    "fit_table_height",
    "hold_column_width",
    "tidy_table",
    "TracePlot",
    "TrackMap",
    "WeatherIcon",
    "session_weather"
]
