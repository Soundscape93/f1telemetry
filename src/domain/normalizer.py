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
    car-telemetry entry:    speed, throttle, brake, steer, gear, engine_rpm, drs;
                            tyres_surface_temperature, tyres_inner_temperature,
                            brakes_temperature, engine_temperature (lap-boundary temps)
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


def normalize_tyre_context(car_status, car_damage=None, car_telemetry=None) -> LapTyreContext:
    """Snapshot the player's tyre state at a lap boundary.
    
    `car_status` is the player's CarStatusData entry (compound + age); `car_damage` is the
    player's CarDamageData entry (per-wheel wear %, damage %, blisters %); `car_telemetry` is the
    player's CarTelemetryData entry (per-wheel surface temp °C + inner/carcass temp °C). All wheel
    arrays are read in order RL, RR, FL, FR; a source not yet seen falls back to zeros.
    """
    if car_damage is not None:
        wear = tuple(float(w) for w in car_damage.tyres_wear)
        damage = tuple(int(d) for d in car_damage.tyres_damage)
        blisters = tuple(int(b) for b in car_damage.tyre_blisters)
    else:
        wear, damage, blisters = (0.0, 0.0, 0.0, 0.0), (0, 0, 0, 0), (0, 0, 0, 0)
    if car_telemetry is not None:
        surface_temp = tuple(int(t) for t in car_telemetry.tyres_surface_temperature)
        carcass_temp = tuple(int(t) for t in car_telemetry.tyres_inner_temperature)
    else:
        surface_temp, carcass_temp = (0, 0, 0, 0), (0, 0, 0, 0)
    return LapTyreContext(
        actual_compound=car_status.actual_tyre_compound,
        visual_compound=car_status.visual_tyre_compound,
        age_laps=car_status.tyres_age_laps,
        wear=wear,
        damage=damage,
        blisters=blisters,
        surface_temp=surface_temp,
        carcass_temp=carcass_temp
    )


def normalize_car_damage(car_damage, car_telemetry=None) -> CarDamage:
    """Convert the player's Car Damage entry into the non-tyre CarDamage snapshot.

    The tyre-specific fields (wear/damage/blisters) are handled by ``normalize_tyre_context``;
    this reads the car-body and engine fields. Brakes are read in wheel order RL, RR, FL, FR.
    `car_telemetry` (the player's CarTelemetryData entry) supplies the per-wheel brake and engine
    temperatures (°C); when absent they fall back to zeros.
    """
    if car_telemetry is not None:
        brake_temp = tuple(int(t) for t in car_telemetry.brakes_temperature)
        engine_temp = car_telemetry.engine_temperature
    else:
        brake_temp, engine_temp = (0, 0, 0, 0), 0
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
        brake_temp=brake_temp,
        engine_temp=engine_temp
    )


class MotionSample(NamedTuple):
    """The player's motion channels for one frame, already unit-normalized."""

    pos_x: float
    pos_z: float
    g_lat: float
    g_long: float


def motion_sample(entry, packet_format: int) -> MotionSample:
    """Read the player's CarMotionData entry into normalized position + g-force.
    
    World position is a float in both formats. G-force is the one channel that diverges:
    2026 quantisises it to int16 (/1000 to get g); 2025 is already float g. We branch on 
    ``packet_format`` here - the single place this channel's format diffrence is handled.
    """
    scale = 1000.0 if packet_format == 2026 else 1.0
    return MotionSample(
        pos_x=entry.world_position_x,
        pos_z=entry.world_position_z,
        g_lat=entry.g_force_lateral / scale,
        g_long=entry.g_force_longitudinal / scale,
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
        track_length_m=packet.track_length,
        sector2_start_m=packet.sector_2_lap_distance_start,
        sector3_start_m=packet.sector_3_lap_distance_start
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
    pos_x: float = float('nan')     # word coords / g-force filled when a Motion frame is present
    pos_z: float = float('nan')
    g_lat: float = float('nan')
    g_long: float = float('nan')
    fuel: float = float('nan')      # Car Status fuel_in_tank (kg); a lap-start scaler, NOT a trace channel


def telemetry_sample(lap_data, car_telemetry, car_status=None, motion=None) -> Sample:
    """Combine one frame's player rows into a single trace sample.
    
    `lap_data` / `car_telemetry` are the player's entries from the Lap Data and
    Car Telemetry packets. `car_status` is the player's Car Status entry (ERS + fuel_in_tank);
    zeros when omitted). `motion` is the normalized ``MotionSample`` for the frame -
    position + g-force - or None (older streams / no Motion), in which case those channels are
    NaN placeholders.
    """
    if car_status is not None:
        ers_store_energy = car_status.ers_store_energy
        ers_deploy_mode = car_status.ers_deploy_mode
        fuel = car_status.fuel_in_tank
    else:
        ers_store_energy = 0
        ers_deploy_mode = 0
        fuel = float('nan')
    if motion is not None:
        pos_x, pos_z, g_lat, g_long = motion
    else:
        pos_x = pos_z = g_lat = g_long = float('nan')
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
        pos_x=pos_x,
        pos_z=pos_z,
        g_lat=g_lat,
        g_long=g_long,
        fuel=fuel
    )


