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

_REQUIRED = ("distance",) + LapTrace.CHANNELS
_OPTIONAL = LapTrace.OPTIONAL_CHANNELS


def write_trace(path: str, trace: LapTrace) -> None:
    """Write a LapTrace to a Parquet file at ``path``.

    Always writes the distance axis + the required channels; the optional channels are
    written only when present, so a lap without Motion stores the original nine-channel file.
    """
    data = {name: getattr(trace, name) for name in _REQUIRED}
    for name in _OPTIONAL:
        values = getattr(trace, name)
        if values is not None:
            data[name] = values
    pq.write_table(pa.table(data), path)

def read_trace(path: str) -> LapTrace:
    """Reconstruct a LapTrace from a Parquet file at ``path``.
    
    Optional motion columns are read only if the file has them, so traces without them
    load with those channels left None - the detail page omits the map/g-force.
    """
    table = pq.read_table(path)
    present = set(table.column_names)
    columns = {name: table.column(name).to_numpy() for name in _REQUIRED}
    for name in _OPTIONAL:
        if name in present:
            columns[name] = table.column(name).to_numpy()
    return LapTrace(**columns)