"""Shared base for all wire structs.

Eevery packet and per-car record inherits from `_Struct`, which fixes two things in one place:
`_pack = 1` (the F1 UDP format is packed, no padding) and a gerneric `__repr__`that prints all field names and values for debugging.
Leaf sctructs use the inerhited repr as-is; container structs that hold large arrays override it to avoid printing every entry.

This module imports nothing from the rest of the package, so it stays a dependency-free leaf that `header.py`and the version-specific
struct modules import.
"""
from __future__ import annotations

import ctypes as ct


class _Struct(ct.LittleEndianStructure):
    _pack_ = 1

    def __repr__(self) -> str:
        parts = []
        for name, *_ in self._fields_:
            value = getattr(self, name)
            if isinstance(value, ct.Array):
                value = list(value)
            parts.append(f"{name}={value}")
        return f"{self.__class__.__name__}({', '.join(parts)})"
