"""Normalizer - converts wire structs into version-agnostic domain objects.

Pure, stateless functions: One packet in, one domain fragment out. Here the 2025/2026 
distinction finally disappears - both formats' structs share field names, so a single
function reads either one without branching on format. Sequencing packets over time
into completed laps and a finished session is the asselbler's job, not the normalizer's.

Stages
    1. session scaffold + participants roster (normalize_session, normalize_participants)
    2. per-frame trace samples and trace building (Sample, telemetry_sample, build_trace)

Field-name contract: these functions read structs attributes by name. They must match the structs
definitions. Important names are:
    header:                 packet_format, session_uid, player_car_index
    session packet:         track_id, session_type, formula, weather, total_laps,
                            season_link_identifier, weekend_link_identifier, session_link_identifier
    participant packet:     num_active_cars, participants
    participant entry:      ai_controlled, driver_id, network_id, team_id, race_number, 
                            nationality, name
    lap-data entry:         lap_distance (read here; current_lap_enum / timing read by the assembler)
    car-telemetry entry:    speed, throttle, brake, steer, gear, engine_rpm, drs
    car-status entry:       ers_store_energy, ers_deploy_mode
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import numpy as np

from ..protocol.enums import (
    Formula,
    ResultReason,
    ResultStatus,
    SessionType,
    Weather,
    safe_enum,
)
from ..protocol.reference import DRIVER_NAMES
from .models import (
    CarDamage,
    Classification,
    ClassificationEntry,
    LapTyreContext,
    LapTrace,
    Participant,
    Setup,
    SessionResult,
    TyreStint,
)

if TYPE_CHECKING:
    from ..protocol.v2025 import PacketParticipantsData, PacketSessionData

def _decode_name(value: bytes) -> str:
    """Decode a UTF-8, null-terminated name from a fixed-width char buffer."""
    return bytes(value).split(b"\x00", 1)[0].decode("utf-8", errors="replace")


def normalize_participants(packet: PacketParticipantsData) -> tuple[Participant, ...]:
    """The participant roster, trimmer to the active cars and marking the player's car.
    
    The driver name comes from the packet's own name field (the game fills it with the AI
    driver name, or the online/LAN id for humans) - not from a reference lookup.
    """
    player_idx = packet.header.player_car_index
    roster = []
    for i in range(packet.num_active_cars):         # count-trim: ignore unused slots
        player = packet.participants[i]
        roster.append(
            Participant(
                vehicle_index=i,
                driver_name=_decode_name(player.name),
                team_id=player.team_id,
                driver_id=player.driver_id,
                race_number=player.race_number,
                nationality_id=player.nationality,
                is_ai=player.ai_controlled,
                is_player=(i == player_idx),
                network_id=player.network_id,
            )
        )
    return tuple(roster)


def merge_participant(existing: "Participant | None", incoming: Participant) -> Participant:
    """Merge two views of the same car seen in diffrent Participants frames (union acreoss frames).
    Keeps the more complete identity - a real name and a nonzero race number - with later
    frames winning ties so a car dropped from a late (e.g. post-race results/podium)
    frame is still recovered from an earlier full-grid frame."""
    if existing is None:
        return incoming
    
    def _score(participant: Participant) -> int:
        return (1 if participant.driver_name.strip() else 0) + (
            1 if participant.race_number else 0)
    
    return incoming if _score(incoming) >= _score(existing) else existing


def normalize_setup(setup) -> Setup:
    """Convert the player's Car Setups entry into a domain Setup.
    
    `setup` is the player's CarSetupData entry (``packet.car_setups[player_car_idx]``). Ride height
    comes from the struct's ``*_suspension_height`` fields; tyre pressures are read in wheel order
    RL, RR, FL, FR to math the Setup contract.
    """
    return Setup(
        front_wing=setup.front_wing,
        rear_wing=setup.rear_wing,
        on_throttle=setup.on_throttle,
        off_throttle=setup.off_throttle,
        front_camber=setup.front_camber,
        rear_camber=setup.rear_camber,
        front_toe=setup.front_toe,
        rear_toe=setup.rear_toe,
        front_suspension=setup.front_suspension,
        rear_suspension=setup.rear_suspension,
        front_anti_roll_bar=setup.front_anti_roll_bar,
        rear_anti_roll_bar=setup.rear_anti_roll_bar,
        front_ride_height=setup.front_suspension_height,
        rear_ride_height=setup.rear_suspension_height,
        brake_pressure=setup.brake_pressure,
        brake_bias=setup.brake_bias,
        engine_braking=setup.engine_braking,
        tyre_pressures = (
            setup.rear_left_tyre_pressure,
            setup.rear_right_tyre_pressure,
            setup.front_left_tyre_pressure,
            setup.front_right_tyre_pressure
        ),
        ballast=setup.ballast,
        fuel_load=setup.fuel_load
    )


def normalize_tyre_context(car_status, car_damage=None) -> LapTyreContext:
    """Snapshot the player's tyre state at a lap boundary.
    
    `car_status` is the player's CarStatusData entry (compound + age); `car_damage` is the
    player's CarDamageData entry (per-wheel wear %, damage %, blisters %). All wheel arrays are
    read in order RL, RR, FL, FR; when no Car Damage frame has arrived yet they fall back to zeros.
    """
    if car_damage is not None:
        wear = tuple(float(w) for w in car_damage.tyres_wear)
        damage = tuple(int(d) for d in car_damage.tyres_damage)
        blisters = tuple(int(b) for b in car_damage.tyre_blisters)
    else:
        wear, damage, blisters = (0.0, 0.0, 0.0, 0.0), (0, 0, 0, 0), (0, 0, 0, 0)
    return LapTyreContext(
        actual_compound=car_status.actual_tyre_compound,
        visual_compound=car_status.visual_tyre_compound,
        age_laps=car_status.tyres_age_laps,
        wear=wear,
        damage=damage,
        blisters=blisters,
    )


def normalize_car_damage(car_damage) -> CarDamage:
    """Convert the player's Car Damage entry into the non-tyre CarDamage snapshot.

    The tyre-specific fields (wear/damage/blisters) are handled by ``normalize_tyre_context``;
    this reads the car-body and engine fields. Brakes are read in wheel order RL, RR, FL, FR.
    """
    return CarDamage(
        brakes = tuple(int(b) for b in car_damage.brakes_damage),
        front_left_wing=car_damage.front_left_wing_damage,
        front_right_wing=car_damage.front_right_wing_damage,
        rear_wing=car_damage.rear_wing_damage,
        floor=car_damage.floor_damage,
        diffuser=car_damage.diffuser_damage,
        sidepod=car_damage.sidepod_damage,
        gearbox=car_damage.gearbox_damage,
        engine=car_damage.engine_damage,
        engine_mguh_wear=car_damage.engine_mguh_wear,
        engine_es_wear=car_damage.engine_es_wear,
        engine_ce_wear=car_damage.engine_ce_wear,
        engine_ice_wear=car_damage.engine_ice_wear,
        engine_mguk_wear=car_damage.engine_mguk_wear,
        engine_tc_wear=car_damage.engine_tc_wear,
        drs_fault=car_damage.drs_fault,
        ers_fault=car_damage.ers_fault,
        engine_blown=car_damage.engine_blown,
        engine_seized=car_damage.engine_seized,
    )


def normalize_session(packet: "PacketSessionData") -> SessionResult:
    """A sessjonResult scaffold: metadata and the persistent hierarchy keys.

    Content (participants, laps, setup, classification) is left empty here and filled in
    by the assembler as the rest of the session's packets arrive.
    """
    header = packet.header
    return SessionResult(
        session_uid=header.session_uid,
        season_link_id=packet.season_link_identifier,
        weekend_link_id=packet.weekend_link_identifier,
        session_link_id=packet.session_link_identifier,
        game_format=header.packet_format,
        track_id=packet.track_id,
        session_type=safe_enum(SessionType, packet.session_type),
        formula=safe_enum(Formula, packet.formula),
        weather=safe_enum(Weather, packet.weather),
        total_laps=packet.total_laps,
        game_mode=packet.game_mode,
        player_vehicle_index=header.player_car_index,
        weekend_structure=tuple(packet.weekend_structure[:packet.num_sessions_in_weekend]),
    )


class Sample(NamedTuple):
    """One frame's worth of trace channel values for the player's car."""

    distance: float
    speed: int
    throttle: float
    brake: float
    steer: float
    gear: int
    engine_rpm: int
    drs: int
    ers_store_energy: int
    ers_deploy_mode: int


def telemetry_sample(lap_data, car_telemetry, car_status=None) -> Sample:
    """Combine one frame's player rows into a single trace sample.
    
    `lap_data` / `car_telemetry` are the player's entries from the Lap Data and
    Car Telemetry packets. `car_status` is the player's Car Status entry:
    when omitted, the ERS channels are placeholdered with zeros and filled in
    once the Car Status join is added.
    """
    if car_status is not None:
        ers_store_energy = car_status.ers_store_energy
        ers_deploy_mode = car_status.ers_deploy_mode
    else:
        ers_store_energy = 0
        ers_deploy_mode = 0
    return Sample(
        distance=lap_data.lap_distance,
        speed=car_telemetry.speed,
        throttle=car_telemetry.throttle,
        brake=car_telemetry.brake,
        steer=car_telemetry.steer,
        gear=car_telemetry.gear,
        engine_rpm=car_telemetry.engine_rpm,
        drs=car_telemetry.drs,
        ers_store_energy=ers_store_energy,
        ers_deploy_mode=ers_deploy_mode,
    )


def build_trace(samples: list[Sample]) -> LapTrace:
    """Transpose a lap's buffered samples into the parallel numpy arrays of a LapTrace."""
    return LapTrace(
        distance=np.array([s.distance for s in samples], dtype=float),
        speed=np.array([s.speed for s in samples], dtype=int),
        throttle=np.array([s.throttle for s in samples], dtype=float),
        brake=np.array([s.brake for s in samples], dtype=float),
        steer=np.array([s.steer for s in samples], dtype=float),
        gear=np.array([s.gear for s in samples], dtype=int),
        engine_rpm=np.array([s.engine_rpm for s in samples], dtype=int),
        drs=np.array([s.drs for s in samples], dtype=int),
        ers_store_energy=np.array([s.ers_store_energy for s in samples], dtype=int),
        ers_deploy_mode=np.array([s.ers_deploy_mode for s in samples], dtype=int)
    )


