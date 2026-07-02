"""Assembler - sequences a stream of decoded packets into completed SessionResults.

This is the stateful counterpart to the normalizer. It does what stateless per-packet
conversion cannot: hold state across packets and across time. Two interleaved splits:
    * session split on header.session_uid - on change, the prevous session is
      finalized and emitted, and a fresh one begings. The final, in-progress session is
      flushed at the end of the stream.
    * lap split on lap_data.current_lap_num - per frame samples accumulate into a buffer;
      when the lap number increments, the completed lap's buffer becomas a LapTrace, paired
      whith the lap's timing, and emitted as a Lap

Within a frame, the player's Lap Data and Car Telemetry entries are joined by matching
header.frame_identifier before becoming one sample. Routing is by header.packet_id,
so the same code drives both 2025 and 2026 streams.

Lap times, sectors, and validitiy come from the Session History (authorative, sent through
the session and refreshed in a bulk update at the end) - NOT from live Lap Data. The trace
pipeline only decides which frames belong to which lap; the join is by lap number:
a lap is emitted when it has both a captured trace and a Session History entry with a real
(non-zero) lap time. This makes the final lap unremarkable, drops in-laps (their
Session History time is 0).
"""
from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Iterator

from ..domain.models import Lap, LapTrace, Participant, SessionResult
from ..domain.normalizer import (
    Sample,
    build_trace,
    normalize_classification,
    merge_participant,
    normalize_participants,
    normalize_session,
    telemetry_sample,
)
from ..protocol.enums import PacketId

# A cleanly caputred lap begins near the start line. A lap whose sample is well past
# it was joined mid-way (started recording) or is an out-lap, so no clean trace is kept.
_MAX_LAP_START_DISTANCE_M = 200  # meters

_LAP_VALID_BIT = 0x08  # bit 3 of lap_valid_bit_flags = whole lap valid


def _sector_ms(minutes_part: int, ms_part: int) -> int:
    """Recombine the spec's split sector time (minutes + millisecond remainder)."""
    return minutes_part * 60_000 + ms_part


