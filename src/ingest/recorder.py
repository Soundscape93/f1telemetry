"""Capture raw F1 UDP telemetry datagrams to a .f1cap file for later replay and analysis.

The recorder consumes a ``PacketSource`` (live UDP by default) and appends every datagram,
with its arrival time, to a capture file. Going through the same source seam as the rest of
the system means the socket handling lives in one place (``LiveUDPSource``) instead of being
duplicated here.

Usage::

    python -m f1telemetry.src.ingest.recorder my_race.f1cap
    python -m f1telemetry.src.ingest.recorder my_race.f1cap --port 20777

The output path must not already exist: the recorder refuses to overwrite an existing capture
so a stray re-run can never destroy a recorded session.
"""

from __future__ import annotations

import argparse
import os
import time
from typing import BinaryIO

from .recording import write_header, write_packet
from .sources import LiveUDPSource, PacketSource


class SessionRecorder:
    """Appends every datagram from a ``PacketSource`` to a capture file."""

    def __init__(self, output_path: str, source: PacketSource):
        self.output_path = output_path
        self.source = source
        self.packet_count = 0
        self.byte_count = 0

    def record_forever(self, status_interval: float = 2.0) -> None:
        """Capture until interrupted with Ctrl-C. Prints status every ``status_interval`` seconds.

        Refuses to start if ``output_path`` already exists, and only creates the file once the
        first datagram arrives - so a failed bind never leaves an empty capture behind, and a
        re-run never clobbers an existing one.
        """
        if os.path.exists(self.output_path):
            raise FileExistsError(
                f"{self.output_path} already exists; refusing to overwrite a capture. "
                "Choose another name or delete it first."
            )

        print(f"Listening for telemetry, writing to {self.output_path}")
        print("Drive a session, then press Ctrl-C to stop.\n")

        file: BinaryIO | None = None
        last_status = time.perf_counter()
        try:
            for data in self.source:
                if file is None:
                    file = open(self.output_path, "xb")  # xb: created only once packets flow, never overwrites
                    write_header(file)
                write_packet(file, time.time(), data)
                self.packet_count += 1
                self.byte_count += len(data)

                now = time.perf_counter()
                if now - last_status >= status_interval:
                    self._print_status()
                    last_status = now
        except KeyboardInterrupt:
            pass
        finally:
            if file is not None:
                file.flush()
                file.close()
            self._print_status()
            print(f"\nSaved {self.packet_count} packets to {self.output_path}")

    def _print_status(self) -> None:
        kb = self.byte_count / 1024
        print(f"\r {self.packet_count:>7} packets, {kb:>9.1f} KB", end="", flush=True)


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
