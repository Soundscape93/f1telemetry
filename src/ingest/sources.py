"""Packet sources - the seam that makes the rest of the system agnostic to where packets come from.

``LiveUDPSource`` pulls datagrams off the network; ``FileReplaySource`` replays
a .f1cap file. Both satisfy the same ``PacketSource`` interface and yield
raw bytes, so every downstream (parser, normalizer, assembler, analysis)
runs identically whether the data is live or replayed.
This is the key to making the system testable and debuggable.
"""

from __future__ import annotations

import logging
import socket
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
import threading

from .recording import read_header, read_packet
from .archive import open_capture

log = logging.getLogger(__name__)

_RECV_BUFFER = 4096        # bytes; largest F1 UDP datagram is ~1460, but we can be generous
_SOCKET_TIMEOUT = 0.5      # seconds; wake up periodically so Ctrl-C stays responsive

# The kernel buffers datagrams while we're between recvfrom calls; once it's fully silent
# drops the rest. Windows defaults to 65 KB, which at the ~0.2 MB/s telemetry rate is only ~0.3 s
# of cover (Linux defaults to ~208 KB, barely 1 s). If the process is descheduled - screen lock,
# power management, a foreground fullscreen game - everything past that vanishes, and one-shot
# packets like Final Classification are gone for good. Ask for megabytes; the OS clamps to its own
# maximum, so this is a request rather than a guarantee - hence logging what was actually granted.
_RCVBUF_TARGET = 8 * 1024 * 1024

# One loop iteration should never take much longer than _SOCKET_TIMEOUT: when the game is silent
# recvfrom times out on schedule. A far longer iteration means *we* weren't running - a different
# fault from the game not sending, and the one that loses packets.
_STALL_WARN_SECONDS = 2.0


class PacketSource(ABC):
    """Abstract base class for sources; yields raw UDP datagrams, one per iteration."""

    @abstractmethod
    def __iter__(self) -> Iterator[bytes]: ...


class LiveUDPSource(PacketSource):
    """Listens on the telemetry port and yields every datagram as it arrives.

    Stops when the consumer stops iterating (Ctrl-C in the CLI) or, for programmatic
    control, when ``stop_event`` is set. This event is checked once per socket-timeout cycle,
    so a GUI stop button ends capture within ``_SOCKET_TIMEOUT`` even while the game is idle
    and no datagrams are arriving. The socket is closed when iteration ends.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 20777, stop_event: threading.Event | None = None):
        self.host = host
        self.port = port
        self._stop_event = stop_event

    def __iter__(self) -> Iterator[bytes]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, _RCVBUF_TARGET)
        except OSError as exc:            # never fatal; we just fall back to the OS default
            log.warning("Could not raise the UDP receive buffer: %s", exc)
        granted = sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
        sock.bind((self.host, self.port))
        sock.settimeout(_SOCKET_TIMEOUT)
        log.info("listening on %s:%d, receive buffer %.1f KB (asked for %.1f KB)",
                 self.host, self.port, granted / 1024, _RCVBUF_TARGET / 1024)
        try:
            while True:
                # checked at the top of every cycle, so it catches both the idle case
                # (after a timeout) and the active case (after yielding a datagram)
                if self._stop_event is not None and self._stop_event.is_set():
                    return
                cycle_start = time.monotonic()
                try:
                    data, _addr = sock.recvfrom(_RECV_BUFFER)
                except socket.timeout:
                    data = None
                stalled = time.monotonic() - cycle_start
                if stalled > _STALL_WARN_SECONDS:
                    # We were descheduled: the socket timeout should have returned long ago.
                    # Anything the kernel buffered its limit is already lost.
                    log.warning(
                        "recorder stalled %.1fs (socket timeout is %.1fs) - datagrams beyond the "
                        "%.1f KB receive buffer were dropped by the OS",
                        stalled, _SOCKET_TIMEOUT, granted / 1024)
                if data is None:
                    continue
                yield data
        finally:
            sock.close()


class FileReplaySource(PacketSource):
    """Replays datagrams from a .f1cap file.

    ``realtime=True`` reproduces the original inter-packet timing and ordering, which is what
    the assembler's frame-join logic needs to be exercised realistically. ``realtime=False``
    yields packets as fast as possible - useful when iterating on the parser or analysis,
    where timing is irrelevant.

    ``speed`` scales realtime playback (2.0 = twice as fast as recorded).
    """

    def __init__(self, path: str, realtime: bool = True, speed: float = 1.0):
        if speed <= 0:
            raise ValueError("speed must be positive")
        self.path = path
        self.realtime = realtime
        self.speed = speed

    def __iter__(self) -> Iterator[bytes]:
        with open_capture(self.path) as f:
            read_header(f)
            anchor_wall: float | None = None
            anchor_rec: float | None = None
            while True:
                packet = read_packet(f)
                if packet is None:
                    return
                if self.realtime:
                    if anchor_wall is None:
                        # first packet sets the clock; it plays immediately
                        anchor_wall = time.perf_counter()
                        anchor_rec = packet.recv_time
                    else:
                        # sleep until the packet's scheduled moment, anchored to the start so
                        # any downstream processing time is absorbed rather than accumulating
                        target = anchor_wall + (packet.recv_time - anchor_rec) / self.speed
                        delay = target - time.perf_counter()
                        if delay > 0:
                            time.sleep(delay)
                yield packet.data
