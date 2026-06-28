"""Capture raw F1 UDP telemetry datagrams to a .f1cap file for later replay and analysis.

The recorder consumes a ``PacketSource`` (live UDP by default) and appends every datagram,
with its arrival time, to a capture file. Going through the same source seam as the rest of
the system means the socket handling lives in one place (``LiveUDPSource``) instead of being
duplicated here.

Usage (CLI)::

    python -m f1telemetry.src.ingest.recorder my_race.f1cap
    python -m f1telemetry.src.ingest.recorder my_race.f1cap --port 20777

For programmatic / GUI use, call :meth: `SessionRecorder.record` with a status callback and
drive the stop through the source's ``stop_event`` (see ``LiveUDPSource``). The output path
must not already exist: the recorder refuses to overwrite an existing capture so a stray
re-run can never destroy a recorded session.
"""

from __future__ import annotations

import argparse
import os
import time
from typing import BinaryIO
from collections.abc import Callable

from .recording import write_header, write_packet
from .sources import LiveUDPSource, PacketSource

# called with (packet_count, byte_count, elapsed_seconds)
StatusCallback = Callable[[int, int, float], None]


class SessionRecorder:
    """Appends every datagram from a ``PacketSource`` to a capture file."""

    def __init__(self, output_path: str, source: PacketSource):
        self.output_path = output_path
        self.source = source
        self.packet_count = 0
        self.byte_count = 0

    def record(self, on_status: StatusCallback | None = None, status_interval: float = 2.0) -> int:
        """Capture datagrams until the source stops yielding, returning the packet count.

        The source decides when capture ends - exhaustion, Ctrl-C (which interrupts the socket),
        or a ``stop_event`` being set. ``on_status`` is invoked periodically and once more at the
        end with the final tally, so a GUI can show live progress. The file is created only once the first
        datagram arrives, (so a failed bind never leaves an empty capture) and is never overwritten.
        """
        if os.path.exists(self.output_path):
            raise FileExistsError(
                f"{self.output_path} already exists; refusing to overwrite a capture. "
                "Choose another name or delete it first."
            )
        
        file: BinaryIO | None = None
        start = time.perf_counter()
        last_status = start
        try:
            for data in self.source:
                if file is None:
                    file = open(self.output_path, "xb")  # xb: created only once packets flow, never overwrites
                    write_header(file)
                write_packet(file, time.time(), data)
                self.packet_count += 1
                self.byte_count += len(data)

                now = time.perf_counter()
                if on_status is not None and now - last_status >= status_interval:
                    on_status(self.packet_count, self.byte_count, now - start)
                    last_status = now
        finally:
            if file is not None:
                file.flush()
                file.close()
            if on_status is not None:
                on_status(self.packet_count, self.byte_count, time.perf_counter() - start)
            return self.packet_count
        
    def record_forever(self, status_interval: float = 2.0) -> None:
        """CLI entry: capture until Ctrl-C, printing status on stdout."""
        print(f"Listening for telemetry, writing to {self.output_path}")
        print("Drive a session, then press Ctrl-c or stop.\n")
        try:
            self.record(on_status=self._print_status, status_interval=status_interval)
        except KeyboardInterrupt:
            pass
        print(f"\nSaved {self.packet_count} packets to {self.output_path}")

    @staticmethod
    def _print_status(packet_count: int, byte_count: int, _elapsed: float) -> None:
        kb = byte_count / 1024
        print(f"\r {packet_count:>7} packets, {kb:>9.1f} KB", end="", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Record raw F1 UDP telemetry datagrams to a .f1cap file")
    parser.add_argument("output", help="Path to the output .f1cap file (must not already exist)")
    parser.add_argument("--host", default="0.0.0.0", help="bind address (default: all)")
    parser.add_argument("--port", type=int, default=20777, help="bind port (default: 20777)")
    args = parser.parse_args()

    source = LiveUDPSource(host=args.host, port=args.port)
    recorder = SessionRecorder(args.output, source)
    try:
        recorder.record_forever()
    except FileExistsError as exc:
        raise SystemExit(str(exc))
    except OSError as exc:
        raise SystemExit(f"could not start recorder: {exc}")


if __name__ == "__main__":
    main()
