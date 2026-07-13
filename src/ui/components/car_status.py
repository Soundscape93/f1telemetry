"""Pure, Qt-free status/colour model for the lap-detail car-status graphic (iteration 2c).

Maps a lap's ``CarDamage`` + ``LapTyreContext`` onto per-part health status + fill colour, so the
graphic widget (``car_status_graphic.py``, Phase C) stays a thin renderer over tested logic - the
same split as ``damage_panel.damage_rows`` / ``setup_panel.setup_rows``.

Three threshold families (see DECISIONS.md, 2c):
  * monotonic WEAR (tyre + engine components): green <60, orange 60-79, red >=80;
  * monotonic BODY / aero damage (stricter): green <15, orange 15-39, red >=40;
  * two-sided TEMPERATURE bands - tyres keyed by compound (carcass window), brakes a broad band.
Temperature windows + aero cutoffs are community-/estimate-sourced (not official game values); they
live here as named constants to retune once observed against real telemetry.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ...domain.models import CarDamage, LapTyreContext
from ...protocol.enums import ActualTyreCompound


class Status(Enum):
    """A part's health band; the widget maps it to a fill colour via ``status_colour``."""
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"
    COLD = "cold"             # temperature below the working window (two sided bands only)
    NONE = "none"             # structural / no data caputred -> neutral


_COLOURS = {
    Status.OK: "#3fb950",       # green (matches tyre.box._wear_colour)
    Status.WARNING: "#d29922",  # orange
    Status.CRITICAL: "#f85149", # red
    Status.COLD: "#3f86d6",     # blue
    Status.NONE: "#8b949e"      # gray
}

# severity order for "worst of" combinations: CRITICAL > WARNING > COLD > OK > NONE
_SEVERITY = {Status.NONE: 0, Status.OK: 1, Status.COLD: 2, Status.WARNING: 3, Status.CRITICAL: 4}


def status_colour(status: Status) -> str:
    """The hex fill colour for a status (chosen to read on both light and dark grounds)."""
    return _COLOURS[status]


def worst(*statuses: Status) -> Status:
    """The most severe of several statuses (Critical > Warning > Cold > OK > None)."""
    return max(statuses, key=lambda s: _SEVERITY[s], default=Status.NONE)


# --- threshold constants (single source of truth; see DECISIONS.md 2c) ------------
_WEAR_WARN, _WEAR_CRIT = 60, 80         # tyre + engine component wear/damage %
_BODY_WARN, _BODY_CRIT = 15, 40         # aero / body damage % (stricter - a wing damage costs downforce early on)
_BRAKE_COLD, _BRAKE_WARN, _BRAKE_CRIT = 250, 750, 1000      # brake temperature °C bands

# per-compound tyre CARCASS window (cold_below, hot_above) °C; the tyre reads COLD below the window
# and CRITICAL above it. Surface runs a few °C hotter. Community-measured F1 24/25 values; unknown /
# F2 / classic compounds fall back to _TYRE_WINDOW_DEFAULT.
_TYRE_WINDOWS = {
    ActualTyreCompound.C0: (95, 120),
    ActualTyreCompound.C1: (90, 115),
    ActualTyreCompound.C2: (85, 115),
    ActualTyreCompound.C3: (80, 105),
    ActualTyreCompound.C4: (75, 100),
    ActualTyreCompound.C5: (70, 90),
    ActualTyreCompound.C6: (65, 85),
    ActualTyreCompound.INTER: (55, 75),
    ActualTyreCompound.WET: (45, 65),
}
TYRE_WINDOW_DEFAULT = (80, 110)  # fallback for unknown / F2 / classic compounds

# (tuple index into RL,RR,FL,FR arrays, key, label) - on-car wheel order
_WHEELS = ((0, "rl", "Rear-left"), (1, "rr", "Rear-right"),
           (2, "fl", "Front-left"), (3, "fr", "Front-right"))

# engine sub-wear fields -> label; the engine blick is coloured by the worst of these
_ENGINE_WEARS = {
    "engine_ice_wear": "ICE",
    "engine_mguk_wear": "MGU-K",
    "engine_mguh_wear": "MGU-H",
    "engine_tc_wear": "Turbo",
    "engine_es_wear": "Energy Store",
    "engine_ce_wear": "Control Electronics",
}


# --- threshold functions ----------------------------------------------------------------
def _monotonic(pct: float, warn: int, crit: int) -> Status:
    """Higher-is-worse band: >= crit CRITICAL, >= warn WARNING, else OK."""
    if pct >= crit:
        return Status.CRITICAL
    if pct >= warn:
        return Status.WARNING
    return Status.OK


def _wear_status(pct: float) -> Status:
    """Tyre / engine component wear or damage %: green <60, orange 60-79, red >=80."""
    return _monotonic(pct, _WEAR_WARN, _WEAR_CRIT)


def body_status(pct: float) -> Status:
    """Aero / body damage %: stricter green <15, orange 15-39, red >=40."""
    return _monotonic(pct, _BODY_WARN, _BODY_CRIT)


