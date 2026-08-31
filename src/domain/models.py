"""Version-agnostic domain models for F1 telemetry data.

The parser hands up raw, format-specific wire structs; the normalizer turns them into these objects,
at which point the 2025/2026 distinction is gone. Nothing in this layer/module knows or cares
which game version produced the data.

A capture normalizes into one ``SessionResult``: the session's metadata and persistent hierarchy keys,
the participants roster, the player's completed laps (each with its dense distance-indexed trace),
the player's setup and the final classification. The Season -> Weekend -> Session tree is not built here;
it is reconstructed downstream by grouping stored `SessionResult`s on their season/weekend keys (storage/UI layers).

Conventions:
    * Lap and sector times are milliseconds (int); total race time is in seconds (float).
    * Distance is meters; speed is km/h; ERS energy is joules.
    * Wheel-order tuples are RL, RR, FL, FR; matching the UDP spec.
    * Closed values sets use the shared enums; open ID sets (track, team, driver, nationality) are stored
      in raw ints and resolved via protocol.reference at display.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

import numpy as np

from ..protocol.enums import Formula, ResultReason, ResultStatus, SessionType, Weather


@dataclass
class LapTrace:
    """Dense per-lap telemetry, every channel indexed by lap distrance (meters).
    
    All channel arrays are parallel and the same length as `distance`, which is the
    canonical x-axis: laps overlay and diff on distance, never time. Channels are
    populated by the assembler joining Car Telemetry (+ Car Status for ERS) per frame;
    for the player's own car every channel is always available.
    """

    distance: np.ndarray            # meters around the lap (x-axis)
    speed: np.ndarray               # km/h
    throttle: np.ndarray            # 0.0..1.0
    brake: np.ndarray               # 0.0..1.0
    steer: np.ndarray               # -1.0..1.0
    gear: np.ndarray                # R = -1, N = 0, 1..8
    engine_rpm: np.ndarray      
    drs: np.ndarray                 # 0 / 1
    ers_store_energy: np.ndarray    # joules
    ers_deploy_mode: np.ndarray     # see enums.ERSDeployMode

    # optional motion channels, from the Motion packet. None on laps captured without Motion data;
    # present laps carry all four together. pos_x/pos_z are world coords (F1's gound plane is X/Z, Y is up)
    # for the track-map view; g_lat/g_long are g-force (2026 int16 / 1000 at ingest, so already in g here).
    pos_x: np.ndarray | None = None
    pos_z: np.ndarray | None = None
    g_lat: np.ndarray | None = None
    g_long: np.ndarray | None = None

    # required channel field names excluding the distance axis (storage columns / iteration)
    CHANNELS: ClassVar[tuple[str, ...]] = (
        'speed', 'throttle', 'brake', 'steer', 'gear',
        'engine_rpm', 'drs', 'ers_store_energy', 'ers_deploy_mode'
    )

    # additive motion channels; each is either None (absent) of the same length as 'distance'.
    OPTIONAL_CHANNELS: ClassVar[tuple[str, ...]] = ('pos_x', 'pos_z', 'g_lat', 'g_long')

    def __post_init__(self):
        """Validate that all channels are the same length as the distance axis."""
        n = len(self.distance)
        for name in self.CHANNELS:
            length = len(getattr(self, name))
            if length != n:
                raise ValueError(f"Channel '{name}' has length {length},expected {n} "
                                 f"to match the distance axis."
                                )
        for name in self.OPTIONAL_CHANNELS:
            values = getattr(self, name)
            if values is not None and len(values) != n:
                raise ValueError(f"Optional channel '{name}' has length {len(values)}, "
                                 f"expected {n} to match the distance axis.")
    
    @property
    def has_motion(self) -> bool:
        """True if the Motion channels (position + g-force) were captured for this lap."""
        return self.pos_x is not None
    
    def __len__(self):
        return len(self.distance)


@dataclass(frozen=True)
class LapTyreContext:
    """The player's tyre state caputred at the end of one lap (as the car crosses the line).
    
    Wear is cumulative over the stint (a percentage per wheel), so this is a boundary snapshot,
    not a per-frame trace channel. Compund and age come from Car Status; wear from Car Damage;
    the surface/carcass temperatures from Car Telemetry. Wheel order is RL, RR, FL, FR throughout,
    matching the UDP spec.
    """

    actual_compound: int                        # see enums.ActualTyreCompound
    visual_compound: int                        # see enums.VisualTyreCompound
    age_laps: int                               # number of laps on this tyre set
    wear: tuple[float, float, float, float]     # RL, RR, FL, FR (0.0..100.0 %)
    damage: tuple[int, int, int, int] = (0, 0, 0, 0)           # per wheel a damage %
    blisters: tuple[int, int, int, int] = (0, 0, 0, 0)          # per wheel a blister %
    surface_temp: tuple[int, int, int, int] = (0, 0, 0, 0)      # per wheel surface temp °C, RL,RR,FL,FR
    carcass_temp: tuple[int, int, int, int] = (0, 0, 0, 0)       # per wheel inner/carcass temp °C (primary readout)


@dataclass(frozen=True)
class CarDamage:
    """The player's non-tyre car damage, snapshotted at a lap boundary (from Car Damage).

    The tyre-specific fields of the Car Damage packet (wear / damage / blisters) live on
    LapTyreContext; this holds the rest - the car-body and engine story a damage table and the
    body graphic render. All values are percentages unless noted; brakes are RL, RR, FL, FR.
    """

    brakes: tuple[int, int, int, int]       # per-wheel brake damage %, RL, RR, FL, FR
    front_left_wing: int
    front_right_wing: int
    rear_wing: int
    floor: int
    diffuser: int
    sidepod: int
    gearbox: int
    engine: int
    engine_mguh_wear: int
    engine_es_wear: int
    engine_ce_wear: int
    engine_ice_wear: int
    engine_mguk_wear: int
    engine_tc_wear: int
    drs_fault: bool
    ers_fault: bool
    engine_blown: bool
    engine_seized: bool
    brake_temp: tuple[int, int, int, int] = (0, 0, 0, 0)  # per-wheel brake temp °C, RL, RR, FL, FR (Car Telemetry)
    engine_temp: int = 0                                   # engine temp °C (Car Telemetry)


@dataclass(frozen=True)
class Lap:
    """One completed lap: its timing and a reference to its dense trace."""

    lap_number: int
    lap_time_ms: int | None         # None if the lap was not completed (e.g. In Lap, Out Lap, DNF)
    sector1_ms: int | None
    sector2_ms: int | None
    sector3_ms: int | None
    is_valid: bool
    trace: LapTrace | None = None   # dense samples; may be persistent seperately from timing
    tyre_context: LapTyreContext | None = None  # tyre state at the line; None until captured/stored
    damage: CarDamage | None = None  # non-tyre damage at the line; None until captured/stored
    fuel_in_tank: float | None = None  # kg in the tank at lap start (Car Status); None until captured.

    # --- lap context: what Lap Data and the Sessioon packet said about this lap ---------------------
    # All None for laps ingested before PIPELINE_VERSION 4. ``has_lap_context`` is the one place
    # that decides "stored truth or inferred fallback"; nothing else should test a field for None.
    # Enums ride as raw ints and are read back through ``safe_enum`` (core invariant #9).
    driver_status: int | None = None            # DriverStatus held for most of the timed lap
    pit_status: int | None = None               # highest PitStatus seen; 2 = the pit stop is on this lap
    preceded_by_garage: bool | None = None      # the car was in the garage between the last lap and this
    is_out_lap: bool | None = None              # this lap began in the pit lane, or after a restart
    is_in_lap: bool | None = None               # this lap ended by entering the pit lane
    safety_car: int | None = None               # SafetyCarStatus in force during the lap
    red_flagged: bool | None = None             # a red-flag period began during this lap

    @property
    def is_complete(self) -> bool:
        """True if the lap was completed and has a valid time."""
        return self.lap_time_ms is not None

    @property
    def has_lap_context(self) -> bool:
        """Whether this lap carries the stored lap-state fields, or predates them.

        ``driver_status`` is the discriminator because every lap the assembler emits has a timed
        run and every frame of a timed run carries one - so it is set for all laps ingested at
        PIPELINE_VERSION 4 or later, and None for all laps ingested before. The booleans beside it
        cannot serve: ``False`` and "never captured" would read the same.
        """
        return self.driver_status is not None
    

@dataclass(frozen=True)
class Setup:
    """The player's car setup (one snapshot). Tyre pressures are RL, RR, FL, FR (PSI)"""

    front_wing: int
    rear_wing: int
    on_throttle: int                    # differential %, on throttle
    off_throttle: int                   # differential %, off throttle
    front_camber: float
    rear_camber: float
    front_toe: float
    rear_toe: float
    front_suspension: int
    rear_suspension: int
    front_anti_roll_bar: int
    rear_anti_roll_bar: int
    front_ride_height: int
    rear_ride_height: int
    brake_pressure: int                 # %
    brake_bias: int                     # %
    engine_braking: int                 # %
    tyre_pressures: tuple[float, float, float, float]  # RL, RR, FL, FR (PSI)
    ballast: int                        # kg
    fuel_load: float                    # kg


