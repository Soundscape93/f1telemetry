"""Nationality flag icons for the results-screen driver column.

Maps a UDP nationality id (see ``protocol.reference.NATIONALITY_NAMES``) to a bundled SVG flag
and renders it to a cached ``QIcon``. The mapping is hand-written because F1 nationalities aren't
1:1 with ISO countries: the UK home nations have their own flags (England/Scotland/Wales/Northern
Ireland), and a few names differ from the country label (Monegasque → Monaco, Emirian → UAE, …).

Flags are from the flag-icons project (MIT); see ``assets/flags/ATTRIBUTION.md``. An unmapped
nationality or a missing asset yields ``None`` so the cell simply shows no flag rather than raising.
"""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
    
from ...paths import resource_path

_FLAGS_DIR = resource_path("ui", "assets", "flags")
_FLAG_HEIGHT = 24               # px; flag-icons 4x3 flags render to 32x24, scaled by the view

# nationality id -> flag-icons code (ISO 3166-1 alpha-2, or a GB subdivision code).
_NATIONALITY_FLAG: dict[int, str] = {
    1: "us", 2: "ar", 3: "au", 4: "at", 5: "az", 6: "bh", 7: "be", 8: "bo", 9: "br", 10: "gb",
    11: "bg", 12: "cm", 13: "ca", 14: "cl", 15: "cn", 16: "co", 17: "cr", 18: "hr", 19: "cy",
    20: "cz", 21: "dk", 22: "nl", 23: "ec", 24: "gb-eng", 25: "ae", 26: "ee", 27: "fi", 28: "fr",
    29: "de", 30: "gh", 31: "gr", 32: "gt", 33: "hn", 34: "hk", 35: "hu", 36: "is", 37: "in",
    38: "id", 39: "ie", 40: "il", 41: "it", 42: "jm", 43: "jp", 44: "jo", 45: "kw", 46: "lv",
    47: "lb", 48: "lt", 49: "lu", 50: "my", 51: "mt", 52: "mx", 53: "mc", 54: "nz", 55: "ni",
    56: "gb-nir", 57: "no", 58: "om", 59: "pk", 60: "pa", 61: "py", 62: "pe", 63: "pl", 64: "pt",
    65: "qa", 66: "ro", 68: "sv", 69: "sa", 70: "gb-sct", 71: "rs", 72: "sg", 73: "sk", 74: "si",
    75: "kr", 76: "za", 77: "es", 78: "se", 79: "ch", 80: "th", 81: "tr", 82: "uy", 83: "ua",
    84: "ve", 85: "bb", 86: "gb-wls", 87: "vn", 88: "dz", 89: "ba", 90: "ph",
}


def flag_code(nationality_id: int) -> str | None:
    """The bundled flag-asset code for a nationality id, or None if unmapped."""
    return _NATIONALITY_FLAG.get(nationality_id)


@lru_cache(maxsize=None)
def flag_icon(nationality_id: int) -> QIcon | None:
    """A cached flag ``QIcon`` for a nationality id, or None if unmapped or the asset is missing.

    Rendered from SVG to a pixmap so it doesn't depend on the optional Qt SVG *icon-engine*
    plugin (only the always-present ``QtSvg`` module).
    """
    code = _NATIONALITY_FLAG.get(nationality_id)
    if code is None:
        return None
    path = _FLAGS_DIR / f"{code}.svg"
    if not path.exists():
        return None
    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        return None
    pixmap = QPixmap(QSize(_FLAG_HEIGHT * 4 // 3, _FLAG_HEIGHT))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)
