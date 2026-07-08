"""The lap-detail setup panel: the Setup active on a lap as a grouped key/value table.

The detail page resolves which setup was active via ``SessionResult.setup_for_lap(lap_number)``
(setup is a per-session history, not per-lap) and passes it here. ``setup_rows`` is Qt-free (pure
formatting) so it's unit-tested; the builder renders it through ``build_kv_table``.
"""
from __future__ import annotations

from PySide6.QtWidgets import QTableWidget

from ...domain.models import Setup
from .tables import build_kv_table


def setup_rows(setup: Setup) -> list[tuple[str, str | None]]:
    """Grouped ``(label, value)`` rows for a Setup (``value=None`` marks a section header)."""
    return (
        ("Aerodynamics", None),
        ("Front wing", str(setup.front_wing)),
        ("Rear wing", str(setup.rear_wing)),
        ("Transmission", None),
        ("On-throttle differential", str(setup.on_throttle)),
        ("Off-throttle differential", str(setup.off_throttle)),
        ("Engine braking", str(setup.engine_braking)),
        ("Suspension geometry", None),
        ("Front camber", f"{setup.front_camber:.1f}°"),
        ("Rear camber", f"{setup.rear_camber:.1f}°"),
        ("Front toe", f"{setup.front_toe:.2f}°"),
        ("Rear toe", f"{setup.rear_toe:.2f}°"),
        ("Suspension", None),
        ("Front suspension", str(setup.front_suspension)),
        ("Rear suspension", str(setup.rear_suspension)),
        ("Front anti-roll bar", str(setup.front_anti_roll_bar)),
        ("Rear anti-roll bar", str(setup.rear_anti_roll_bar)),
        ("Front ride height", str(setup.front_ride_height)),
        ("Rear ride height", str(setup.rear_ride_height)),
        ("Brakes", None),
        ("Brake pressure", str(setup.brake_pressure)),
        ("Brake bias", str(setup.brake_bias)),
        ("Tyres", None),
        ("Pressure Rear Left", f"{setup.tyre_pressures[0]:.1f} psi"),
        ("Pressure Rear Right", f"{setup.tyre_pressures[1]:.1f} psi"),
        ("Pressure Front Left", f"{setup.tyre_pressures[2]:.1f} psi"),
        ("Pressure Front Right", f"{setup.tyre_pressures[3]:.1f} psi"),
        ("Ballast & Fuel", None),
        ("Ballast", f"{setup.ballast} kg"),
        ("Fuel load", f"{setup.fuel_load:.1f} kg"),
    )


def build_setup_table(setup: Setup) -> QTableWidget:
    """A grouped key/value table of one lap's setup."""
    return build_kv_table(setup_rows(setup))