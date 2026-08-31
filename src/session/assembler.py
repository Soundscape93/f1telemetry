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
from collections import Counter
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
from ..protocol.enums import (
    DriverStatus,
    PacketId,
    PitStatus,
    SafetyCarStatus,
    Weather,
    safe_enum,
)

# A cleanly caputred lap begins near the start line. A lap whose sample is well past
# it was joined mid-way (started recording) or is an out-lap, so no clean trace is kept.
#
# The bound has to clear a standing start: the grid sits some way past the timing line, and how far
# is set by pole rather than by the back of the grid — the grid queues backwards from P1 towards the
# line, so lower slots sit nearer it, and where pole is already close they fall behind the line and
# start their lap 1 from a few metres. The deepest slot on the calendar is P1 at COTA, about 323 m;
# measured in these captures, Jeddah is 246.5 m and Shanghai 175.7 m. 200 dropped those opening laps
# silently. 350 clears COTA while still meaning "at the start" - about a tenth of a Monaco lap.
_MAX_LAP_START_DISTANCE_M = 350  # meters

_LAP_VALID_BIT = 0x08  # bit 3 of lap_valid_bit_flags = whole lap valid

# lapDistance (m_lapDistance) is NEGATIVE before the car crosses the start/finish line and only
# becomes 0..track-length on the lap proper. The formation lap (race lap 1) and out-laps share their
# current_lap_num with the timed lap that follows, so a lap's raw buffer can carry a pre-line segment
# (negative, or a whole formation/out lap) in front of the real 0..L pass. A backward jump larger
# than this marks such a boundary within one buffer (the s/f line reset).
_LAP_RESET_DROP_M = 300  # meters

# --- lap state (E17) -------------------------------------------------------------------------
# Measured across every capture in this database before these rules were written; the evidence is
# in TELEMETRY_NOTES -> "What driver_status actually reports".
#
_SAFETY_CAR_NONE = int(SafetyCarStatus.NONE)
_SAFETY_CAR_DEPLOYED = (int(SafetyCarStatus.FULL), int(SafetyCarStatus.VIRTUAL))

# --- weather (E14) ---------------------------------------------------------------------------
# The opening Session packets of a session report a condition the packet then corrects. Measured
# across all 33 captures: 8 of 73 sessions carry such a run, every one of them settled by
# session_time 2.0 s, and in 3 of the 8 the forecast array is still empty - the game is still
# setting the session up. Skipping that window is what stops a Melbourne Q1 that read CLEAR for
# 1.5 s and then rained for eighteen minutes from being called mixed.
#
# In SECONDS, not packets. The game fast-forwards the session clock while the player sits in the
# garage, so a *genuine* 38-second wet stretch can be four packets - the same length as the
# artifact, which makes a packet count useless as a dwell. The shortest real stretch measured is
# 26.4 s, so 3.0 clears both edges by an order of magnitude. See TELEMETRY_NOTES -> weather.
_WEATHER_SETTLE_S = 3.0  # seconds


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


def _longest_run_index(runs: list[list[Sample]]) -> int:
    """Index of the run covering the most distance; ties -> the later run or -1 when there are none.
    
    An *index* returned rather than the run itself because the caller needs to know what came before it in
    the buffer, and two runs of a lap can compare equal - ``list.index`` would find the wrong one.
    """
    best, best_span = -1, -1.0
    for index, run in enumerate(runs):
        span = run[-1].distance - run[0].distance
        if span >= best_span:
            best, best_span = index, span
    return best


def _longest_run(runs: list[list[Sample]]) -> list[Sample]:
    """The run covering the most distande; ties -> the later run (timed lap follows an out-lap)."""
    index = _longest_run_index(runs)
    return runs[index] if index >= 0 else []


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


def _select_timed_run_index(runs: list[list[Sample]], target_ms: int | None) -> int:
    """Index of the run that is the lap Session History timed at ``target_ms``, or -1 for none.

    With a known lap time and more than one full run (qualifying's in/out/flying laps share one
    current_lap_num), choose the run whose estimated duration is closest to it - the flying lap,
    not the slower in/out laps. Without a time, or with a single run, fall back to the longest run
    (the full 0..L pass) - the right choice for a normal race lap and its trailing slow-down.
    """
    if not runs:
        return -1
    if target_ms and len(runs) > 1:
        return min(range(len(runs)), key=lambda i: abs(_estimate_lap_ms(runs[i]) - target_ms))
    return _longest_run_index(runs)