def _tyre_window(actual_compound: int) -> tuple[int, int]:
    """The (cold_below, hot_above) carcass window °C for a compound; default for unknwon / F2."""
    try:
        return _TYRE_WINDOWS[ActualTyreCompound(actual_compound)]
    except (ValueError, KeyError):
        return TYRE_WINDOW_DEFAULT


def tyre_temp_status(carcass_temp: float, actual_compound: int) -> Status:
    """Two-sided compound-specific band: COLD below the window, CRITICAL above, else OK.
    
    A non-positive reading means the temperature wasn't captured -> NONE.
    """
    if carcass_temp <= 0:
        return Status.NONE
    cold_below, hot_above = _tyre_window(actual_compound)
    if carcass_temp < cold_below:
        return Status.COLD
    if carcass_temp > hot_above:
        return Status.CRITICAL
    return Status.OK


def brake_temp_status(temp_c: float) -> Status:
    """Broad brake band: COLD <250, OK 250-750, WARNING 750-1000, CRITICAL >1000 °C (0 -> NONE)."""
    if temp_c <= 0:
        return Status.NONE
    if temp_c < _BRAKE_COLD:
        return Status.COLD
    if temp_c > _BRAKE_CRIT:
        return Status.CRITICAL
    if temp_c > _BRAKE_WARN:
        return Status.WARNING
    return Status.OK


# --- assembled per-part model -------------------------------------------------------------
@dataclass(frozen=True)
class PartStatus:
    """One coloured region of the car body: a stable ``key`` (matches the SVG part id), a human
    ``label``, its health ``status`` + fill ``colour``, and a short hover ``detail``string."""

    key: str
    label: str
    status: Status
    colour: str
    detail: str


@dataclass(frozen=True)
class TyreCorner:
    """One wheel's status for a corner gauge: tyre wear + temperatures (the ring is coloured by the
    carcass ``temp_status``; the wear-% label by ``wear_status`` - two signals, in-game style), plus
    the co-located brake temperature."""

    key: str        # "rl" / "rr" / "fl" / "fr"
    label: str
    wear_pct: float
    surface_temp: int
    carcass_temp: int
    brake_temp: int
    temp_status: Status         # tyre carcass band (compound-specific)
    wear_status: Status
    brake_status: Status
    temp_colour: str
    wear_colour: str
    detail: str


def _part(key: str, label: str, status: Status, detail: str) -> PartStatus:
    return PartStatus(key, label, status, status_colour(status), detail)


def damage_parts(damage: CarDamage) -> list[PartStatus]:
    """Per-region status for the non-tyre car body: aero (stricter rule), the engine block (coloured
    by its wors sub-wear, each listed on hover) and the gearbox. Brake temps live on the tyre 
    corners (``tyre_corners``), so they're not repeated here."""
    parts = [
        _part("front_wing_left", "Front wing (left)", 
              body_status(damage.front_left_wing), f"{damage.front_left_wing}% damage"),
        _part("front_wing_right", "Front wing (right)",
                body_status(damage.front_right_wing), f"{damage.front_right_wing}% damage"),
        _part("rear_wing", "Rear wing", body_status(damage.rear_wing), f"{damage.rear_wing}% damage"),
        _part("floor", "Floor", body_status(damage.floor), f"{damage.floor}% damage"),
        _part("diffuser", "Diffuser", body_status(damage.diffuser), f"{damage.diffuser}% damage"),
        _part("sidepod", "Sidepod", body_status(damage.sidepod), f"{damage.sidepod}% damage"),
    ]
    sub = [(label, getattr(damage, field)) for field, label in _ENGINE_WEARS.items()]
    engine_status = worst(*(_wear_status(v) for _, v in sub))
    engine_detail = ", ".join(f"{label} {v}%" for label, v in sub)
    parts.append(_part("engine", "Power unit", engine_status, engine_detail))
    parts.append(_part("gearbox", "Gearbox", _wear_status(damage.gearbox), f"{damage.gearbox}% damage"))
    return parts


def tyre_corners(tyre_context: LapTyreContext,
                 damage: CarDamage | None = None) -> list[TyreCorner]:
    """The four corner gauges, in order RL, RR, FL, FR. Brake temp is read from ``damage``
    when present (else 0 -> NONE)."""
    corners = []
    for idx, key, label in _WHEELS:
        wear = tyre_context.wear[idx]
        carcass = tyre_context.carcass_temp[idx]
        surface = tyre_context.surface_temp[idx]
        brake = damage.brake_temp[idx] if damage is not None else 0
        ts = tyre_temp_status(carcass, tyre_context.actual_compound)
        ws = _wear_status(wear)
        bs = brake_temp_status(brake)
        detail = (f"{wear:.0f}% wear · carcass {carcass}°C · surface {surface}°C · brake {brake}°C")
        corners.append(TyreCorner(
            key=key, label=label, wear_pct=wear, surface_temp=surface, carcass_temp=carcass,
            brake_temp=brake, temp_status=ts, wear_status=ws, brake_status=bs,
            temp_colour=status_colour(ts), wear_colour=status_colour(ws), detail=detail
        ))
    return corners