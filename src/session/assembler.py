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
import math
from collections.abc import Iterable, Iterator

from ..domain.models import (
    CarDamage,
    Lap,
    LapTyreContext,
    Participant,
    SessionResult,
    SetupSnapshot,
)

from ..domain.normalizer import (
    Sample,
    build_trace,
    motion_sample,
    normalize_classification,
    reconstruct_classification,
    merge_participant,
    normalize_participants,
    normalize_session,
    normalize_setup,
    normalize_tyre_context,
    normalize_car_damage,
    telemetry_sample,
)
from ..protocol.enums import PacketId

# A cleanly caputred lap begins near the start line. A lap whose sample is well past
# it was joined mid-way (started recording) or is an out-lap, so no clean trace is kept.
_MAX_LAP_START_DISTANCE_M = 200  # meters

_LAP_VALID_BIT = 0x08  # bit 3 of lap_valid_bit_flags = whole lap valid

# lapDistance (m_lapDistance) is NEGATIVE before the car crosses the start/finish line and only
# becomes 0..track-length on the lap proper. The formation lap (race lap 1) and out-laps share their
# current_lap_num with the timed lap that follows, so a lap's raw buffer can carry a pre-line segment
# (negative, or a whole formation/out lap) in front of the real 0..L pass. A backward jump larger
# than this marks such a boundary within one buffer (the s/f line reset).
_LAP_RESET_DROP_M = 300  # meters


def _sector_ms(minutes_part: int, ms_part: int) -> int:
    """Recombine the spec's split sector time (minutes + millisecond remainder)."""
    return minutes_part * 60_000 + ms_part


def _drop_leading_negatives(run: list[Sample]) -> list[Sample]:
    """Drop a run's leading pre-line (negative lapDistance) samples so it starts at the s/f line."""
    i = 0
    while i < len(run) and run[i].distance < 0:
        i += 1
    return run[i:]


def _split_runs(samples: list[Sample]) -> list[list[Sample]]:
    """Split a lap buffer into runs at each s/f line reset, each starting at the line.

    A raw buffer can carry more than one 0..track-length pass under a single current_lap_num: a
    formation/out lap in front (pre-line, negative lapDistance), a post-finish slow-down/in-lap
    behind, and - in qualifying, where the game keeps one lap number across an in-lap, the
    following out-lap and the next flying lap - several full laps. Each is separated from the next
    by a large backward jump in lapDistance (the s/f line reset); a small backward blip
    (< ``_LAP_RESET_DROP_M``) is treated as noise, not a boundary, so clean laps are never split.
    Each run's leading pre-line (negative) samples are dropped; runs left empty are omitted.
    """
    if not samples:
        return []
    runs: list[list[Sample]] = [[samples[0]]]
    for i in range(1, len(samples)):
        if samples[i].distance < samples[i - 1].distance - _LAP_RESET_DROP_M:
            runs.append([samples[i]])                   # a line reset starts a new run
        else:
            runs[-1].append(samples[i])
    return [clipped for run in runs if (clipped := _drop_leading_negatives(run))]


def _longest_run(runs: list[list[Sample]]) -> list[Sample]:
    """The run covering the most distance; ties -> the later run (timed lap follows an out-lap)."""
    best: list[Sample] = []
    best_span = -1.0
    for run in runs:
        span = run[-1].distance - run[0].distance
        if span >= best_span:
            best, best_span = run, span
    return best


def _estimate_lap_ms(run: list[Sample]) -> float:
    """Estimate a run's duration by integrating dt = distance / speed over its samples.

    Speed is km/h; converting to m/s yields seconds. This is independent of the sample rate, so it
    can be compared against a Session History lap time to tell which run is the timed lap: over the
    same distance an in-lap or out-lap takes noticeably longer than the flying lap.
    """
    total_s = 0.0
    for a, b in zip(run, run[1:]):
        dd = b.distance - a.distance
        v = (a.speed + b.speed) / 2.0 * (1000.0 / 3600.0)  # km/h -> m/s
        if dd > 0 and v > 0:
            total_s += dd / v
    return total_s * 1000.0


def _select_timed_run(runs: list[list[Sample]], target_ms: int | None) -> list[Sample]:
    """Pick the run that is the lap Session History timed at ``target_ms``.

    With a known lap time and more than one full run (qualifying's in/out/flying laps share one
    current_lap_num), choose the run whose estimated duration is closest to it - the flying lap,
    not the slower in/out laps. Without a time, or with a single run, fall back to the longest run
    (the full 0..L pass) - the right choice for a normal race lap and its trailing slow-down.
    """
    if not runs:
        return []
    if target_ms and len(runs) > 1:
        return min(runs, key=lambda r: abs(_estimate_lap_ms(r) - target_ms))
    return _longest_run(runs)


