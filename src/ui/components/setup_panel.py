"""The lap-detail setup panel: the Setup active on a lap/session as slider-style rows.

Owns the setup-specific field list + in-game adjustable ranges (``_SETUP_SPEC`` - the single source
of truth; edit there to retune) and turns a ``Setup`` into rows of ``SetupField``. The actual row
widget is the reusable ``SetupSliderRow`` in ``slider_row.py`` (shared with the future session setup
view). ``build_setup_table`` is the public entry point. ``setup_fields`` is Qt-free (range-lookup +
formatting) so its unit-testable.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ...domain.models import Setup
from .slider_row import SetupSliderRow

# section -> rows of (label, attr, index, minimum, maximum, decimals, unit).
# `index` picks an element of tuple field (tyre_pressures); None for scalars.
# min/max are the in-game adjustable bounds.
_SETUP_SPEC = (
    ("Aerodynamics", (
        ("Front Wing", "front_wing", None, 0, 50, 0, ""),
        ("Rear Wing", "rear_wing", None, 0, 50, 0, ""),
        )),
    ("Transmission", (
        ("Differential Adjustment On Throttle", "on_throttle", None, 10, 100, 0, "%"),
        ("Differential Adjustment Off Throttle", "off_throttle", None, 10, 100, 0, "%"),
        ("Engine braking", "engine_braking", None, 0, 100, 0, "%"),
    )),
    ("Suspension Geometry", (
        ("Front Camber", "front_camber", None, -3.50, -2.50, 2, "°"),
        ("Rear Camber", "rear_camber", None, -2.00, -1.00, 2, "°"),
        ("Front Toe", "front_toe", None, 0.00, 0.20, 2, "°"),
        ("Rear Toe", "rear_toe", None, 0.10, 0.35, 2, "°"),
    )),
    ("Suspension", (
        ("Front Suspension", "front_suspension", None, 1, 41, 0, ""),
        ("Rear Suspension", "rear_suspension", None, 1, 41, 0, ""),
        ("Front Anti-Roll Bar", "front_anti_roll_bar", None, 1, 21, 0, ""),
        ("Rear Anti-Roll Bar", "rear_anti_roll_bar", None, 1, 21, 0, ""),
        ("Front Ride Height", "front_ride_height", None, 15, 35, 0, ""),
        ("Rear Ride Height", "rear_ride_height", None, 40, 60, 0, ""),
    )),
    ("Brakes", (
        ("Front Brake Bias", "brake_bias", None, 70, 50, 0, "%"),
        ("Brake Pressure", "brake_pressure", None, 80, 100, 0, "%"),
    )),
    ("Tyres", (
        ("Front Right Tyre Pressure", "tyre_pressures", 3, 22.5, 29.5, 1, "PSI"),
        ("Front Left Tyre Pressure", "tyre_pressures", 2, 22.5, 29.5, 1, "PSI"),
        ("Rear Right Tyre Pressure", "tyre_pressures", 1, 20.5, 26.5, 1, "PSI"),
        ("Rear Left Tyre Pressure", "tyre_pressures", 0, 20.5, 26.5, 1, "PSI"),
    )),
)


@dataclass(frozen=True)
class SetupField:
    """One setup row's data: the selected ``value`` on the ``(minimum, maximum)`` range, plus
    pre-formatted strings the row shows. Qt-free, so unit-testable.
    """

    label: str
    value: float
    minimum: float
    maximum: float
    display: str        # selected value with unit, e.g. "23", "-3.00°" "22.5 PSI"
    min_display: str    # bare min (no unit)
    max_display: str    # bare max (no unit)

    @property
    def fraction(self) -> float:
        """Marker position in 0..1 along min->max, clamped so any out-of-band value stays on track."""
        span = self.maximum - self.minimum
        if span <= 0:
            return 0.0
        return min(1.0, max(0.0, (self.value - self.minimum) / span))


def _num(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}"


def setup_fields(setup: Setup) -> list[tuple[str, SetupField | None]]:
    """Ordered rows: ``(section_label, None)`` headers interleaved with ``(None, SetupField)`` fields.
    
    Reads each field's value off ``setup`` and pairs it with its ``_SETUP_SPEC` range; pure so the
    range lookup + formatting are tested without Qt.
    """
    rows: list[tuple[str, SetupField | None]] = []
    for section, fields in _SETUP_SPEC:
        rows.append((section, None))
        for label, attr, index, lo, hi, decimals, unit in fields:
            raw = getattr(setup, attr)
            value = raw[index] if index is not None else raw
            rows.append((None, SetupField(
                label=label, value=float(value), minimum=float(lo), maximum=float(hi),
                display=_num(value, decimals) + unit,
                min_display=_num(lo, decimals), max_display=_num(hi, decimals)
            )))
    return rows


def build_setup_table(setup: Setup) -> QWidget:
    """Slider-style setup readout: one ``SetupSliderRow`` per field, grouped under bold section
    headers. Returns a plain stacked widget - drop-in for the detail panel (unchanged signature)."""
    host = QWidget()
    box = QVBoxLayout(host)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(4)
    for label, field in setup_fields(setup):
        if field is None:           # section header
            head = QLabel(label)
            head.setStyleSheet("font-weight: 600; margin-top: 6px;")
            box.addWidget(head)
            continue
        box.addWidget(SetupSliderRow(
            name=field.label, min_text=field.min_display, max_text=field.max_display,
            value_text=field.display, fraction=field.fraction
        ))
    return host