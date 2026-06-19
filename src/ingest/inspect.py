"""Summarize a .f1cap capture: how many of each (packet format, packet id) it holds.

A quick eyeball check that a recording is well-formed and contains the packet types you
expect - the diagnostic counterpart to the synthetic round-trip tests. It reads through the
same recording layer the analysis uses, so a corrupt or truncated capture surfaces the same
errors here as it would downstream.

Run::

    python -m f1telemetry.src.ingest.inspect my_race.f1cap
"""

from __future__ import annotations

import argparse
import struct

from .recording import read_header, read_packet

# F1 25 / F1 26 packet ids (see Claude.md MVP subset). 15 is F1 25+, 16 is F1 26 only.
_PACKET_NAMES = {
    0: "Motion",
    1: "Session",
    2: "Lap Data",
    3: "Event",
    4: "Participants",
    5: "Car Setups",
    6: "Car Telemetry",
    7: "Car Status",
    8: "Final Classification",
    9: "Lobby Info",
    10: "Car Damage",
    11: "Session History",
    12: "Tyre Sets",
    13: "Motion Ex",
    14: "Time Trial",
    15: "Lap Positions",
    16: "Car Telemetry 2",
}

_HEADER_MIN_LEN = 7   # need bytes 0-1 (packet format) and byte 6 (packet id)


def summarize(path: str) -> None:
    """Print a per-(format, packet id) tally plus totals for one capture file."""
    tally: dict[tuple[int, int], int] = {}
    total_bytes = 0
    first_time: float | None = None
    last_time: float | None = None

    with open(path, "rb") as f:
        read_header(f)
        while True:
            packet = read_packet(f)
            if packet is None:
                break
            raw = packet.data
            if len(raw) < _HEADER_MIN_LEN:
                continue                              # too short to carry a header
            fmt = struct.unpack_from("<H", raw, 0)[0]  # m_packetFormat
            pid = raw[6]                               # m_packetId
            tally[(fmt, pid)] = tally.get((fmt, pid), 0) + 1
            total_bytes += len(raw)
            if first_time is None:
                first_time = packet.recv_time
            last_time = packet.recv_time

    for (fmt, pid), count in sorted(tally.items()):
        name = _PACKET_NAMES.get(pid, "unknown")
        print(f"format {fmt}, packet {pid:3d} ({name}): {count} packets")

    total = sum(tally.values())
    duration = (last_time - first_time) if first_time is not None and last_time is not None else 0.0
    print(
        f"\n{total} packets, {total_bytes / 1024:.1f} KB over {duration:.1f} s "
        f"({len(tally)} distinct format/packet types)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize the packets in a .f1cap capture")
    parser.add_argument("capture", help="Path to a .f1cap file")
    args = parser.parse_args()
    summarize(args.capture)


if __name__ == "__main__":
    main()
