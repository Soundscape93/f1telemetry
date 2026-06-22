"""Round-trip and validation tests for the ingest layer (.f1cap format + replay + recorder).

These exercise recording.py, FileReplaySource and SessionRecorder with synthetic datagrams,
so they are deterministic and need no real game capture. The synthetic datagrams mimic the F1
header just enough to assert the offset convention the rest of the system dispatches on:
uint16 packet format at offset 0, packet id at offset 6.

Run::

    python -m f1telemetry.test.well_formed_packets_tests
"""

from __future__ import annotations

import contextlib
import io
import os
import struct
import tempfile
import unittest

from f1telemetry.src.ingest.recorder import SessionRecorder
from f1telemetry.src.ingest.recording import (
    MAGIC,
    RECORDING_FORMAT_VERSION,
    _MAX_PACKET_LEN,
    _RECORD,
    read_header,
    read_packet,
    write_header,
    write_packet,
)
from f1telemetry.src.ingest.sources import FileReplaySource, PacketSource


def _make_datagram(fmt: int, packet_id: int, size: int = 24) -> bytes:
    """A synthetic F1 datagram: uint16 format at offset 0, packet id at offset 6."""
    buf = bytearray(size)
    struct.pack_into("<H", buf, 0, fmt)
    buf[6] = packet_id
    for i in range(7, size):           # unique-ish tail so a byte-exact round-trip is meaningful
        buf[i] = (packet_id + i) & 0xFF
    return bytes(buf)


class _ListSource(PacketSource):
    """A finite in-memory PacketSource, so the recorder can be tested without a socket."""

    def __init__(self, items: list[bytes]):
        self._items = items

    def __iter__(self):
        return iter(self._items)


class IngestRoundTripTest(unittest.TestCase):
    def _temp_path(self, create: bool) -> str:
        fd, path = tempfile.mkstemp(suffix=".f1cap")
        os.close(fd)
        if not create:
            os.remove(path)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path

    def _write_capture(self, datagrams: list[bytes]) -> str:
        path = self._temp_path(create=True)
        with open(path, "wb") as f:
            write_header(f)
            for i, data in enumerate(datagrams):
                write_packet(f, float(i), data)
        return path

    def test_round_trip_preserves_bytes_and_order(self):
        datagrams = [
            _make_datagram(2025, 0),
            _make_datagram(2025, 6),
            _make_datagram(2025, 2),
            _make_datagram(2026, 3),
        ]
        path = self._write_capture(datagrams)
        self.assertEqual(list(FileReplaySource(path, realtime=False)), datagrams)

    def test_header_offset_convention(self):
        # the system dispatches on (packet_format, packet_id); pin those offsets down
        datagrams = [_make_datagram(2025, 6), _make_datagram(2026, 3)]
        path = self._write_capture(datagrams)
        parsed = [
            (struct.unpack_from("<H", raw, 0)[0], raw[6])
            for raw in FileReplaySource(path, realtime=False)
        ]
        self.assertEqual(parsed, [(2025, 6), (2026, 3)])

    def test_empty_capture_yields_no_packets(self):
        path = self._write_capture([])
        self.assertEqual(list(FileReplaySource(path, realtime=False)), [])

    def test_clean_eof_returns_none(self):
        path = self._write_capture([_make_datagram(2025, 0)])
        with open(path, "rb") as f:
            read_header(f)
            self.assertIsNotNone(read_packet(f))
            self.assertIsNone(read_packet(f))

    def test_bad_magic_rejected(self):
        path = self._temp_path(create=True)
        with open(path, "wb") as f:
            f.write(b"NOTACAP_" + b"\x01\x00")
        with open(path, "rb") as f, self.assertRaises(ValueError):
            read_header(f)

    def test_newer_version_rejected(self):
        path = self._temp_path(create=True)
        with open(path, "wb") as f:
            f.write(struct.pack("<8sH", MAGIC, RECORDING_FORMAT_VERSION + 1))
        with open(path, "rb") as f, self.assertRaises(ValueError):
            read_header(f)

    def test_oversized_length_rejected(self):
        path = self._temp_path(create=True)
        with open(path, "wb") as f:
            write_header(f)
            f.write(_RECORD.pack(0.0, _MAX_PACKET_LEN + 1))   # claims an impossible size
        with open(path, "rb") as f:
            read_header(f)
            with self.assertRaises(ValueError):
                read_packet(f)

    def test_truncated_payload_rejected(self):
        path = self._temp_path(create=True)
        with open(path, "wb") as f:
            write_header(f)
            f.write(_RECORD.pack(0.0, 50))   # promises 50 bytes...
            f.write(b"\x00" * 10)            # ...but only 10 are present
        with open(path, "rb") as f:
            read_header(f)
            with self.assertRaises(ValueError):
                read_packet(f)

    def test_recorder_writes_replayable_capture(self):
        datagrams = [_make_datagram(2025, 0), _make_datagram(2025, 6)]
        path = self._temp_path(create=False)
        recorder = SessionRecorder(path, _ListSource(datagrams))
        with contextlib.redirect_stdout(io.StringIO()):
            recorder.record_forever()
        self.assertEqual(recorder.packet_count, 2)
        self.assertEqual(list(FileReplaySource(path, realtime=False)), datagrams)

    def test_recorder_refuses_to_overwrite_existing_capture(self):
        path = self._write_capture([_make_datagram(2025, 0)])
        recorder = SessionRecorder(path, _ListSource([_make_datagram(2025, 1)]))
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(FileExistsError):
            recorder.record_forever()
        # the original capture must be untouched (still exactly its one packet)
        self.assertEqual(len(list(FileReplaySource(path, realtime=False))), 1)


if __name__ == "__main__":
    unittest.main()