def _select_timed_run(runs: list[list[Sample]], target_ms: int | None) -> list[Sample]:
    """The run that is the lap Session History timed at ``target_ms`` (see _select_timed_run_index)."""
    index = _select_timed_run_index(runs, target_ms)
    return runs[index] if index >= 0 else []


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


def _modal_driver_status(samples: list[Sample]) -> int:
    """The status the car held for most of the timed lap.
    
    Modal rather than first or last: a lap can begin with a stale frame ffrom the lap before it, and
    a race in-lap flips to IN-LAP for its final second. What the lap *was* is what it mostly read.
    """
    return Counter(sample.driver_status for sample in samples).most_common(1)[0][0]


def _peak_pit_status(samples: list[Sample]) -> int:
    """The furthest into the pits the car got on this lap: none -> pitting -> in the pit area.

    IN_PIT_AREA (2) is the useful one - it means the stationary stop itself happened on this lap,
    which is not always the lap the driver entered the pit lane on. Where the pit box sits before
    the timing line (Melbourne, Sakhir) the stop lands on the *in*-lap and that lap carries the
    +14 to +37 s; where it sits after (Suzuka, Shanghai) it lands on the out-lap.
    """
    return max((sample.pit_status for sample in samples), default=int(PitStatus.NONE))


def _is_out_lap(samples: list[Sample]) -> bool:
    """Whether this lap began in the pit lane: the lane timer was running as it started.

    One signal, and it is exact. Measured over all 470 emitted laps in this database, the timer
    flags 15 laps and every one of them also carries a pit stop - there is no real pit-lane exit
    it misses.

    ``driver_status == OUT_LAP`` is deliberately *not* consulted, though it looks like it should
    be. It flags those same 15 laps and two more: Shanghai sprint lap 4 and Shanghai race lap 13,
    each 94-95% OUT_LAP with the timer never active. Those two are red-flag restarts, and the game
    means something different by them - it does not time the lap that drives out of the pit lane to
    the grid (TELEMETRY_NOTES -> "A red flag skips a lap number"), so the status is left over from a
    lap that was never emitted, and the lap it lands on is a standing start from the grid box, not a
    lap begun in the pit lane. Calling it an out-lap put the wrong chip on it and drew it as a stint
    opener. ``lap_context`` reads the restart off the stored ``red_flagged`` flag instead; the raw
    status is still on the lap for anyone asking.
    """
    return bool(samples[0].pit_lane_timer_active)


def _is_in_lap(samples: list[Sample]) -> bool:
    """Whether this lap ended by entering the pit lane - read from the lane timer, never the status.

    ``driver_status == IN_LAP`` looks like the right field and is not: the game sets it when the
    *planned* in-lap comes up and leaves it set while the driver stays out. Melbourne race laps 19,
    20 and 21 all read IN_LAP and the stop is on 21; one Suzuka race reads IN_LAP for its last six
    laps and never pits again. The pit-lane timer running as the car crosses the line is the fact.
    """
    return bool(samples[-1].pit_lane_timer_active)


