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
    not a per-frame trace channel. Compund and age come from Car Status; wear from Car Damage.
    Wheel order is RL, RR, FL, FR throughout, matching the UDP spec.
    """

    actual_compound: int                        # see enums.ActualTyreCompound
    visual_compound: int                        # see enums.VisualTyreCompound
    age_laps: int                               # number of laps on this tyre set
    wear: tuple[float, float, float, float]     # RL, RR, FL, FR (0.0..100.0 %)
    damage: tuple[int, int, int, int] = (0, 0, 0, 0)           # per wheel a damage %
    blisters: tuple[int, int, int, int] = (0, 0, 0, 0)          # per wheel a blister %


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

    @property
    def is_complete(self) -> bool:
        """True if the lap was completed and has a valid time."""
        return self.lap_time_ms is not None
    

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


@dataclass(frozen=True)
class Classification:
    """The final classification - the authorative result, entries ordered by position.
    
    
    This is the deliverable usedd to render the entries onta a card for all sessions.
    """

    entries: tuple[ClassificationEntry, ...]

    @property
    def winner(self) -> ClassificationEntry | None:
        """The first-place entry, or None if the classification is empty."""
        return self.entries[0] if self.entries else None
    
    @property
    def player(self) -> ClassificationEntry | None:
        """The player's entry, or None if not found in the classification."""
        return next((e for e in self.entries if e.is_player), None)
    

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

        # The ordered session types that make up this weekend (from the Session packet's
        # weekend_structure array, truncated to num_sessions_in_weekend). Empty for rows saved
        # before it was captured. Both the Sprint Race and the Grand Prix report session_type
        # RACE (15), so this is what tells them apart - see domain/season.py:weekend_slots.
        weekend_structure: tuple[int, ...] = ()

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
        

        def setup_for_lap(self, lap_number: int) -> Setup | None:
            """The setup active on a given lap; the latest snapshot taking effect on or before it.
            
            Returns None if no setupr was captured, or if every snapshot starts after this lap.
            """
            active = [snap for snap in self.setup_history if snap.from_lap <= lap_number]
            return max(active, key=lambda snap: snap.from_lap).setup if active else None
        