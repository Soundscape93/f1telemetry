"""The lap-detail damage panel: the player's non-tyre CarDamage as a grouped key/value table.

Splits the CarDamage snapshot into readable sections (aero, brakes, drivetrain, faults). The
tyre-specific wear/damage/blisters live on LapTyreContext and are shown by ``TyreBox`` instead, so
there's no overlap. ``damage_rows`` is Qt-free (pure formatting) so it's unit-tested; the builder
just renders it through ``build_kv_table``. The elaborate car-body render is deferred (lap plan).
"""
from __future__ import annotations

from PySide6.QtWidgets import QTableWidget

from ...domain.models import CarDamage
from .tables import build_kv_table


def _pct(value: int) -> str:
    return f"{value}%"


def _fault(flag: bool) -> str:
    return "⚠ yes" if flag else "—"


def damage_rows(damage: CarDamage) -> list[tuple[str, str | None]]:
    """Grouped ``(label, value)`` rows for a CarDamage (``value=None`` marks a section header)."""
    return (
        ("Aero", None),
        ("Front wing (L)", _pct(damage.front_left_wing)),
        ("Front wing (R)", _pct(damage.front_right_wing)),
        ("Rear wing", _pct(damage.rear_wing)),
        ("Floor", _pct(damage.floor)),
        ("Sidepod", _pct(damage.sidepod)),
        ("Brakes", None),
        ("Brake RL", _pct(damage.brakes[0])),
        ("Brake RR", _pct(damage.brakes[1])),
        ("Brake FL", _pct(damage.brakes[2])),
        ("Brake FR", _pct(damage.brakes[3])),
        ("Drivetrain", None),
        ("Gearbox", _pct(damage.gearbox)),
        ("Engine", _pct(damage.engine)),
        ("MGU-H", _pct(damage.engine_mguh_wear)),
        ("ES wear", _pct(damage.engine_es_wear)),
        ("CE wear", _pct(damage.engine_ce_wear)),
        ("ICE wear", _pct(damage.engine_ice_wear)),
        ("MGU-K wear", _pct(damage.engine_mguk_wear)),
        ("TC wear", _pct(damage.engine_tc_wear)),
        ("Faults", None),
        ("DRS", _fault(damage.drs_fault)),
        ("ERS", _fault(damage.ers_fault)),
        ("Engine blown", _fault(damage.engine_blown)),
        ("Engine seized", _fault(damage.engine_seized)),
    )


def build_damage_table(damage: CarDamage) -> QTableWidget:
    """A grouped key/value table of one lap's non-tyre car damage."""
    return build_kv_table(damage_rows(damage))