def _lap_start_fuel(samples: list[Sample]) -> float | None:
    """Fuel in the tank at the start of a timed lap, in kg.
    
    ``samples`` is already trimmed to the timed lap's 0..track-length pass (the
    formation/out-lap prefix and in-lap/slow-down have been dropped by _select_timed_run /
    _split_runs), so its first frame sits at the racing s/f line - i.e. fuel at the lap start,
    which falls lap by lap. Returns the first finite Car Status fuel reading, or None when no 
    frame of the run carried one (older streams, or Car Status not yet seen).
    """
    for sample in samples:
        if not math.isnan(sample.fuel):
            return sample.fuel
    return None


def _trim_to_timed_lap(samples: list[Sample]) -> list[Sample]:
    """Trim a raw lap buffer to the timed lap's 0..track-length pass, without a target time.

    Splits the buffer at s/f line resets, drops each run's pre-line (negative) samples, and keeps
    the longest run - discarding a leading formation/out lap and a trailing post-finish slow-down.
    A clean lap is a single run and is returned unchanged; a pure out-lap (all pre-line) trims to
    nothing. The assembler prefers the time-aware ``_select_timed_run`` when a lap time is known
    (see _build_laps, needed to disambiguate qualifying in/out/flying laps); this is the timing-free
    fallback and is what the unit tests pin.
    """
    return _longest_run(_split_runs(samples))