@dataclass(frozen=True)
class SetupSnapshot:
    """The player's car setup as it was for a given lap onward.
    
    A player can return to the garage mid-session and change setup, so a session carries an
    ordered history of these rather than one static Setup. `from_lap`is the lap the setup became
    active on; a lap's setup is the latest snapshot with `from_lap <= lap.lap_number`.
    (see SessionResult.setup_for_lap).
    """

    from_lap: int
    setup: Setup


@dataclass(frozen=True)
class TyreStint:
    """One tyre stint within a session (from the classification)."""

    actual_compound: int            # see enums.ActualTyreCompound
    visual_compound: int            # see enums.VisualTyreCompound
    end_lap: int                    # lap the stint ended on


@dataclass(frozen=True)
class Participant:
    """One car/driver in the session, keyed by the session-scoped vehicle index."""

    vehicle_index: int
    driver_name: str                # AI driver name, or online ID from humans
    team_id: int                     # see reference.team_name
    driver_id: int                   # see reference.driver_name (AI); 255 if network human
    race_number: int
    nationality_id: int               # see reference.nationality_name
    is_ai: bool
    is_player: bool                 # True fo the capturing player's own car
    network_id: int


@dataclass(frozen=True)
class ClassificationEntry:
    """One car's final result.
    
    `driver_name` and `team_id`, `race_number`, and `nationality_id` are denormalized from the
    participant roster so a results card renders self-contained without a join and league
    standings can key on the (stable per human) race number.

    ``is_ai`` is denormalized for the same reason and keeps identity honest: race numbers are only
    unique *within* a human field, so an AI driver and a league member can legitimately share one.
    Standings must never merge across that line. Defaults False for rows stored before it was captured.
    See `domain.roster.looks_like_ai` for the name based fallback that covers those until a re-ingest.
    """

    vehicle_index: int
    position: int
    driver_name: str
    team_id: int
    race_number: int
    nationality_id: int             # see reference.nationality_name (for the results-screen flag)
    is_player: bool
    grid_position: int
    points: int
    num_laps: int
    num_pit_stops: int
    best_lap_time_ms: int
    best_lap_num: int               # lap the best lap was set on; picks the fastest-lap tyre stint
    total_race_time_s: float
    penalties_time_s: int
    num_penalties: int
    result_status: ResultStatus
    result_reason: ResultReason
    tyre_stints: tuple[TyreStint, ...] = ()
    is_ai: bool = False                # additive + defaulted: pre re-ingest rows load as False


