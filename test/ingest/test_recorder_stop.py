"""Tests for the capture looü and its cooperative stop - no Qt, real loopback UDP.

These cover the tricky parts of recording: that a stop request acutally halts the
loop (even when idle), that the captured file is intact and replayable, that the
packet tally is right, and that an idle stop leaves no emtpy capture behind.
"""

from __future__ import annotations

import contextlib
import os
import socket
import tempfile
import threading
import time
import unittest

from f1telemetry.src.ingest.recorder import SessionRecorder
from f1telemetry.src.ingest.sources import FileReplaySource, LiveUDPSource


def _free_udp_port() -> int:
    """Return a free UDP port on localhost."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _temp_capture_path() -> str:
    """Return a temporary file path for a capture file."""
    fd, path = tempfile.mkstemp(suffix=".f1cap")
    os.close(fd)
    os.unlink(path)         # the recorder refuses to overwrite; it must not pre-exist
    return path


class RecorderStopTest(unittest.TestCase):
    """Test that the capture loop stops cleanly and leaves a valid file."""
    def setUp(self):
        """Set up a temporary capture path and a free UDP port."""
        self.port = _free_udp_port()
        self.path = _temp_capture_path()

    def tearDown(self):
        """Clean up the temporary capture file if it exists."""
        if os.path.exists(self.path):
            os.unlink(self.path)

    def _run_recorder(self, stop_event, on_status=None):
        """Run the recorder in a background thread, returning the recorder and thread."""
        recorder = SessionRecorder(
            self.path, LiveUDPSource("127.0.0.1", self.port, stop_event=stop_event)
        )
        thread = threading.Thread(
            target=lambda: recorder.record(on_status=on_status, status_interval=0.05)
        )
        thread.start()
        return recorder, thread
    
    def test_captures_and_stops_cleanly(self):
        """Test that the recorder captures packets and stops cleanly when requested."""
        stop = threading.Event()
        statuses: list[tuple[int, int, float]] = []
        recorder, thread = self._run_recorder(stop, on_status=lambda c, b, e: statuses.append((c, b, e)))
        time.sleep(0.3)  # let it bind and ilde trough some timeout cycles

        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as sender:
            for _ in range(5):
                sender.sendto(b"\x07" + b"x" * 1459, ("127.0.0.1", self.port))  # 1460 byte datagram
                self.addClassCleanup(sender.close)
                time.sleep(0.05)
        time.sleep(0.2)

        stop.set()
        thread.join(timeout=3)

        self.assertFalse(thread.is_alive(), "Recorder did not stop after the event was set")
        self.assertEqual(recorder.packet_count, 5, "Recorder did not capture the expected number of packets")
        self.assertTrue(os.path.exists(self.path), "Recorder did not create a capture file")
        replayed = list(FileReplaySource(self.path, realtime=False))
        self.assertEqual([len(d) for d in replayed], [1460] * 5, "Replayed packets do not match the expected size")
        self.assertTrue(statuses and statuses[-1][0] == 5, "final status callback should report 5 packets captured")

    def test_idle_stop_writes_no_file(self):
        """Test that stopping the recorder without sending any packets leaves no file behind."""
        stop = threading.Event()
        recorder, thread = self._run_recorder(stop)
        time.sleep(0.3)  # never send anything
        stop.set()
        thread.join(timeout=3)

        self.assertFalse(thread.is_alive(), "Recorder did not stop after the event was set")
        self.assertEqual(recorder.packet_count, 0, "Recorder should not have captured any packets")
        self.assertFalse(os.path.exists(self.path), "an idle stop must not leave an empty capture file behind")

    def test_refuses_to_overwrite_existing_capture(self):
        """Test that the recorder refuses to overwrite an existing capture file."""
        with open(self.path, "wb") as f:
            f.write(b"existing")
        recorder = SessionRecorder(self.path, LiveUDPSource("127.0.0.1", self.port))
        with self.assertRaises(FileExistsError):
            recorder.record()


if __name__ == "__main__":
    unittest.main()