class _SessionBuilder:
    """Accumulates one session's packet into a single SessionResult."""

    def __init__(self) -> None:
        self._scaffold: SessionResult | None = None
        self._roster_by_index: dict[int, Participant] = {}  # merged across all Participants frames
        self._session_history = None            # the player's latest Session History packet
        self._session_history_by_index: dict[int, object] = {}  # car_idx -> last Session History (fallback classification)
        self._best_lap_num_by_index: dict[int, int] = {}  # car_idx -> lap the best lap was set on
        self._last_lap_data = None                # latest full Lap Data packet, all cars (fallback classification)
        self._final_classification = None       # the final classification packet
        self._last_car_status = None            # the player's latest Car Status entry
        self._last_car_telemetry = None         # the player's latest Car Telemetry entry
        self._last_motion = None                # the player's latest normalized MotionSample

        self._last_car_damage = None            # the player's latest Car Damage entry (tyre wear)
        self._last_setup = None                 # the player's latest normalized Setup (for change-diff)
        self._setup_history: list[SetupSnapshot] = []  # ordered garage-setup snapshots
        self._tyre_context: dict[int, LapTyreContext] = {}  # lap_number -> tyre state at the line
        self._damage: dict[int, CarDamage] = {}  # lap_number -> non-tyre damage at the line

        # lap_number -> candidate runs from that lap's buffer; the timed run is chosen at build
        # time (see _build_laps), once the Session History lap time is known.
        self._lap_runs: dict[int, list[list[Sample]]] = {}

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
            # Session History cycles through every car; keep each car's best-lap lap number
            # (last-write wins) so the classification can resolve the fastest-lap tyre stint.
            self._best_lap_num_by_index[packet.car_idx] = packet.best_lap_time_lap_num
            self._session_history_by_index[packet.car_idx] = packet     # full history, for fallback classification
            if packet.car_idx == packet.header.player_car_index:
                self._session_history = packet              # last-write wins -> end-of-session bulk
        elif pid == PacketId.FINAL_CLASSIFICATION:
            self._final_classification = packet
        elif pid == PacketId.CAR_STATUS:
            idx = packet.header.player_car_index
            if idx >= len(packet.car_status_data):  # player not in the array this frame (lobby/spectator)
                return
            self._last_car_status = packet.car_status_data[idx]
        elif pid == PacketId.MOTION:
            idx = packet.header.player_car_index
            if idx >= len(packet.car_motion_data):  # player not in the array this frame
                return
            self._last_motion = motion_sample(
                packet.car_motion_data[idx], packet.header.packet_format)
        elif pid == PacketId.CAR_DAMAGE:
            idx = packet.header.player_car_index
            if idx >= len(packet.car_damage_data):  # player not in the array this frame (lobby/spectator)
                return
            self._last_car_damage = packet.car_damage_data[idx]
        elif pid == PacketId.CAR_SETUPS:
            idx = packet.header.player_car_index
            if idx >= len(packet.car_setups):   # player not in the array this frame (lobby/spectator)
                return
            self._record_setup(normalize_setup(packet.car_setups[idx]))
        elif pid == PacketId.LAP_DATA:
            self._last_lap_data = packet            # full grid; for fallback classification if not Final Classification arrives
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
            entry = packet.car_telemetry_data[idx]
            self._last_car_telemetry = entry        # carry forward for the lap-boundary temp snapshot
            self._pending_car_telemetry = entry
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
            self._snapshot_lap_state(self._cur_lap)
            self._cur_lap = lap_num
            self._buffer = []
        self._buffer.append(telemetry_sample(lap_data, car_telemetry, self._last_car_status, self._last_motion))

    def _store_trace(self, lap_number: int) -> None:
        """Stash the current buffer's candidate runs for a lap_number.

        The buffer is split into runs at each s/f line reset (pre-line samples dropped); which run
        is the timed lap is decided at build time by ``_build_laps``/``_select_timed_run``, once the
        Session History lap time - which alone tells qualifying's in/out/flying laps apart - is
        known. (At stream time here that time is still 0.)
        """
        runs = _split_runs(self._buffer)
        if runs:
            self._lap_runs[lap_number] = runs

    def _record_setup(self, setup) -> None:
        """Append a setup snapshot when the setup changes, deduping consecutive identical ones.
        
        `from_lap` is the lap the change was seen on (0 before the first lap starts), so the lap
        detail resolves a lap's setup as the latest snapshot with from lap <= lap_number. First
        implementation stays dumb (record-on-change); debouncing garage-visit flicker can be added
        later without touching the model or storage.
        """
        if setup == self._last_setup:
            return
        self._last_setup = setup
        self._setup_history.append(SetupSnapshot(from_lap=self._cur_lap or 0, setup=setup))

    def _snapshot_lap_state(self, lap_number: int) -> None:
        """Snapshot the player's tyre state and car damage at a lap boundary (as the car crosses
        the line). Tyre context needs a Car Status frame; damage needs a Car Damage frame; the
        surface/carcass/brake/engine temperatures come from the latest Car Telemetry frame
        (carry forward). Each snapshot is recorded only once its required source has been seen.
        """
        if self._last_car_status is not None:
            self._tyre_context[lap_number] = normalize_tyre_context(
                self._last_car_status, self._last_car_damage, self._last_car_telemetry
            )
        if self._last_car_damage is not None:
            self._damage[lap_number] = normalize_car_damage(
                self._last_car_damage, self._last_car_telemetry
            )

    def _build_laps(self) -> tuple[Lap, ...]:
        """Join captured traces with Session History timing, by lap number."""
        sh = self._session_history
        laps = []
        for lap_number in sorted(self._lap_runs):
            if sh is None or not (1 <= lap_number <= sh.num_laps):
                continue
            entry = sh.lap_history_data[lap_number - 1]
            total = entry.lap_time_in_ms
            if total <= 0:          # lap not completed (in-lap / current partial)
                continue
            # now that the lap time is known, pick the run it belongs to (qualifying can leave an
            # in-lap, out-lap and flying lap under one lap number) and build only that trace. A run
            # still starting well past the line (joined mid-lap) or none at all is skipped.
            samples = _select_timed_run(self._lap_runs[lap_number], total)
            if not samples or samples[0].distance > _MAX_LAP_START_DISTANCE_M:
                continue
            laps.append(
                Lap(
                    lap_number=lap_number,
                    lap_time_ms=total,
                    sector1_ms=_sector_ms(entry.sector1_time_minutes_part, entry.sector1_time_ms_part) or None,
                    sector2_ms=_sector_ms(entry.sector2_time_minutes_part, entry.sector2_time_ms_part) or None,
                    sector3_ms=_sector_ms(entry.sector3_time_minutes_part, entry.sector3_time_ms_part) or None,
                    is_valid=bool(entry.lap_valid_bit_flags & _LAP_VALID_BIT),
                    trace=build_trace(samples),
                    tyre_context=self._tyre_context.get(lap_number),
                    damage=self._damage.get(lap_number),
                    fuel_in_tank=_lap_start_fuel(samples)
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
            self._snapshot_lap_state(self._cur_lap)

        roster = tuple(self._roster_by_index[i] for i in sorted(self._roster_by_index))

        classification = None
        if self._final_classification is not None:
            classification = normalize_classification(
                self._final_classification, roster, self._best_lap_num_by_index
            )
        else:
            # No Final Classification packet arrived (recording stopped early, or that single 
            # datagram was lost). Reconstruct a best-effort result from the last Lap Data fram + 
            # Session History so the session still has a table.
            classification = reconstruct_classification(
                roster, self._last_lap_data, self._session_history_by_index,
                self._best_lap_num_by_index
            )

        return dataclasses.replace(
            self._scaffold,
            participants=roster,
            laps=self._build_laps(),
            classification=classification,
            setup_history=tuple(self._setup_history)
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