def _preceded_by_garage(before: list[Sample]) -> bool:
    """Whether the car sat in the garage between the previous emitted lap and this one.

    ``before`` is every frame of this lap number's buffer ahead of the run that turned out to be
    the timed lap. That is where a garage visit always is: ``current_lap_num`` only advances when
    the line is crossed at the end of a *timed* lap, so an in-lap, a garage stop and the out-lap
    that follows all share the lap number of the flying lap they lead into. Measured across every
    capture here - 484 emitted laps, 69 with a garage before them, **none** with one inside or
    after the timed run, and no garage stranded in a buffer that was never emitted.

    This is what the ``fuel_in_tank`` proxy was standing in for (DECISIONS -> UI). A race never
    reports it: the game says IN_PIT_AREA for a pit stop and keeps IN_GARAGE for the garage proper,
    so this is an *additional* run boundary beside wear/age/compound, never a replacement.
    """
    return any(sample.driver_status == DriverStatus.IN_GARAGE for sample in before)


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

        # race control, from the Session packet rather than the frame join (see _note_race_control):
        self._safety_car: dict[int, int] = {}       # lap_number -> SafetyCarStatus seen that lap
        self._red_flag_laps: set[int] = set()       # lap_numbers a red-flag period began on
        self._red_flag_periods: int | None = None   # last num_red_flag_periods, to see it rise

        # every distinct condition the Session packets reported, in first-seen order, raw ints
        # (see _note_weather). The scaffold's `weather` stays the end-of-session snapshot.
        self._weather_seen: list[int] = []

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
            self._note_race_control(packet)
            self._note_weather(packet)
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


    def _note_race_control(self, packet) -> None:
        """Attribute the Session packet's safety-car and red-flag state to the lap in progress.

        Neither rides on Lap Data, so neither reaches the frame join - they are session-wide facts
        on their own packet, and the lap they belong to is simply the one the join is filling.
        That attribution is exact for a race, which drives one lap-distance pass per lap number;
        practice and qualifying never see either state at all (measured across every capture here,
        where the only three safety cars and two red flags are all in races).

        **Safety car**: the state the lap is remembered by is the first non-NONE one it saw, except
        that a real deployment always wins - so a race lap 1 records the formation lap, and a lap
        the car spends going green under a returning safety car still records FULL rather than the
        NONE that followed it.

        **Red flag**: a *rise* in ``num_red_flag_periods``. Only rises, because the counter is not
        monotonic - the Shanghai sprint's went 0 -> 1 on lap 2 and back to 0 on lap 10 - so reading
        the value itself would flag every lap of the restart and then stop. Thin evidence: this
        database holds two red flags, and both land on the right lap.
        """
        lap_number = self._cur_lap
        if lap_number is None:
            return                  # pre-session frames: no lap to attribute anything to
        status = packet.safety_car_status
        stored = self._safety_car.get(lap_number)
        if (stored is None 
            or (stored == _SAFETY_CAR_NONE and status != _SAFETY_CAR_NONE)
            or status in _SAFETY_CAR_DEPLOYED):
            self._safety_car[lap_number] = status
        periods = packet.num_red_flag_periods
        if self._red_flag_periods is not None and periods > self._red_flag_periods:
            self._red_flag_laps.add(lap_number)
        self._red_flag_periods = periods

    def _note_weather(self, packet) -> None:
        """Accumulate the distinct conditions this session reported, in first-seen order.
        
        The Session packet carries one condition and the scaffold keeps the last, so a session
        that started dry and finished wet stores as wet with nothing saying it changed. This is
        the other half of that fact - the set is actually ran through it, which
        ``SessionResult.is_mixed_weather`` reads. Ground truth, unlike ``weatherForecastSamples``
        (weekend.wide, rolls past samples off, and only a forecast - see PRIORITIES -> E14).

        The opening ``_WEATHER_SETTLE_S`` seconds are skipped; the constant carries the measured
        reason and why the window is session time rather than a packet count. The filter belongs
        here and not on read: it is temporal, and the times are gone once this is a set.
        """
        if packet.header.session_time < _WEATHER_SETTLE_S:
            return
        weather = int(packet.weather)
        if weather not in self._weather_seen:
            self._weather_seen.append(weather)

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
            runs = self._lap_runs[lap_number]
            index = _select_timed_run_index(runs, total)
            samples = runs[index] if index >= 0 else []
            if not samples or samples[0].distance > _MAX_LAP_START_DISTANCE_M:
                continue
            # Everything in this lap number's buffer ahead of the timed run: the in-lap the game
            # never timed, the garage stop and the out-lap, all of which share this lap's number.
            before = [sample for run in runs[:index] for sample in run]
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
                    fuel_in_tank=_lap_start_fuel(samples),
                    driver_status=_modal_driver_status(samples),
                    pit_status=_peak_pit_status(samples),
                    preceded_by_garage=_preceded_by_garage(before),
                    is_out_lap=_is_out_lap(samples),
                    is_in_lap=_is_in_lap(samples),
                    safety_car=self._safety_car.get(lap_number, _SAFETY_CAR_NONE),
                    red_flagged=lap_number in self._red_flag_laps
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
            setup_history=tuple(self._setup_history),
            weather_seen=tuple(safe_enum(Weather, w) for w in self._weather_seen)
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