def build_trace(samples: list[Sample]) -> LapTrace:
    """Transpose a lap's buffered samples into the parallel numpy arrays of a LapTrace.
    
    The four motion channels are collapsed to None when no frame carried Motion (all-NaN), so
    stream without the Motion packet stores a plain nine-channel trace.
    """
    pos_x = np.array([s.pos_x for s in samples], dtype=float)
    has_motion = pos_x.size > 0 and not np.isnan(pos_x).all()
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
        ers_deploy_mode=np.array([s.ers_deploy_mode for s in samples], dtype=int),
        pos_x=pos_x if has_motion else None,
        pos_z=np.array([s.pos_z for s in samples], dtype=float) if has_motion else None,
        g_lat=np.array([s.g_lat for s in samples], dtype=float) if has_motion else None,
        g_long=np.array([s.g_long for s in samples], dtype=float) if has_motion else None,
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


def reconstruct_classification(
        roster: tuple[Participant, ...], lap_data_packet,
        session_history_by_index: dict[int, object],
        best_lap_num_by_index: dict[int, int] | None = None) -> Classification | None:
    """Best-effort classification for a session that never delivered a Final Classification packet.
    
    The game broadcasts the Final Classification packet once, at the session-end moment; if the
    recording is stopped a beat too early or that single datagram is lost, it is absent and
    ``normalize_classification`` has nothing to build from. This reconstructs each car's row from
    the last Lap Data frame (finishing/running position, grid, pit stops, laps, result status) and
    its Session History (best lap time and tyre stints), joined to the roster the same way.

    Total race time is recovered as the sum of the car's Session History lap times (the game
    defines the Final Classification total as race time *without penalties*, i.e. exactly that
    sum) and accumulated time penalties from the last Lap Data frame. Championship points are the
    one Final-Classification-only field - not present in any telemetry packet - so they are left 0
    (the UI shows an estimate; standings exclude reconstructed sessions). Returns None when there
    is no Lap Data to order by (nothing to reconstruct).
    """
    if lap_data_packet is None:
        return None
    
    player_idx = lap_data_packet.header.player_car_index
    by_index = {p.vehicle_index: p for p in roster}
    best_lap_num_by_index = best_lap_num_by_index or {}
    lap_rows = lap_data_packet.lap_data

    entries = []
    for i in sorted(by_index):
        if i >= len(lap_rows):
            continue
        lap = lap_rows[i]
        participant = by_index.get(i)

        best_ms = 0
        total_race_ms = 0
        stints: tuple[TyreStint, ...] = ()
        sh = session_history_by_index.get(i)
        if sh is not None:
            num_laps = min(sh.num_laps, len(sh.lap_history_data))
            lap_times = [sh.lap_history_data[j].lap_time_in_ms for j in range(num_laps)]
            completed = sum(1 for t in lap_times if t > 0)
            total_race_ms = sum(t for t in lap_times if t > 0)   # race time w/o penalties = sum of laps
            bnum = sh.best_lap_time_lap_num
            if 0 < bnum <= num_laps:
                best_ms = sh.lap_history_data[bnum - 1].lap_time_in_ms
            stints = tuple(
                TyreStint(
                    actual_compound=t.tyre_actual_compound,
                    visual_compound=t.tyre_visual_compound,
                    end_lap=t.end_lap,
                )
                for t in sh.tyre_stints_history_data[:sh.num_tyre_stints]
            )
        else:
            completed = max(0, lap.current_lap_num -1)
        
        entries.append(
            ClassificationEntry(
                vehicle_index=i,
                position=lap.car_position,
                driver_name=_display_driver_name(participant) if participant else f"car_{i}",
                team_id=participant.team_id if participant else -1,
                race_number=participant.race_number if participant else 0,
                nationality_id=participant.nationality_id if participant else 0,
                is_player=(i == player_idx),
                grid_position=lap.grid_position,
                points=0,
                num_laps=completed,
                num_pit_stops=lap.num_pit_stops,
                best_lap_time_ms=best_ms,
                best_lap_num=best_lap_num_by_index.get(i, 0),
                total_race_time_s=total_race_ms / 1000.0,
                penalties_time_s=lap.penalties,         # LapData.penalties = accumulated time penalties (s)
                num_penalties=0,
                result_status=safe_enum(ResultStatus, lap.result_status),
                result_reason=safe_enum(ResultReason, 0),
                tyre_stints=stints,
            )
        )
    
    if not entries:
        return None
    
    # same ordering as the real classifiction: by finishing position, unclassified (0) to the bottom
    entries.sort(key=lambda e: (e.position if e.position > 0 else 9999))
    return Classification(entries=tuple(entries), is_reconstructed=True)