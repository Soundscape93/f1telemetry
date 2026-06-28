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

    # channel field names excluding the distance axis (for storage columns / iteration)
    CHANNELS: ClassVar[tuple[str, ...]] = (
        'speed', 'throttle', 'brake', 'steer', 'gear',
        'engine_rpm', 'drs', 'ers_store_energy', 'ers_deploy_mode'
    )

    def __post_init__(self):
        """Validate that all channels are the same length as the distance axis."""
        n = len(self.distance)
        for name in self.CHANNELS:
            length = len(getattr(self, name))
            if length != n:
                raise ValueError(f"Channel '{name}' has length {length},expected {n} "
                                 f"to match the distance axis."
                                )
            
    def __len__(self):
        return len(self.distance)
    

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
    
    `driver_name` and `team_id` are denormalized from the participant roster 
    so a results card renders self-contained without a join.
    """

    vehicle_index: int
    position: int
    driver_name: str
    team_id: int
    is_player: bool
    grid_position: int
    points: int
    num_laps: int
    num_pit_stops: int
    best_lap_time_ms: int
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
        player_vehicle_index: int   # which car is in the roster is the player's
        

        # content
        participants: tuple[Participant, ...] = ()
        laps: tuple[Lap, ...] = ()      # the player's completed laps (with traces)
        setup: Setup | None = None
        classification: Classification | None = None
        recorded_at: datetime | None = None     # capture time, for chronological ordering


        @property
        def player_participant(self) -> Participant | None:
            """The player's participant object, or None if not found in the roster."""
            return next((p for p in self.participants if p.is_player), None)