@dataclass(frozen=True)
class Classification:
    """The final classification - the authorative result, entries ordered by position.
    
    
    This is the deliverable usedd to render the entries onta a card for all sessions.
    """

    entries: tuple[ClassificationEntry, ...]
    # True when this classification was synthesized from telemetry because no Final Classification
    # packet arrived (see domain.normalizer.reconstruct_classification). Championship points are
    # not derivable and are left 0; the UI badges such tables and standings exclude them.
    is_reconstructed: bool = False

    @property
    def winner(self) -> ClassificationEntry | None:
        """The first-place entry, or None if the classification is empty."""
        return self.entries[0] if self.entries else None
    
    @property
    def player(self) -> ClassificationEntry | None:
        """The player's entry, or None if not found in the classification."""
        return next((e for e in self.entries if e.is_player), None)


# Dry vs wet, for ``SessionResult.is_mixed_weather``. A value outside the enum (safe_enum hands
# back the raw int) is in neither set, so it can never make a session read as mixed on its own.
_DRY_WEATHER = frozenset({Weather.CLEAR, Weather.LIGHT_CLOUD, Weather.OVERCAST})
_WET_WEATHER = frozenset({Weather.LIGHT_RAIN, Weather.HEAVY_RAIN, Weather.STORM})


@dataclass(frozen=True)
class SessionResult:
        """Everything one capture yields: one session's metadata, hierarchy keys,
        roster, the player's laps + traces, the player's setup, and the final
        classification.
        
        The Season -> Weekend -> Session tree is reconstructed downstream by grouping
        stored `SessionResult`s on `season_link_id`and `weekend_link_id`; it is not built here.
        """

        # identity & persistant hierarchy keys (from the Session packet / header)
        session_uid: int         # runtime-unique session id (header)     
        season_link_id: int        # groups sessions into a season (persists acrosss saves)
        weekend_link_id: int        # groups sessions into a session (persists acrosss saves)
        session_link_id: int        # groups sessions into a weekend

        # metadata
        game_format: int        # 2025 / 2026 - provenance only, never branched on
        track_id: int           # see reference.track_name
        session_type: SessionType
        formula: Formula
        weather: Weather
        total_laps: int
        game_mode: int          # raw mode id; see reference.game_mode_name (used to bucket sessions into mode-based windows)
        player_vehicle_index: int   # which car is in the roster is the player's

        # AI difficulty rating (0..110) from the Session packet; 0 means "not captured" - either stored before PIPELINE_VERSION 3 or a session with no AI.
        ai_difficulty: int = 0

        # The ordered session types that make up this weekend (from the Session packet's
        # weekend_structure array, truncated to num_sessions_in_weekend). Empty for rows saved
        # before it was captured. Both the Sprint Race and the Grand Prix report session_type
        # RACE (15), so this is what tells them apart - see domain/season.py:weekend_slots.
        weekend_structure: tuple[int, ...] = ()

        # Every distinct condition the session's Session packets reported, in first-seen order
        # (PIPELINE_VERSION 4). `weather` above stays the end-of-session snapshot; this is an
        # *additional* fact, so a session that ran in one condition still says which. Empty means
        # "not captured" - a row ingested before this existed, or a capture holding only the
        # opening seconds of a session - and never "one condition".
        weather_seen: tuple[Weather, ...] = () 

        # Static track geometry (metres) from the Session packet, kept together for the map and (future)
        # corner metadata. None for rows saved before this was captured; the game always sends them otherwise.
        # Sector 1 is 0..sector2_start_m. The track map colours its outline by sector and th traces mark the
        # boundaries from these.
        track_length_m: float | None = None
        sector2_start_m: float | None = None
        sector3_start_m: float | None = None

        # content
        participants: tuple[Participant, ...] = ()
        laps: tuple[Lap, ...] = ()      # the player's completed laps (with traces)
        setup_history: tuple[SetupSnapshot, ...] = ()  # ordered garage-setup snapshots (mid session changes)
        classification: Classification | None = None
        recorded_at: datetime | None = None     # capture time, for chronological ordering


        @property
        def player_participant(self) -> Participant | None:
            """The player's participant object, or None if not found in the roster."""
            return next((p for p in self.participants if p.is_player), None)

        @property
        def is_mixed_weather(self) -> bool:
            """Whether the session ran both dry and wet.
            
            Derived, never stored: ``weather_seen`` is the raw fact and this is the reading of it,
            so a future weather timeline widens the same column rather than needing a new one.
            False for a row with no set - "not captured" is not evidence of a change in conditions.
            """
            seen = set(self.weather_seen)
            return bool(seen & _DRY_WEATHER) and bool(seen & _WET_WEATHER)

        def setup_for_lap(self, lap_number: int) -> Setup | None:
            """he setup active on a given lap; the latest snapshot taking effect on or before it.

            Returns None if no setup was captured, or if every snapshot starts after this lap.
            Several snapshots can share a from_lap (e.g. tuning in the garage before the first
            lap: the game emits the initial default then the chosen setup while still on lap 1).
            setup_history is in record order, so among those the last one is the setup actually
            driven - pick it, not the first (which `max` would return on a tie).
            """
            active = [snap for snap in self.setup_history if snap.from_lap <= lap_number]
            if not active:
                return None
            latest = max(snap.from_lap for snap in active)
            return next(snap.setup for snap in reversed(self.setup_history) if snap.from_lap == latest)
        