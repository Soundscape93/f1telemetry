"""Struct size regression tests for protocol packets.

Verifies that packed ctypes structs match their wire-format sizes across
2025 and 2026 formats. Checks individual structs and the common header.

Run::

    python -m unittest f1telemetry.test.struct_size_tests
    python -m unittest f1telemetry.test.struct_size_tests.StructSizeTest.test_2025_sizes
"""

from __future__ import annotations

import ctypes as ct
import unittest

from f1telemetry.src.protocol.header import PacketHeader
from f1telemetry.src.protocol.v2025 import structs as s25
from f1telemetry.src.protocol.v2026 import structs as s26

SIZES_2025 = {
    "PacketMotionData": 1349,
    "PacketSessionData": 753,
    "PacketLapData": 1285,
    "PacketEventData": 45,
    "PacketParticipantsData": 1284,
    "PacketCarSetupData": 1133,
    "PacketCarTelemetryData": 1352,
    "PacketCarStatusData": 1239,
    "PacketFinalClassificationData": 1042,
    "PacketLobbyInfoData": 954,
    "PacketCarDamageData": 1041,
    "PacketSessionHistoryData": 1460,
    "PacketTyreSetsData": 231,
    "PacketMotionExData": 273,
    "PacketTimeTrialData": 101,
    "PacketLapPositionsData": 1131,
}

SIZES_2026 = {
    "PacketMotionData": 1325,
    "PacketSessionData": 926,
    "PacketLapData": 1399,
    "PacketEventData": 45,
    "PacketParticipantsData": 1470,
    "PacketCarSetupData": 1233,
    "PacketCarTelemetryData": 1448,
    "PacketCarStatusData": 1445,
    "PacketFinalClassificationData": 1134,
    "PacketLobbyInfoData": 1062,
    "PacketCarDamageData": 1133,
    "PacketSessionHistoryData": 1460,
    "PacketTyreSetsData": 231,
    "PacketMotionExData": 273,
    "PacketTimeTrialData": 104,
    "PacketLapPositionsData": 1231,
    "PacketCarTelemetry2Data": 269,
}


class StructSizeTest(unittest.TestCase):
    """Regression tests for struct sizes — each struct in its own sub-test."""

    def test_2025_sizes(self):
        """All 2025 packet structs match their wire-format sizes."""
        for name, size in SIZES_2025.items():
            with self.subTest(struct=name):
                actual = ct.sizeof(getattr(s25, name))
                self.assertEqual(actual, size)

    def test_2026_sizes(self):
        """All 2026 packet structs match their wire-format sizes."""
        for name, size in SIZES_2026.items():
            with self.subTest(struct=name):
                actual = ct.sizeof(getattr(s26, name))
                self.assertEqual(actual, size)

    def test_header_size(self):
        """PacketHeader is exactly 29 bytes (wire format invariant)."""
        self.assertEqual(ct.sizeof(PacketHeader), 29)


if __name__ == "__main__":
    unittest.main()