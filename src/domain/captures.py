"""The capture aggregate: what a recording file is and what it contains.

Deliberatly separate from ``models.py``, which holds normalized *game* data. This describes
the file itself - its identity, codec, size, and which sessions it holds - so captures are
queryable without decompressing a multi-hundred-MB payload (DECISIONS -> Storage), the hybrid).

``content_hash`` is the sha256 of the **decompressed** payload and is the aggregate's identity:
stable across a gzip -> zstd re-archive, and the dedupe key when league members' captures are
imported from a shared folder.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class CaptureMeta:
    """One capture file's metadata, recorded at ingest."""

    content_hash: str               # sha256 of the decompressed payload; the identity
    path: str                       # where the archive was last seen (advisory - files move)
    file_name: str                  # basename; the cheap pre-filter for a folder scan
    file_size: int                  # compressed size on disk, bytes
    payload_size: int               # decompressed size, bytes
    codec: str                      # archive.CODEC_*, of the file at `path`
    packet_count: int
    # every session the capture *contains*, including ones ingest skipped as tombstoned:
    # this describes the file, not the admin's curation of it.
    session_uids: tuple[str, ...] = ()
    recorded_by: str | None = None              # which user/member produced it; None = unknown/self
    ingested_at: datetime | None = None
    first_packet_at: datetime | None = None     # capture packet wall-clock, like SessionResult.recorded_at
    last_packet_at: datetime | None = None