def _display_driver_name(participant: Participant) -> str:
    """The name a results card should show for a car: an AI driver's canonical full name
    (via ``driver_id``), or a human's captured online name left as-is.

    Baking this here means every downstream consumer - the classification table AND the
    driver standings, which both read ``ClassificationEntry.driver_name`` - gets the full
    name without a participant join (participants aren't persisted). Falls back to the
    captured name when the id isn't in the appendix.
    """
    if participant.is_ai:
        return DRIVER_NAMES.get(participant.driver_id, participant.driver_name)
    return participant.driver_name


def normalize_classification(
    packet,
    roster: tuple[Participant, ...],
    best_lap_num_by_index: dict[int, int] | None = None,
) -> Classification:
    """Build the final classification, ordered by finishing position.

    Driver name and team are denormalized from the roster (joined by vehicle index)
    so a results card render self-contained. AI drivers are resolved to their canonical
    full name (see ``_display_driver_name``). Tyre stints are trimmed per car by
    that car's num_tyre_stints. ``best_lap_num_by_index`` maps a car's vehicle index to the
    lap its best lap was set on (from Session History) so the fastest-lap tyre can be resolved
    at display; absent (e.g. no history captured) it defaults to 0.
    """
    player_idx = packet.header.player_car_index
    by_index = {p.vehicle_index: p for p in roster}
    best_lap_num_by_index = best_lap_num_by_index or {}
    
    entries = []
    for i in range(packet.num_cars):
        car = packet.final_classification_data[i]
        participant = by_index.get(i)
        stints = tuple(
            TyreStint(
                actual_compound=car.tyre_stints_actual[j],
                visual_compound=car.tyre_stints_visual[j],
                end_lap=car.tyre_stints_end_laps[j],
            )
            for j in range(car.num_tyre_stints)
        )
        entries.append(
            ClassificationEntry(
                vehicle_index=i,
                position=car.position,
                driver_name=_display_driver_name(participant) if participant else f"car_{i}",
                team_id=participant.team_id if participant else -1,
                race_number=participant.race_number if participant else 0,
                nationality_id=participant.nationality_id if participant else 0,
                is_player=(i == player_idx),
                grid_position=car.grid_position,
                points=car.points,
                num_laps=car.num_laps,
                num_pit_stops=car.num_pit_stops,
                best_lap_time_ms=car.best_lap_time_in_ms,
                best_lap_num=best_lap_num_by_index.get(i, 0),
                total_race_time_s=car.total_race_time,
                penalties_time_s=car.penalties_time,
                num_penalties=car.num_penalties,
                result_status=safe_enum(ResultStatus, car.result_status),
                result_reason=safe_enum(ResultReason, car.result_reason),
                tyre_stints=stints,
            )
        )

        # ordered by finishing position; unclassified (position=0/DNF) sink to the bottom
    entries.sort(key=lambda e: (e.position if e.position > 0 else 9999))
    return Classification(entries=tuple(entries))