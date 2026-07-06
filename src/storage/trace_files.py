"""Parquet persistence for a dense LapTrace.

A LapTrace is ~5,400 samples/lap across ten parallel arrays - wrong shape for SQLite rows, so it
lives in one Parquet file per lap referenced by the ``laps`` row (see DECISIONS -> Storage). This
module is the only place that imports pyarrow; everything else deals in domain ``LapTrace`` objects.

The Parquet columns are the distance axis plus ``LapTrace.CHANNELS`` - i.e. exactly the LapTrace
constructor arguments - so a read round-trips straight back into the dataclass.
"""
from __future__ import annotations

import pyarrow as pa
import pyarrow.parquet as pq

from ..domain.models import LapTrace

_COLUMNS = ("distance",) + LapTrace.CHANNELS


def write_trace(path: str, trace: LapTrace) -> None:
    """Write a LapTrace to a Parquet file at ``path``."""
    table = pa.table({name: getattr(trace, name) for name in _COLUMNS})
    pq.write_table(table, path)

def read_trace(path: str) -> LapTrace:
    """Reconstruct a LapTrace from a Parquet file at ``path``."""
    table = pq.read_table(path)
    columns = {name: table.column(name).to_numpy() for name in _COLUMNS}
    return LapTrace(**columns)