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

    def test_archive_round_trips_every_codec(self):
        """Bytes, order, and the remove-original default, for every codec we can write."""
        from f1telemetry.src.ingest.archive import CODEC_GZIP, CODEC_ZSTD, archive_capture

        datagrams = [_make_datagram(2025, 0),
                     _make_datagram(2025, 6),
                     _make_datagram(2026, 2),
                     _make_datagram(2026, 3)
        ]
        for codec, suffix in ((CODEC_GZIP, ".gz"), (CODEC_ZSTD, ".zst")):
            with self.subTest(codec=codec):
                path = self._write_capture(datagrams)
                archive_path = archive_capture(path, codec=codec)
                self.addCleanup(lambda p=archive_path: os.path.exists(p) and os.remove(p))

                self.assertTrue(str(archive_path).endswith(suffix))
                self.assertFalse(os.path.exists(path),
                                 "archive_capture should remove the original capture by default")
                self.assertEqual(list(FileReplaySource(archive_path, realtime=False)), datagrams,
                                 "replay of the archived capture should yield the same datagrams in order")
    
    def test_default_codec_is_zstd(self):
        from f1telemetry.src.ingest.archive import CODEC_ZSTD, archive_capture, capture_codec

        path = self._write_capture([_make_datagram(2025, 0)])
        archive_path = archive_capture(path)
        self.addCleanup(lambda: os.path.exists(archive_path) and os.remove(archive_path))
        self.assertEqual(capture_codec(archive_path), CODEC_ZSTD)
    
    def test_archive_capture_can_keep_original_when_requested(self):
        """Load-bearing for the ingest flow: the worker archives *before* it ingests, and
        deletes the raw capture only once ingest has proven the archive readable."""
        from f1telemetry.src.ingest.archive import archive_capture

        datagrams = [_make_datagram(2025, 0), _make_datagram(2025, 6)]
        path = self._write_capture(datagrams)

        archive_path = archive_capture(path, remove_original=False)
        self.addCleanup(lambda: os.path.exists(archive_path) and os.remove(archive_path))

        self.assertTrue(os.path.exists(path),
                        "archive_capture should keep the original capture when remove_original=False")
        self.assertEqual(list(FileReplaySource(str(archive_path), realtime=False)), datagrams,
                         "replay of the archived capture should yield the same datagrams in order")

    def test_archive_preserves_recv_time(self):
        """Every codec must preserve recv_time - SessionResult.recorded_at is derived from it."""
        from f1telemetry.src.ingest.archive import (CODEC_GZIP, CODEC_ZSTD, archive_capture,
                                                    open_capture)

        datagrams = [_make_datagram(2025, 0), _make_datagram(2025, 6), _make_datagram(2025, 3)]
        for codec in (CODEC_GZIP, CODEC_ZSTD):
            with self.subTest(codec=codec):
                path = self._write_capture(datagrams)
                archive_path = archive_capture(path, codec=codec)
                self.addCleanup(lambda p=archive_path: os.path.exists(p) and os.remove(p))

                recovered = []
                with open_capture(str(archive_path)) as f:
                    read_header(f)
                    while (packet := read_packet(f)) is not None:
                        recovered.append((packet.recv_time, packet.data))

                self.assertEqual(
                    recovered,
                    [(float(i), d) for i, d in enumerate(datagrams)],
                    "the archive round-trip must preserve both recv_time and payload bytes")

    def test_hash_is_codec_independent(self):
        """A gzip -> zstd re-archive changes every byte on disk but not the capture's identity.

        This is what lets the content hash be the dedupe key for league capture imports: the
        hash is taken over the decompressed payload, never the archive.
        """
        from f1telemetry.src.ingest.archive import (CODEC_GZIP, CODEC_ZSTD, HashingReader,
                                                    archive_capture, open_capture)

        datagrams = [_make_datagram(2025, 0), _make_datagram(2026, 3)]
        hashes = {}
        for codec in (CODEC_GZIP, CODEC_ZSTD):
            path = self._write_capture(datagrams)
            archive_path = archive_capture(path, codec=codec)
            self.addCleanup(lambda p=archive_path: os.path.exists(p) and os.remove(p))

            with open_capture(str(archive_path)) as fh:
                reader = HashingReader(fh)
                while reader.read(4096):
                    pass
                hashes[codec] = reader.content_hash

        self.assertEqual(hashes[CODEC_GZIP], hashes[CODEC_ZSTD],
                         "the content hash must be taken over the decompressed payload, so a "
                         "re-archived capture keeps its identity")


if __name__ == "__main__":
    unittest.main()