class _SessionBuilder:
    """Accumulates one session's packet into a single SessionResult."""

    def __init__(self) -> None:
        self._scaffold: SessionResult | None = None
        self._roster_by_index: dict[int, Participant] = {}  # merged across all Participants frames
        self._session_history = None            # the player's latest Session History packet
        self._final_classification = None       # the final classification packet
        self._last_car_status = None            # the player's latest Car Status entry

        self._traces: dict[int, LapTrace] = {}  # lap_number -> captured trace

        # current-lap accumulation:
        self._cur_lap: int | None = None
        self._buffer: list[Sample] = []

        # frame-join staging:
        self._pending_lap = None
        self._pending_lap_frame: int | None = None
        self._pending_car_telemetry = None
        self._pending_car_telemetry_frame: int | None = None

    def feed(self, packet) -> None:
        """Route a packet to the appropriate handler. The SessionResult scaffold is built from the Session packet;
        the roster is built from the Participants packet; the final classification is captured from the Final Classification
        packet; the player's Session History is captured from the Session History packet; and the current lap's
        telemetry is accumulated from the Lap Data and Car Telemetry packets."""
        pid = packet.header.packet_id
        if pid == PacketId.SESSION:
            self._scaffold = normalize_session(packet)
        elif pid == PacketId.PARTICIPANTS:
            # union aross frames: a late (post-race) frame can drop cars, so merge rather
            # than overwrite, keeping the most complete identity seen for each car index.
            for participant in normalize_participants(packet):
                idx = participant.vehicle_index
                self._roster_by_index[idx] = merge_participant(
                    self._roster_by_index.get(idx), participant
                )
        elif pid == PacketId.SESSION_HISTORY:
            if packet.car_idx == packet.header.player_car_index:
                self._session_history = packet              # last-write wins -> end-of-session bulk
        elif pid == PacketId.FINAL_CLASSIFICATION:
            self._final_classification = packet
        elif pid == PacketId.CAR_STATUS:
            idx = packet.header.player_car_index
            if idx >= len(packet.car_status_data):  # player not in the array this frame (lobby/spectator)
                return
            self._last_car_status = packet.car_status_data[idx]
        elif pid == PacketId.LAP_DATA:
            idx = packet.header.player_car_index
            if idx >= len(packet.lap_data):         # player not in the array this frame (lobby/spectator)
                return
            self._pending_lap = packet.lap_data[idx]
            self._pending_lap_frame = packet.header.frame_identifier
            self._try_frame_join()
        elif pid == PacketId.CAR_TELEMETRY:
            idx = packet.header.player_car_index
            if idx >= len(packet.car_telemetry_data):  # player not in the array this frame (lobby/spectator)
                return
            self._pending_car_telemetry = packet.car_telemetry_data[idx]
            self._pending_car_telemetry_frame = packet.header.frame_identifier
            self._try_frame_join()

    def _try_frame_join(self) -> None:
        """If both the Lap Data and Car Telemetry entries for the same frame are present,
        join them into a single Sample and accumulate it into the current lap's buffer."""
        if (
            self._pending_lap is not None
            and self._pending_car_telemetry is not None
            and self._pending_lap_frame == self._pending_car_telemetry_frame
        ):
            self._on_frame(self._pending_lap, self._pending_car_telemetry)
            self._pending_lap = None
            self._pending_car_telemetry = None

    def _on_frame(self, lap_data, car_telemetry) -> None:
        """Accumulate one frame's joined telemetry into the current lap's buffer, and finalize
        the lap if the lap number has incremented.
        """
        lap_num = lap_data.current_lap_num
        if self._cur_lap is None:
            self._cur_lap = lap_num
        elif lap_num != self._cur_lap:
            self._store_trace(self._cur_lap)
            self._cur_lap = lap_num
            self._buffer = []
        self._buffer.append(telemetry_sample(lap_data, car_telemetry, self._last_car_status))

    def _store_trace(self, lap_number: int) -> None:
        """Stash the current buffer as a lap_number's trace, unless it was an out-lap
        or joined mid-lap (didn't start near the start line)."""
        samples = self._buffer
        if not samples:
            return
        if samples[0].distance > _MAX_LAP_START_DISTANCE_M:
            return
        self._traces[lap_number] = build_trace(samples)

    def _build_laps(self) -> tuple[Lap, ...]:
        """Join captured traces with Session History timing, by lap number."""
        sh = self._session_history
        laps = []
        for lap_number in sorted(self._traces):
            if sh is None or not (1 <= lap_number <= sh.num_laps):
                continue
            entry = sh.lap_history_data[lap_number - 1]
            total = entry.lap_time_in_ms
            if total <= 0:          # lap not completed (in-lap / current partial)
                continue
            laps.append(
                Lap(
                    lap_number=lap_number,
                    lap_time_ms=total,
                    sector1_ms=_sector_ms(entry.sector1_time_minutes_part, entry.sector1_time_ms_part) or None,
                    sector2_ms=_sector_ms(entry.sector2_time_minutes_part, entry.sector2_time_ms_part) or None,
                    sector3_ms=_sector_ms(entry.sector3_time_minutes_part, entry.sector3_time_ms_part) or None,
                    is_valid=bool(entry.lap_valid_bit_flags & _LAP_VALID_BIT),
                    trace=self._traces[lap_number],
                )
            )
        return tuple(laps)
    
    def build(self) -> SessionResult | None:
        """Finalize the session. Returns None if no Session packet was ever seen."""
        if self._scaffold is None:
            return None
        # capture the final (trailing) lap's trace; its time comes from Session History
        if self._cur_lap is not None:
            self._store_trace(self._cur_lap)

        roster = tuple(self._roster_by_index[i] for i in sorted(self._roster_by_index))

        classification = None
        if self._final_classification is not None:
            classification = normalize_classification(self._final_classification, roster)

        return dataclasses.replace(
            self._scaffold,
            participants=roster,
            laps=self._build_laps(),
            classification=classification,
        )

class SessionAssembler:
    """Splits a packet stream into sessions by session_uid, emitting one SessionResult
    per session as each boundary is crossed (and the last via finish())."""

    def __init__(self) -> None:
        self._current_uid: int | None = None
        self._builder = _SessionBuilder()

    def process(self, packet) -> SessionResult | None:
        uid = packet.header.session_uid
        if uid == 0:            # frame-1 init packets: no session yet, ignore
            return None
        
        emitted = None
        if self._current_uid is None:
            self._current_uid = uid
        elif uid != self._current_uid:
            emitted = self._builder.build()
            self._current_uid = uid
            self._builder = _SessionBuilder()
        
        self._builder.feed(packet)
        return emitted
    
    def finish(self) -> SessionResult | None:
        """Flush the final, in progress session at the end of the stream."""
        return self._builder.build()
    
def assemble(packets: Iterable) -> Iterator[SessionResult]:
    """Run the assembler over a stream of decoded packets, yielding one SessionResult
    per session. The final session is flushed when the stream ends."""
    assembler = SessionAssembler()
    for packet in packets:
        result = assembler.process(packet)
        if result is not None:
            yield result
    final = assembler.finish()
    if final is not None:
            yield final