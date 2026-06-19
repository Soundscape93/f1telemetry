"""On-disk format for raw UDP capture files (.f1cap).

A capture is a small versioned header, followed by length-prefixed, timestamped datagrams.
The recorder writes this format; ``FileReplaySource`` reads it.
Keeping the frame here - rather than duplicated in both modules - means the read and write
path can never drift apart.

Layout::

    header: magic[8] = b"F1TELCAP", uint16 format_version
    record: double recv_time (unix seconds), uint32 length, <length> bytes
    ...records repeat until EOF

The length prefix matters: UDP datagram boundaries are meaningful (the parser decodes one whole
datagram at a time), so each record stores exactly one datagram. The timestamp lets realtime
replay reproduce the original inter-packet timing and ordering.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import BinaryIO

MAGIC = b"F1TELCAP"
RECORDING_FORMAT_VERSION = 1

_HEADER = struct.Struct("<8sH")     # magic, format version
_RECORD = struct.Struct("<dI")      # recv_time (double), payload_length (uint32)
_MAX_PACKET_LEN = 65535             # a UDP payload can't exceed this; a larger length means a corrupt file


@dataclass
class RecordedPacket:
    """One captured datagram and the wall-clock time it arrived."""

    recv_time: float
    data: bytes


def write_header(file: BinaryIO) -> None:
    """Write the capture file header. Call once, before any packets."""
    file.write(_HEADER.pack(MAGIC, RECORDING_FORMAT_VERSION))


def read_header(file: BinaryIO) -> int:
    """Validate the magic and return the recording format version."""
    raw = file.read(_HEADER.size)
    if len(raw) < _HEADER.size:
        raise ValueError("file too short to be a capture")
    magic, version = _HEADER.unpack(raw)
    if magic != MAGIC:
        raise ValueError("Not an F1 capture file (bad magic)")
    if version > RECORDING_FORMAT_VERSION:
        raise ValueError(
            f"capture format version {version} is newer/older than supported ({RECORDING_FORMAT_VERSION})"
        )
    return version


def write_packet(file: BinaryIO, recv_time: float, data: bytes) -> None:
    """Append one packet with its arrival time."""
    file.write(_RECORD.pack(recv_time, len(data)))
    file.write(data)


def read_packet(file: BinaryIO) -> RecordedPacket | None:
    """Read the next datagram, or return ``None`` at clean EOF."""
    head = file.read(_RECORD.size)
    if not head:
        return None                 # clean EOF
    if len(head) < _RECORD.size:
        raise ValueError("truncated record header")
    recv_time, length = _RECORD.unpack(head)
    if length > _MAX_PACKET_LEN:
        raise ValueError(f"record claims {length} bytes; file is corrupt")
    data = file.read(length)
    if len(data) < length:
        raise ValueError("truncated record payload")
    return RecordedPacket(recv_time=recv_time, data=data)