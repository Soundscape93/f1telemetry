"""Parser and registry dispatch tests.

Verifies that the PacketRegistry correctly maps (packet_format, packet_id) to structs,
and that the PacketParser correctly decodes, validates, and counts packets.

Each test synthesizes raw packet bytes, verifies correct dispatch, handles edge cases
(unknown id/format, truncation, malformation), and validates accounting.

Run::

    python -m unittest f1telemetry.test.parser_registry_tests
"""

from __future__ import annotations

import ctypes as ct
import struct
import unittest

from f1telemetry.src.protocol.enums import PacketId
from f1telemetry.src.protocol.header import PacketHeader
from f1telemetry.src.protocol.parser import PacketParser
from f1telemetry.src.protocol.registry import PacketRegistry, build_registry
from f1telemetry.src.protocol.v2025.structs import (
    PacketMotionData as PacketMotionData_2025,
    PacketLapData as PacketLapData_2025,
)
from f1telemetry.src.protocol.v2026.structs import (
    PacketMotionData as PacketMotionData_2026,
)


def _make_header_bytes(
    packet_format: int, packet_id: int, size: int | None = None
) -> bytes:
    """Synthesize packet header bytes (29 bytes) plus padding to the target size.
    
    Args:
        packet_format: Format code (2025, 2026, etc.)
        packet_id: Packet type ID (int, not PacketId enum for testing unknown IDs).
        size: Total packet size including header. Defaults to header size.
    
    Returns:
        Raw packet bytes of the requested size.
    """
    header_size = ct.sizeof(PacketHeader)
    if size is None:
        size = header_size
    
    buf = bytearray(size)
    struct.pack_into("<H", buf, 0, packet_format)  # packet_format at offset 0
    struct.pack_into("<B", buf, 6, packet_id)       # packet_id at offset 6
    return bytes(buf)


class PacketRegistryTest(unittest.TestCase):
    """Tests for PacketRegistry: registration, lookup, and error handling."""

    def test_duplicate_registration_raises(self):
        """Registering the same (format, id) twice raises ValueError."""
        registry = PacketRegistry()
        registry.register(2025, PacketId.MOTION, PacketMotionData_2025)
        
        with self.assertRaises(ValueError) as cm:
            registry.register(2025, PacketId.MOTION, PacketMotionData_2025)
        
        self.assertIn("Duplicate registration", str(cm.exception))

    def test_lookup_by_raw_int_works(self):
        """Lookup accepts raw int, not just PacketId enum."""
        registry = PacketRegistry()
        registry.register(2025, PacketId.MOTION, PacketMotionData_2025)
        
        # Look up by raw int (enum.value)
        struct_class = registry.get(2025, int(PacketId.MOTION))
        self.assertIs(struct_class, PacketMotionData_2025)

    def test_lookup_unknown_id_returns_none(self):
        """Looking up an unknown (format, id) returns None."""
        registry = PacketRegistry()
        registry.register(2025, PacketId.MOTION, PacketMotionData_2025)
        
        # Unknown packet_id
        struct_class = registry.get(2025, 999)
        self.assertIsNone(struct_class)

    def test_lookup_unknown_format_returns_none(self):
        """Looking up an unknown format returns None."""
        registry = PacketRegistry()
        registry.register(2025, PacketId.MOTION, PacketMotionData_2025)
        
        # Unknown packet_format
        struct_class = registry.get(9999, PacketId.MOTION)
        self.assertIsNone(struct_class)

    def test_dispatch_routes_to_correct_class(self):
        """Different packet IDs route to different structs."""
        registry = build_registry()
        
        motion_2025 = registry.get(2025, PacketId.MOTION)
        lap_2025 = registry.get(2025, PacketId.LAP_DATA)
        motion_2026 = registry.get(2026, PacketId.MOTION)
        
        self.assertIs(motion_2025, PacketMotionData_2025)
        self.assertIs(lap_2025, PacketLapData_2025)
        self.assertIs(motion_2026, PacketMotionData_2026)
        self.assertIsNot(motion_2025, motion_2026)


class PacketParserTest(unittest.TestCase):
    """Tests for PacketParser: decoding, validation, and accounting."""

    def setUp(self):
        """Build the default registry for all tests."""
        self.registry = build_registry()

    def test_parser_decodes_valid_packet(self):
        """A valid packet decodes to the correct struct type."""
        parser = PacketParser(self.registry)
        
        # Create a synthetic 2025 MOTION packet (correct size)
        motion_size = ct.sizeof(PacketMotionData_2025)
        raw = _make_header_bytes(2025, PacketId.MOTION, motion_size)
        
        result = parser.parse(raw)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, PacketMotionData_2025)
        self.assertEqual(parser.parsed, 1)

    def test_parser_counts_unknown_packet_id(self):
        """Unknown packet ID is skipped and counted as skipped_unknown."""
        parser = PacketParser(self.registry)
        
        # Synthesize a packet with an unknown ID (255 = not a real PacketId)
        raw = _make_header_bytes(2025, 255, 100)
        
        result = parser.parse(raw)
        self.assertIsNone(result)
        self.assertEqual(parser.skipped_unknown, 1)
        self.assertEqual(parser.parsed, 0)

    def test_parser_counts_unknown_format(self):
        """Unknown format is skipped and counted as skipped_unknown."""
        parser = PacketParser(self.registry)
        
        # Synthesize a packet with unknown format (9999)
        raw = _make_header_bytes(9999, PacketId.MOTION, 100)
        
        result = parser.parse(raw)
        self.assertIsNone(result)
        self.assertEqual(parser.skipped_unknown, 1)
        self.assertEqual(parser.parsed, 0)

    def test_parser_counts_truncated_packet(self):
        """A packet shorter than the expected struct size is malformed."""
        parser = PacketParser(self.registry)
        
        # 2025 MOTION is 1349 bytes; give it only 1000
        raw = _make_header_bytes(2025, PacketId.MOTION, 1000)
        
        result = parser.parse(raw)
        self.assertIsNone(result)
        self.assertEqual(parser.skipped_malformed, 1)
        self.assertEqual(parser.parsed, 0)

    def test_parser_counts_too_short_header(self):
        """A packet shorter than the header (29 bytes) is malformed."""
        parser = PacketParser(self.registry)
        
        # Only 10 bytes, less than header size (29)
        raw = _make_header_bytes(2025, PacketId.MOTION, 10)
        
        result = parser.parse(raw)
        self.assertIsNone(result)
        self.assertEqual(parser.skipped_malformed, 1)
        self.assertEqual(parser.parsed, 0)

    def test_parser_accounting_parsed_plus_skipped_equals_total(self):
        """Parser accounting: parsed + skipped_unknown + skipped_malformed == total calls."""
        parser = PacketParser(self.registry)
        
        # Parse 5 valid packets
        motion_size = ct.sizeof(PacketMotionData_2025)
        for _ in range(5):
            raw = _make_header_bytes(2025, PacketId.MOTION, motion_size)
            parser.parse(raw)
        
        # 1 unknown ID
        parser.parse(_make_header_bytes(2025, 255, 100))
        
        # 1 truncated
        parser.parse(_make_header_bytes(2025, PacketId.LAP_DATA, 100))
        
        # 1 too-short header
        parser.parse(_make_header_bytes(2025, PacketId.MOTION, 10))
        
        total_calls = 8
        total_accounted = parser.parsed + parser.skipped_unknown + parser.skipped_malformed
        self.assertEqual(total_accounted, total_calls)
        self.assertEqual(parser.parsed, 5)


if __name__ == "__main__":
    unittest.main()