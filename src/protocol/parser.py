"""Decodes a raw datagram into its version-specific wire struct.

Format-agnostic and stateless with respect to the data: it reads the header, looks up
the right struct via the registry by (packet_format, packet_id), validates the byte length,
and decodes. It does not read sockets, loop, or hold session state - the caller 
fees it one datagramm at a time::

    parser = PacketParser(build_registry())
    for raw in source:
        pkt = parser.parse(raw)
        if pkt is not None:
            ...

Skip behavoiur (returns None rather then crashing the stream):
  * unknown (packet_format, packet_id) — a packet/format we don't model yet; normal.
  * wrong byte length for a known packet — truncated or malformed; not mis-decoded.
Both are counted (skipped_unknown / skipped_malformed) so drops are observable.
"""
from __future__ import annotations

import ctypes as ct

from .base import _Struct
from .header import PacketHeader
from .registry import PacketRegistry

_HEADER_SIZE = ct.sizeof(PacketHeader)


class PacketParser:
    """Decodes raw datagrams into version-specific wire structs, using the registry for dispatch."""

    def __init__(self, registry: PacketRegistry) -> None:
        self._registry = registry
        self.parsed = 0
        self.skipped_unknown = 0
        self.skipped_malformed = 0

    def parse(self, raw: bytes) -> _Struct | None:
        # Too short to even contain a header? Malformed, skip.
        if len(raw) < _HEADER_SIZE:
            self.skipped_malformed += 1
            return None
        
        header = PacketHeader.from_buffer_copy(raw)
        struct_class = self._registry.get(header.packet_format, header.packet_id)

        # A format/packet we don't know about? Skip, but not malformed - maybe a newer packet we haven't modeled yet.
        if struct_class is None:
            self.skipped_unknown += 1
            return None
        
        # F1 packets are fixed-size; a length mismatch means truncation or a struct size bug, so refuse to decode rather than hand back garbage.
        if len(raw) != ct.sizeof(struct_class):
            self.skipped_malformed += 1
            return None
        
        self.parsed += 1
        return struct_class.from_buffer_copy(raw)