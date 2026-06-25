"""Format-2026 wire structs.
 
Two tiers per packet: a per-car leaf record (e.g. CarTelemetryData = one car's
channels) and the packet that holds an array of them (PacketCarTelemetryData). Leaf
structs use the inherited __repr__; container packets override it so they don't print
all 24 entries.
 
This module covers the MVP trace backbone (Motion, Sessionn, Lap Data, Event, Participants, Car Setups, Car Telemetry, Car Status,
Final Classification, Lobby Info, Car Damage, Session History, Tyre Sets, Motion Ex, Time Trial, Lap Positions and the new Car Telemetry2).
"""
from __future__ import annotations

import ctypes as ct

from ..base import _Struct
from ..header import PacketHeader

_NUM_CARS = 24  # max number of cars in a session, per the UDP appendices (2025)

# --- Motion Packet-----------------------------------------------------------
class CarMotionData(_Struct):
    """One car's motion data (motion packet)."""

    _fields_ = [
        ("world_position_x", ct.c_float),       # World space X position
        ("world_position_y", ct.c_float),       # World space Y position
        ("world_position_z", ct.c_float),       # World space Z position
        ("world_velocity_x", ct.c_float),       # Velocity in world space X
        ("world_velocity_y", ct.c_float),       # Velocity in world space Y
        ("world_velocity_z", ct.c_float),       # Velocity in world space Z
        ("world_forward_dir_x", ct.c_int16),    # World space forward X direction (normalised)
        ("world_forward_dir_y", ct.c_int16),    # World space forward Y direction (normalised)
        ("world_forward_dir_z", ct.c_int16),    # World space forward Z direction (normalised)
        ("world_right_dir_x", ct.c_int16),      # World space right X direction (normalised)
        ("world_right_dir_y", ct.c_int16),      # World space right Y direction (normalised)
        ("world_right_dir_z", ct.c_int16),      # World space right Z direction (normalised)
        ("g_force_lateral", ct.c_int16),        # Lateral G-Force component (quantised)
        ("g_force_longitudinal", ct.c_int16),   # Longitudinal G-Force component (quantised)
        ("g_force_vertical", ct.c_int16),       # Vertical G-Force component (quantised)
        ("yaw", ct.c_float),                    # Yaw angle in radians
        ("pitch", ct.c_float),                  # Pitch angle in radians
        ("roll", ct.c_float),                   # Roll angle in radians
    ]


class PacketMotionData(_Struct):
    """motion_packet, which holds motion data for all cars in the session."""

    _fields_ = [
        ("header", PacketHeader),                        # Header
        ("car_motion_data", CarMotionData * _NUM_CARS),  # Motion data for all cars on track
    ]

    def __repr__(self) -> str:
        return (f"{type(self).__name__}(format={self.header.packet_format}, "
                f"frame={self.header.frame_identifier}, cars={_NUM_CARS})")
# ------------------------------------------------------------------------------


# --- Session Packet -----------------------------------------------------------
class MarshalZone(_Struct):
    """One marshal zone (session packet)."""

    _fields_ = [
        ("zone_start", ct.c_float),  # Fraction (0..1) of way round the lap the marshal zone starts
        ("zone_flag", ct.c_int8),    # -1 = invalid/unknown, 0 = none, 1 = green, 2 = blue, 3 = yellow,
    ]


class ActiveAeroZone(_Struct):
    """One active aero zone (session packet)."""

    _fields_ = [
        ("zone_start", ct.c_float),  # Fraction (0..1) of way throughout the lap the Active Aero zone starts
        ("zone_end", ct.c_float),   # Fraction (0..1) of way throughout the lap the Active Aero zone ends 
    ]


class DRSZone(_Struct):
    """One DRS zone (session packet)."""

    _fields_ = [
        ("zone_start", ct.c_float),  # Fraction (0..1) of way throughout the lap the DRS zone starts
        ("zone_end", ct.c_float),   # Fraction (0..1) of way throughout the lap the DRS zone ends 
    ]


class WeatherForecastSample(_Struct):
    """One weather forecast sample (session packet)."""

    _fields_ = [
        ("session_type", ct.c_uint8),               # See enums.SessionType
        ("time_offset", ct.c_uint8),                # Time in minutes the forecast is for
        ("weather", ct.c_uint8),                    # See enums.Weather
        ("track_temperature", ct.c_int8),           # Track temp. in degrees celsius
        ("track_temperature_change", ct.c_int8),    # Track temp. change - 0 = up, 1 = down, 2 = no change
        ("air_temperature", ct.c_int8),             # Air temp. in degrees celsius
        ("air_temperature_change", ct.c_int8),      # Air temp. change - 0 = up, 1 = down, 2 = no change
        ("rain_percentage", ct.c_uint8),            # Rain percentage (0-100)
    ]


class PacketSessionData(_Struct):
    """session_packet, which holds static data about the session and track, and arrays of marshal zones and weather forecasts."""

    _fields_ = [
        ("header", PacketHeader),                            # Header
        ("weather", ct.c_uint8),                            # See enums.Weather
        ("track_temperature", ct.c_int8),                   # Track temp. in degrees celsius
        ("air_temperature", ct.c_int8),                     # Air temp. in degrees celsius
        ("total_laps", ct.c_uint8),                         # Total number of laps in this race
        ("track_length", ct.c_uint16),                     # Track length in metres
        ("session_type", ct.c_uint8),                     # See enums.SessionType
        ("track_id", ct.c_int8),                         # -1 unknown - see enums.Track
        ("formula", ct.c_uint8),                         # See enums.Formula
        ("session_time_left", ct.c_uint16),              # Time left in session in seconds
        ("session_duration", ct.c_uint16),               # Session duration in seconds
        ("pit_speed_limit", ct.c_uint8),                # Pit speed limit in kilometres per hour
        ("game_paused", ct.c_uint8),                     # whether the game is paused - 0 = unpaused, 1 = paused
        ("is_spectating", ct.c_uint8),                  # whether the player is spectating
        ("spectator_car_index", ct.c_uint8),           # index of the car being spectated
        ("sli_pro_native_support", ct.c_uint8),        # SLI Pro support - 0 = inactive, 1 = supported
        ("num_marshal_zones", ct.c_uint8),             # Number of marshal zones to follow
        ("marshal_zones", MarshalZone * 21),          # Array of marshal zones – max 21 per F1 25 UDP doc
        ("safety_car_status", ct.c_uint8),              # see enums.SafetyCarStatus
        ("network_game", ct.c_uint8),                  # 0 = offline, 1 = online
        ("num_weather_forecast_samples", ct.c_uint8),  # Number of weather forecast samples to follow
        ("weather_forecast_samples", WeatherForecastSample * 64),  # Array of weather forecast samples – max 64 per F1 25 UDP doc
        ("forecast_accuracy", ct.c_uint8),              # 0 = Perfect, 1 = Approximate
        ("ai_difficulty", ct.c_uint8),                # AI Difficulty rating – 0-110
        ("season_link_identifier", ct.c_uint32),       # Identifier for season - persists across saves
        ("weekend_link_identifier", ct.c_uint32),      # Identifier for weekend - persists across saves
        ("session_link_identifier", ct.c_uint32),      # Identifier for session - persists across saves
        ("pit_stop_window_ideal_lap", ct.c_uint8),      # Ideal lap to pit on for current strategy (player)
        ("pit_stop_window_latest_lap", ct.c_uint8),     # Latest lap to pit on for current strategy (player)
        ("pit_stop_rejoin_position", ct.c_uint8),         # Predicted position to rejoin at (player)
        ("steering_assist", ct.c_uint8),                # 0 = Off, 1 = On
        ("braking_assist", ct.c_uint8),                 # 0 = Off, 1 = Low, 2 = Medium, 3 = High
        ("gearbox_assist", ct.c_uint8),                # 1 = Manual, 2 = Manual & suggested gear, 3 = auto
        ("pit_assist", ct.c_uint8),                    # 0 = Off, 1 = On
        ("pit_release_assist", ct.c_uint8),            # 0 = Off, 1 = On
        ("ERS_assist", ct.c_uint8),                    # 0 = Off, 1 = On
        ("DRS_assist", ct.c_uint8),                    # 0 = Off, 1 = On
        ("dynamic_racing_line", ct.c_uint8),           # 0 = Off, 1 = Corners only, 2 = Full
        ("dynamic_racing_line_type", ct.c_uint8),      # 0 = 2D, 1 = 3D
        ("game_mode", ct.c_uint8),                    # see enums.GameMode
        ("rule_set", ct.c_uint8),                    # see enums.RuleSet
        ("time_of_day", ct.c_uint32),                # Local time of day - minutes since midnight
        ("session_length", ct.c_uint8),               # 0 = None, 2 = Very Short, 3 = Short, 4 = Medium, 5 = Medium Long, 6 = Long, 7 = Full
        ("speed_units_lead_player", ct.c_uint8),                 # Units for speed - 0 = MPH, 1 = KPH
        ("temperature_units_lead_player", ct.c_uint8),          # Units for temperature - 0 = Celsius, 1 = Fahrenheit
        ("speed_units_secondary_player", ct.c_uint8),             # Units for speed - 0 = MPH, 1 = KPH
        ("temperature_units_secondary_player", ct.c_uint8),      # Units for temperature - 0 = Celsius, 1 = Fahrenheit
        ("num_safety_car_periods", ct.c_uint8),              # Number of safety cars called during session
        ("num_virtual_safety_car_periods", ct.c_uint8),      # Number of virtual safety cars called
        ("num_red_flag_periods", ct.c_uint8),                # Number of red flags during session
        ("equal_car_performance", ct.c_uint8),              # 0 = Off, 1 = On
        ("recovery_mode", ct.c_uint8),                    # 0 = None, 1 = Flashback, 2 = Auto-Recovery
        ("flashback_limit", ct.c_uint8),                    # 0 = None, 1 = Medium, 2 = High, 3 = Unlimited)
        ("surface_type", ct.c_uint8),                   # 0 = Simplified, 1 = Realistic
        ("low_fuel_mode", ct.c_uint8),                    # 0 = Easy, 1 = Hard
        ("race_starts", ct.c_uint8),                    # 0 = Manual, 1 = Assisted
        ("tyre_temperature", ct.c_uint8),                    # 0 = Surface only, 1 = Surface & Carcass
        ("pit_lane_tyre_sim", ct.c_uint8),                    # 0 = On, 1 = Off
        ("car_damage", ct.c_uint8),                   # 0 = Off, 1 = Reduced, 2 = Standard, 3 = Simulation
        ("car_damage_rate", ct.c_uint8),                   # 0 = Reduced, 1 = Standard, 2 = Simulation
        ("collisions", ct.c_uint8),                 # 0 = Off, 1 = Player-to-Player Off, 2 = On
        ("collisions_off_for_first_lap_only", ct.c_uint8),  # 0 = Disabled, 1 = Enabled (Multiplayer)
        ("mp_unsafe_pit_release", ct.c_uint8),  # 0 = On, 1 = Off (Multiplayer)
        ("mp_off_for_griefing", ct.c_uint8),  # 0 = Disabled, 1 = Enabled (Multiplayer)
        ("corner_cutting_stringency", ct.c_uint8),  # 0 = Regular, 1 = Strict
        ("parc_ferme_rules", ct.c_uint8),  # 0 = Off, 1 = On
        ("pit_stop_expierience", ct.c_uint8),  # 0 = Automatic, 1 = Broadcast, 2 = Immersive
        ("safety_car", ct.c_uint8),  # 0 = Off, 1 = Reduced, 2 = Standard, 3 = Increased
        ("safety_car_expierience", ct.c_uint8),  # 0 = Automatic, 1 = Broadcast, 2 = Immersive
        ("formation_lap", ct.c_uint8),  # 0 = Off, 1 = On
        ("formation_lap_expierience", ct.c_uint8),  # 0 = Broadcast, 1 = Immersive
        ("red_flags", ct.c_uint8),  # 0 = Off, 1 = Reduced, 2 = Standard, 3 = Increased
        ("affects_licence_level_solo", ct.c_uint8),  # 0 = Off, 1 = On
        ("affects_licence_level_mp", ct.c_uint8),  # 0 = Off, 1 = On
        ("num_sessions_in_weekend", ct.c_uint8),  # Number of sessions in the following array
        ("weekend_structure", ct.c_uint8 * 12),  # Array of session types that form the weekend (see enums.SessionType)
        ("sector_2_lap_distance_start", ct.c_float),  # Distance in m around track where sector 2 starts
        ("sector_3_lap_distance_start", ct.c_float),  # Distance in m around track where sector 3 starts
        ("active_aero_track_status", ct.c_uint8),  # 0 = Full, 1 = Partial
        ("num_active_aero_zones", ct.c_uint8),  # Number of active aero zones to follow
        ("active_aero_zones", ActiveAeroZone * 8),  # Number of active aero zones – max 8 per F1 2026 DLC UDP doc
        ("num_active_aero_zones_partial", ct.c_uint8),  # Number of active aero zones with partial effect to follow
        ("active_aero_zones_partial", ActiveAeroZone * 8),  # List of active aero zones with partial effect – max 8 per F1 2026 DLC UDP doc
        ("num_drs_zones", ct.c_uint8),  # Number of DRS zones to follow
        ("drs_zones", DRSZone * 4),  # List of DRS zones – max 4 per F1 2026 DLC UDP doc
        ("start_reaction_time", ct.c_float),  # Driver start reaction time in seconds
        ("anti_lock_brakes_assist", ct.c_uint8),  # 0 = Off, 1 = On
        ("traction_control_assist", ct.c_uint8),  # 0 = Off, 1 = On
        ("dynamic_racing_line_hi_vis", ct.c_uint8),  # 0 = Off, 1 = On
        ("dynamic_racing_line_colour_blind", ct.c_uint8),  # 0 = Off, 1 = Protanopia, 2 = Deuteranopia, 3 = Tritanopia
        ("recurring_rewind_prompt", ct.c_uint8),  # 0 = Off, 1 = On

    ]
# -------------------------------------------------------------------------------


# --- Lap Data Packet -----------------------------------------------------------
class LapData(_Struct):
    """One car's lap timing and position (lap_data packet)."""

    _fields_ = [
        ("last_lap_time_ms", ct.c_uint32),                       # Last lap time in milliseconds
        ("current_lap_time_ms", ct.c_uint32),                    # Current time around the lap in milliseconds
        ("sector1_time_ms_part", ct.c_uint16),                  # Sector 1 time in milliseconds part
        ("sector1_time_minutes_part", ct.c_uint8),             # Sector 1 whole minute part
        ("sector2_time_ms_part", ct.c_uint16),                  # Sector 2 time in milliseconds part
        ("sector2_time_minutes_part", ct.c_uint8),             # Sector 2 whole minute part
        ("delta_to_car_in_front_ms_part", ct.c_uint16),          # Time delta to car in front in milliseconds
        ("delta_to_car_in_front_minutes_part", ct.c_uint8),    # Time delta to car in front whole minute part
        ("delta_to_race_leader_ms_part", ct.c_uint16),           # Time delta to racelader in milliseconds part
        ("delta_to_race_leader_minutes_part", ct.c_uint8),     # Time delta to raceleader whole minute part
        ("lap_distance", ct.c_float),                           # Distance vehicle is around current lap in metres – could be negative if line hasn’t been crossed yet
        ("total_distance", ct.c_float),                         # Total distance travelled in session in metres – could be negative if line hasn’t been crossed yet
        ("safety_car_delta", ct.c_float),                       # Delta in seconds for safety car
        ("car_position", ct.c_uint8),                           # Car race position
        ("current_lap_num", ct.c_uint8),                        # Current lap number
        ("pit_status", ct.c_uint8),                             # 0 = none, 1 = pitting, 2 = in pit area - see enums.PitStatus
        ("num_pit_stops", ct.c_uint8),                          # Number of pit stops taken in this race
        ("sector", ct.c_uint8),                                 # 0 = sector1, 1 = sector2, 2 = sector3 - see enums.Sector
        ("current_lap_invalid", ct.c_uint8),                    # Current lap invalid - 0 = valid, 1 = invalid
        ("penalties", ct.c_uint8),                              # Accumulated time penalties in seconds to be added
        ("total_warnings", ct.c_uint8),                         # Accumulated number of warnings issued
        ("corner_cutting_warnings", ct.c_uint8),                # Accumulated number of corner cutting warnings issued
        ("num_unserved_drive_through_pens", ct.c_uint8),        # Num drive through pens left to serve
        ("num_unserved_stop_go_pens", ct.c_uint8),              # Num stop go pens left to serve
        ("grid_position", ct.c_uint8),                          # Grid position the vehicle started the race in    
        ("driver_status", ct.c_uint8),                          # Status of driver - 0 = in garage, 1 = flying lap 2 = in lap, 3 = out lap, 4 = on track
                                                                # - see enums.DriverStatus
        ("result_status", ct.c_uint8),                          # Result status - 0 = invalid, 1 = inactive, 2 = active, 3 = finished, 4 = didnotfinish,
                                                                # 5 = disqualified, 6 = not classified, 7 = retired - see enums.ResultStatus
        ("pit_lane_timer_active", ct.c_uint8),                  # Pit lane timing, 0 = inactive, 1 = active
        ("pit_lane_time_in_lane_ms", ct.c_uint16),              # If active, the current time spent in the pit lange in ms
        ("pit_stop_timer_ms", ct.c_uint16),                     # Time of the actual pit stop in ms 
        ("pit_stop_should_serve_pen", ct.c_uint8),              # Whether the car should serve a penalty at this stop
        ("speed_trap_fastest_speed", ct.c_float),               # Fastet speed through the speed trap for this car in kmph
        ("speed_trap_fastest_lap", ct.c_uint8),                 # Lap no the fastest speed was achieved, 255 if not set
    ]


class PacketLapData(_Struct):
    _fields_ = [
        ("header", PacketHeader),                      # Header
        ("lap_data", LapData * _NUM_CARS),             # Lap data for all cars on track
        ("time_trial_pb_car_idx", ct.c_uint8),         # Index of Personal Best car in time trial (255 if invalid)
        ("time_trial_rival_car_idx", ct.c_uint8),      # Index of Rival car in time trial (255 if invalid)
    ]


    def __repr__(self) -> str:
        return (f"{type(self).__name__}(format={self.header.packet_format}, "
                f"frame={self.header.frame_identifier}, cars={_NUM_CARS})")
# ----------------------------------------------------------------------------


# --- Event Packet -----------------------------------------------------------
class FastestLap(_Struct):
    """Fastest lap event data (event data details)."""

    _fields_ = [
        ("vehicle_idx", ct.c_uint8),  # Vehicle index of car achieving fastest lap
        ("lap_time", ct.c_float),     # Lap time is in seconds
    ]


class Retirement(_Struct):
    """Retirement event data (event data details)."""

    _fields_ = [
        ("vehicle_idx", ct.c_uint8),  # Vehicle index of car retiring
        ("reason", ct.c_uint8),       # Reason for retirement - see enums.ResultReason
    ]


class DRSDisabled(_Struct):
    """DRS disabled event data (event data details)."""

    _fields_ = [
        ("reason", ct.c_uint8),  # 0 = Wet track, 1 = Safety car deployed, 2 = Red flag, 3 = Min lap not reached
    ]


class TeamMateInPits(_Struct):
    """Team mate in pits event data (event data details)."""

    _fields_ = [
        ("vehicle_idx", ct.c_uint8),  # Vehicle index of team mate
    ]


class RaceWinner(_Struct):
    """Race winner event data (event data details)."""
    
    _fields_ = [
        ("vehicle_idx", ct.c_uint8),  # Vehicle index of the race winner
    ]


class Penalty(_Struct):
    """Penalty event data (event data details)."""

    _fields_ = [
        ("penalty_type", ct.c_uint8),  # Penalty type - see enums.PenaltyType
        ("infringement_type", ct.c_uint8),  # Infringement type - see enums.InfringementType
        ("vehicle_idx", ct.c_uint8),  # Vehicle index of the car the penalty is applied to
        ("other_vehicle_idx", ct.c_uint8),  # Vehicle index of the other car involved
        ("time", ct.c_uint8),  # Time gained, or time spent doing action in seconds
        ("lap_num", ct.c_uint8),  # Lap the penalty occurred on
        ("places_gained", ct.c_uint8),  # Number of places gained by this infraction
    ]


class SpeedTrap(_Struct):
    """Speed trap event data (event data details)."""

    _fields_ = [
        ("vehicle_idx", ct.c_uint8),  # Vehicle index of the vehicle triggering speed trap
        ("speed", ct.c_float),  # Top speed achieved in kilometres per hour
        ("is_overall_fastest_in_session", ct.c_uint8),  # Overall fastest speed in session = 1, otherwise 0
        ("is_driver_fastest_in_session", ct.c_uint8),  # Fastest speed for driver in session = 1, otherwise 0
        ("fastest_vehicle_idx_in_session", ct.c_uint8),  # Vehicle index of the vehicle that is the fastest in this session
        ("fastest_speed_in_session", ct.c_float),  # Speed of the vehicle that is the fastest in this session in kilometres per hour
    ]


class StartLights(_Struct):
    """Start lights event data (event data details)."""

    _fields_ = [
        ("num_lights", ct.c_uint8),  # Number of lights showing
    ]


class DriveThroughPenaltyServed(_Struct):
    """Drive through penalty served event data (event data details)."""

    _fields_ = [
        ("vehicle_idx", ct.c_uint8),  # Vehicle index of the vehicle serving drive through
    ]


class StopGoPenaltyServed(_Struct):
    """Stop go penalty served event data (event data details)."""

    _fields_ = [
        ("vehicle_idx", ct.c_uint8),  # Vehicle index of the vehicle serving stop go
        ("stop_time", ct.c_float),  # Time spent serving stop go in seconds
    ]


class Flashback(_Struct):
    """Flashback event data (event data details)."""

    _fields_ = [
        ("flashback_frame_identifier", ct.c_uint32),  # Frame identifier flashed back to
        ("flashback_session_time", ct.c_float),  # Session time flashed back to
    ]


class Buttons(_Struct):
    """Buttons event data (event data details)."""

    _fields_ = [
        ("buttons", ct.c_uint32),  # Bit flags specifying which buttons are being pressed - see enums.Buttons
    ]


class Overtake(_Struct):
    """Overtake event data (event data details)."""

    _fields_ = [
        ("overtaking_vehicle_idx", ct.c_uint8),  # Vehicle index of the vehicle overtaking
        ("being_overtaken_vehicle_idx", ct.c_uint8),  # Vehicle index of the vehicle being overtaken
    ]


class SafetyCar(_Struct):
    """Safety car event data (event data details)."""

    _fields_ = [
        ("safety_car_status", ct.c_uint8),  # Status of safety car - see enums.SafetyCarStatus
        ("event_type", ct.c_uint8),  # 0 = Deployed, 1 = Returning, 2 = Returned, 3 = Resume Race
    ]


class Collision(_Struct):
    """Collision event data (event data details)."""

    _fields_ = [
        ("vehicle1_idx", ct.c_uint8),  # Vehicle index of the first vehicle involved
        ("vehicle2_idx", ct.c_uint8),  # Vehicle index of the second vehicle
        ("severity", ct.c_uint8),  # Severity of the collision - 0 = low, 1 = medium, 2 = high
    ]


class EventDataDetails(ct.Union):
    """Event data details (event_data_details)."""

    _pack_ = 1
    _fields_ = [
        ("fastest_lap", FastestLap),
        ("retirement", Retirement),
        ("drs_disabled", DRSDisabled),
        ("team_mate_in_pits", TeamMateInPits),
        ("race_winner", RaceWinner),
        ("penalty", Penalty),
        ("speed_trap", SpeedTrap),
        ("start_lights", StartLights),
        ("drive_through_penalty_served", DriveThroughPenaltyServed),
        ("stop_go_penalty_served", StopGoPenaltyServed),
        ("flashback", Flashback),
        ("buttons", Buttons),
        ("overtake", Overtake),
        ("safety_car", SafetyCar),
        ("collision", Collision),
    ]


class PacketEventData(_Struct):
    """event_packet, which holds details of events that happen during the course of a session."""

    _fields_ = [
        ("header", PacketHeader),  # Header
        ("event_string_code", ct.c_char * 4),  # Event string code, see below
        ("event_data_details", EventDataDetails),  # Event data details - should be interpreted differently for each type
    ]

    def __repr__(self) -> str:
        return (f"{type(self).__name__}(format={self.header.packet_format}, "
                f"frame={self.header.frame_identifier}, event={self.event_string_code.decode()})")
# -------------------------------------------------------------------------------


# --- Participants Packet -----------------------------------------------------------
class LiveryColour(_Struct):
    """One livery colour (participants packet)."""

    _fields_ = [
        ("red", ct.c_uint8),  # Red colour component
        ("green", ct.c_uint8),  # Green colour component
        ("blue", ct.c_uint8),  # Blue colour component
    ]


class ParticipantData(_Struct):
    """One car's participant data (participants packet)."""

    _fields_ = [
        ("ai_controlled", ct.c_uint8),  # Whether the car is AI (1) or Human (0) controlled
        ("driver_id", ct.c_uint16),       # Driver id - see enums.DriverId, 65535 if network human
        ("network_id", ct.c_uint16),      # Network id - unique identifier for network players
        ("team_id", ct.c_uint16),         # Team id - see enums.TeamId
        ("my_team", ct.c_uint8),         # My team flag - 1 = My Team, 0 = otherwise
        ("race_number", ct.c_uint8),    # Race number of the car
        ("nationality", ct.c_uint8),     # Nationality of the driver
        ("name", ct.c_char * 32),       # Name of participant in UTF-8 format – null terminated, will be truncated with … (U+2026) if too long
        ("your_telemetry", ct.c_uint8),  # The player's UDP setting, 0 = restricted, 1 = public
        ("shown_online_names", ct.c_uint8),  # The player's show online names setting, 0 = Off, 1 = On
        ("tech_level", ct.c_uint16),  # F1 World tech level
        ("platform", ct.c_uint8),  # 1 = Steam, 3 = PlayStation, 4 = Xbox, 6 = Origin, 255 = unknown
        ("num_colours", ct.c_uint8),  # Number of colours valid for this car
        ("livery_colours", LiveryColour * 4),  # Colours for the car
    ]


class PacketParticipantsData(_Struct):
    _fields_ = [
        ("header", PacketHeader),                      # Header
        ("num_active_cars", ct.c_uint8),             # Number of active cars in the data – should match number of cars on HUD
        ("participants", ParticipantData * _NUM_CARS),  # Array of participants
    ]

    def __repr__(self) -> str:
        return (f"{type(self).__name__}(format={self.header.packet_format}, "
                f"frame={self.header.frame_identifier}, cars={_NUM_CARS})")
# ---------------------------------------------------------------------------


# --- Car Setups Packet -----------------------------------------------------------
class CarSetupData(_Struct):
    """One car's setup data (car_setups packet)."""

    _fields_ = [
        ("front_wing", ct.c_uint8),  # Front wing aero
        ("rear_wing", ct.c_uint8),   # Rear wing aero
        ("on_throttle", ct.c_uint8),  # Differential adjustment on throttle (percentage)
        ("off_throttle", ct.c_uint8),  # Differential adjustment off throttle (percentage)
        ("front_camber", ct.c_float),  # Front camber angle (suspension geometry)
        ("rear_camber", ct.c_float),   # Rear camber angle (suspension geometry)
        ("front_toe", ct.c_float),     # Front toe angle (suspension geometry)
        ("rear_toe", ct.c_float),      # Rear toe angle (suspension geometry)
        ("front_suspension", ct.c_uint8),  # Front suspension
        ("rear_suspension", ct.c_uint8),   # Rear suspension
        ("front_anti_roll_bar", ct.c_uint8),  # Front anti-roll bar
        ("rear_anti_roll_bar", ct.c_uint8),   # Rear anti-roll bar
        ("front_suspension_height", ct.c_uint8),  # Front ride height
        ("rear_suspension_height", ct.c_uint8),   # Rear ride height
        ("brake_pressure", ct.c_uint8),  # Brake pressure (percentage)
        ("brake_bias", ct.c_uint8),      # Brake bias (percentage)
        ("engine_braking", ct.c_uint8),  # Engine braking (percentage) 
        ("rear_left_tyre_pressure", ct.c_float),  # Rear left tyre pressure in PSI
        ("rear_right_tyre_pressure", ct.c_float),  # Rear right tyre pressure in PSI
        ("front_left_tyre_pressure", ct.c_float),  # Front left tyre pressure in PSI
        ("front_right_tyre_pressure", ct.c_float),  # Front right tyre pressure in PSI
        ("ballast", ct.c_uint8),  # Ballast
        ("fuel_load", ct.c_float),  # Fuel load in kg
    ]


class PacketCarSetupData(_Struct):
    """car_setups packet, which holds setup data for all cars in the session."""

    _fields_ = [
        ("header", PacketHeader),                        # Header
        ("car_setups", CarSetupData * _NUM_CARS),  # Setup data for all cars on track
        ("next_front_wing_Values", ct.c_float),  # Value of front wing after next pit stop - player only
    ]

    def __repr__(self) -> str:
        return (f"{type(self).__name__}(format={self.header.packet_format}, "
                f"frame={self.header.frame_identifier}, cars={_NUM_CARS})")
#----------------------------------------------------------------------------


# --- Car Telemetry Packet -----------------------------------------------------------
class CarTelemetryData(_Struct):
    """One car's telemetry (car_telemetry packet)."""

    _fields_ = [
        ("speed", ct.c_uint16),                         # Speed of car in kilometres per hour
        ("throttle", ct.c_float),                       # Amount of throttle applied (0.0 to 1.0)
        ("steer", ct.c_float),                          # Steering (-1.0 (full lock left) to 1.0 (full lock right))
        ("brake", ct.c_float),                          # Amount of brake applied (0.0 to 1.0)
        ("clutch", ct.c_uint8),                         # Amount of clutch applied (0 to 100)
        ("gear", ct.c_int8),                            # Gear selected (1-8, N=0, R=-1)
        ("engine_rpm", ct.c_uint16),                    # Engine RPM
        ("drs", ct.c_uint8),                            # 0 = off, 1 = on
        ("rev_lights_percent", ct.c_uint8),             # Rev lights indicator (percentage)
        ("rev_lights_bit_value", ct.c_uint16),          # Rev lights (bit 0 = leftmost LED, bit 14 = rightmost LED)
        ("brakes_temperature", ct.c_uint16 * 4),        # Brakes temperature (celsius)
        ("tyres_surface_temperature", ct.c_uint8 * 4),  # Tyres surface temperature (celsius)
        ("tyres_inner_temperature", ct.c_uint8 * 4),    # Tyres inner temperature (celsius)
        ("engine_temperature", ct.c_uint8),            # Engine temperature (celsius)
        ("tyres_pressure", ct.c_float * 4),             # Tyres pressure (PSI)
        ("surface_type", ct.c_uint8 * 4),               # Driving surface, per tyre (see enums.SurfaceType)
    ]

class PacketCarTelemetryData(_Struct):
    """car_telemetry packet, which holds telemetry for all cars in the session."""

    _fields_ = [
        ("header", PacketHeader),                                   # Header
        ("car_telemetry_data", CarTelemetryData * _NUM_CARS),
        ("mfd_panel_index", ct.c_uint8),                            # Index of MFD panel open - 255 = MFD closed
                                                                    # Single player, race - 0 = Car setup, 1 = Pits, 2 = Damage, 3 =  Engine, 4 = Temperatures
                                                                    # May vary depending on game mode
        ("mfd_panel_index_secondary_player", ct.c_uint8),           # see above
        ("suggested_gear", ct.c_int8),                              # 0 if no gear suggested
    ]

    def __repr__(self) -> str:
        return (f"{type(self).__name__}(format={self.header.packet_format}, "
                f"frame={self.header.frame_identifier}, cars={_NUM_CARS})")
#----------------------------------------------------------------------------


# --- Car Status Packet -----------------------------------------------------------
class CarStatusData(_Struct):
    """One car's status (car_status packet)."""

    _fields_ = [
        ("traction_control", ct.c_uint8),  # 0 = off, 1 = medium, 2 = full
        ("anti_lock_brakes", ct.c_uint8),  # 0 (off) - 1 (on)
        ("fuel_mix", ct.c_uint8),          # 0 = lean, 1 = standard, 2 = rich, 3 = max
        ("front_brake_bias", ct.c_uint8),   # Front brake bias (percentage)
        ("pit_limiter_status", ct.c_uint8),  # Pit limiter status - 0 = off, 1 = on
        ("fuel_in_tank", ct.c_float),       # Current fuel mass
        ("fuel_capacity", ct.c_float),      # Fuel capacity
        ("fuel_remaining_laps", ct.c_float), # Fuel remaining in terms of laps (value on MFD)
        ("max_rpm", ct.c_uint16),          # Cars max RPM, point of rev limiter
        ("idle_rpm", ct.c_uint16),         # Cars idle RPM
        ("max_gears", ct.c_uint8),         # Maximum number of gears the car has
        ("drs_allowed", ct.c_uint8),       # 0 = not allowed, 1 = allowed
        ("drs_activation_distance", ct.c_uint16),  # 0 = DRS not available, non-zero - DRS will be available
                                                    # in [X] metres
        ("actual_tyre_compound", ct.c_uint8),  # see enums.TyreCompound
        ("visual_tyre_compound", ct.c_uint8),  # see enums.TyreVisualCompound
        ("tyres_age_laps", ct.c_uint8),        # Age in laps of the current set of tyres
        ("vehicle_fia_flags", ct.c_int8),         # -1 = invalid/unknown, 0 = none, 1 = green, 2 = blue, 3 = yellow
        ("engine_power_ice", ct.c_float),  # Engine power output of the ICE (W)
        ("engine_power_mguk", ct.c_float),  # Engine power output of the MGU-K (W)
        ("ers_engine_store_energy", ct.c_float),  # ERS energy store in Joules
        ("ers_deploy_mode", ct.c_uint8),  # see enums.ERSDeployMode
        ("ers_harvested_this_lap_mguk", ct.c_float),  # ERS energy harvested this lap by MGU-K
        ("ers_harvested_this_lap_mguh", ct.c_float),  # ERS energy harvested this lap by MGU-H
        ("ers_harveseted_limit_per_lap", ct.c_float),  # ERS energy harvest limit for this lap
        ("ers_deployed_this_lap", ct.c_float),  # ERS energy deployed this lap
        ("network_paused", ct.c_uint8),  # Whether the car is paused in a network game
    ]


class PacketCarStatusData(_Struct):
    """car_status packet, which holds car status for all cars in the session."""

    _fields_ = [
        ("header", PacketHeader),                        # Header
        ("car_status_data", CarStatusData * _NUM_CARS),  # Car status data for all cars on track
    ]

    def __repr__(self) -> str:
        return (f"{type(self).__name__}(format={self.header.packet_format}, "
                f"frame={self.header.frame_identifier}, cars={_NUM_CARS})")
#----------------------------------------------------------------------------    


# -- Final Classification Packet -----------------------------------------------------------
class FinalClassificationData(_Struct):
    """One car's final classification data (final_classification packet)."""

    _fields_ = [
        ("position", ct.c_uint8),  # Finishing position
        ("num_laps", ct.c_uint8),  # Number of laps completed
        ("grid_position", ct.c_uint8),  # Grid position of the car
        ("points", ct.c_uint8),  # Number of points scored
        ("num_pit_stops", ct.c_uint8),  # Number of pit stops made
        ("result_status", ct.c_uint8),  # Result status - see enums.ResultStatus
        ("result_reason", ct.c_uint8),  # Result reason - see enums.ResultReason
        ("best_lap_time_in_ms", ct.c_uint32),  # Best lap time of the session in milliseconds
        ("total_race_time", ct.c_double),  # Total race time in seconds without penalties
        ("penalties_time", ct.c_uint8),  # Total penalties accumulated in seconds
        ("num_penalties", ct.c_uint8),  # Number of penalties applied to this driver
        ("num_tyre_stints", ct.c_uint8),  # Number of tyres stints up to maximum
        ("tyre_stints_actual", ct.c_uint8 * 8),  # Actual tyres used by this driver
        ("tyre_stints_visual", ct.c_uint8 * 8),  # Visual tyres used by this driver
        ("tyre_stints_end_laps", ct.c_uint8 * 8),  # Lap number stints end on
    ]


class PacketFinalClassificationData(_Struct):
    """final_classification packet, which holds final classification for all cars in the session."""

    _fields_ = [
        ("header", PacketHeader),  # Header
        ("num_cars", ct.c_uint8),  # Number of cars in the final classification
        ("final_classification_data", FinalClassificationData * _NUM_CARS),  # Final classification data for all cars on track
    ]

    def __repr__(self) -> str:
        return (f"{type(self).__name__}(format={self.header.packet_format}, "
                f"frame={self.header.frame_identifier}, cars={_NUM_CARS})")
#----------------------------------------------------------------------------


# --- Lobby Info Packet -----------------------------------------------------------
class LobbyInfoData(_Struct):
    """One car's lobby info data (lobby_info packet)."""

    _fields_ = [
        ("ai_controlled", ct.c_uint8),  # Whether the car is AI (1) or Human (0) controlled
        ("team_id", ct.c_uint16),  # Team id - see enums.TeamId
        ("nationality", ct.c_uint8),  # Nationality - see enums.Nationality
        ("platform", ct.c_uint8),  # 1 = Steam, 3 = PlayStation, 4 = Xbox, 6 = Origin, 255 = unknown
        ("name", ct.c_char * 32),  # Name of participant in UTF-8 format – null terminated, will be truncated with … (U+2026) if too long
        ("car_number", ct.c_uint8),  # Car number of the player
        ("your_telemetry", ct.c_uint8),  # The player's UDP setting, 0 = restricted, 1 = public
        ("shown_online_names", ct.c_uint8),  # The player's show online names setting, 0 = Off, 1 = On
        ("tech_level", ct.c_uint16),  # F1 World tech level
        ("ready_status", ct.c_uint8),  # Ready status - 0 = not ready, 1 = ready
    ]


class PacketLobbyInfoData(_Struct):
    """lobby_info packet, which holds lobby info for all cars in the session."""

    _fields_ = [
        ("header", PacketHeader),  # Header
        ("num_players", ct.c_uint8),  # Number of players in the lobby data
        ("lobby_info_data", LobbyInfoData * _NUM_CARS),  # Lobby info data for all cars on track
    ]

    def __repr__(self) -> str:
        return (f"{type(self).__name__}(format={self.header.packet_format}, "
                f"frame={self.header.frame_identifier}, cars={_NUM_CARS})")
#----------------------------------------------------------------------------


# --- Car Damage Packet -----------------------------------------------------------
class CarDamageData(_Struct):
    """One car's damage data (car_damage packet)."""

    _fields_ = [
        ("tyres_wear", ct.c_float * 4),  # Tyre wear (percentage)
        ("tyres_damage", ct.c_uint8 * 4),  # Tyre damage (percentage)
        ("brakes_damage", ct.c_uint8 * 4),  # Brakes damage (percentage)
        ("tyre_blisters", ct.c_uint8 * 4),  # Tyre blisters value (percentage)
        ("front_left_wing_damage", ct.c_uint8),  # Front left wing damage (percentage)
        ("front_right_wing_damage", ct.c_uint8),  # Front right wing damage (percentage)
        ("rear_wing_damage", ct.c_uint8),  # Rear wing damage (percentage)
        ("floor_damage", ct.c_uint8),  # Floor damage (percentage)
        ("diffuser_damage", ct.c_uint8),  # Diffuser damage (percentage)
        ("sidepod_damage", ct.c_uint8),  # Sidepod damage (percentage)
        ("drs_fault", ct.c_uint8),  # DRS fault - 0 = OK, 1 = fault
        ("ers_fault", ct.c_uint8),  # ERS fault - 0 = OK, 1 = fault
        ("gearbox_damage", ct.c_uint8),  # Gearbox damage (percentage)
        ("engine_damage", ct.c_uint8),  # Engine damage (percentage)
        ("engine_mguh_wear", ct.c_uint8),  # Engine wear MGU-H (percentage)
        ("engine_es_wear", ct.c_uint8),  # Engine wear ES (percentage)
        ("engine_ce_wear", ct.c_uint8),  # Engine wear CE (percentage)
        ("engine_ice_wear", ct.c_uint8),  # Engine wear ICE (percentage)
        ("engine_mguk_wear", ct.c_uint8),  # Engine wear MGU-K (percentage)
        ("engine_tc_wear", ct.c_uint8),  # Engine wear TC (percentage)
        ("engine_blown", ct.c_uint8),  # Engine blown - 0 = OK, 1 = fault
        ("engine_seized", ct.c_uint8),  # Engine seized - 0 = OK, 1 = fault
    ]


class PacketCarDamageData(_Struct):
    """car_damage packet, which holds car damage for all cars in the session."""

    _fields_ = [
        ("header", PacketHeader),                        # Header
        ("car_damage_data", CarDamageData * _NUM_CARS),  # Car damage data for all cars on track
    ]

    def __repr__(self) -> str:
        return (f"{type(self).__name__}(format={self.header.packet_format}, "
                f"frame={self.header.frame_identifier}, cars={_NUM_CARS})")
#----------------------------------------------------------------------------
    

# --- Session History Packet -----------------------------------------------------------
class LapHistoryData(_Struct):
    """One car's lap history data (lap_history packet)."""

    _fields_ = [
        ("lap_time_in_ms", ct.c_uint32),  # Lap time in milliseconds
        ("sector1_time_ms_part", ct.c_uint16),  # Sector 1 time in milliseconds
        ("sector1_time_minutes_part", ct.c_uint8),  # Sector 1 whole minute part
        ("sector2_time_ms_part", ct.c_uint16),  # Sector 2 time in milliseconds
        ("sector2_time_minutes_part", ct.c_uint8),  # Sector 2 whole minute part
        ("sector3_time_ms_part", ct.c_uint16),  # Sector 3 time in milliseconds
        ("sector3_time_minutes_part", ct.c_uint8),  # Sector 3 whole minute part
        ("lap_valid_bit_flags", ct.c_uint8),  # 0x01 bit set = sector 1 valid, 0x02 bit set = sector 2 valid, 0x04 bit set = sector 3 valid, 0x08 bit set = lap valid
    ]



class TyreStintHistoryData(_Struct):
    """One car's tyre stint history data (tyre_stints_history packet)."""

    _fields_ = [
        ("end_lap", ct.c_uint8),  # Lap the tyre usage ends on (255 of current tyre)
        ("tyre_actual_compound", ct.c_uint8),  # Actual tyres used by this driver - see enums.TyreCompound
        ("tyre_visual_compound", ct.c_uint8),  # Visual tyres used by this driver - see enums.TyreVisualCompound
    ]


class PacketSessionHistoryData(_Struct):
    """session_history packet. This packet works slighly diffrent then others.
    Each packet relates to a specific vehicle and is sent every 1/20s and the vehicle being sent is cycled through.
    In a 20 car race there should be an update for each vehicle at least once every second.
    """

    _fields_ = [
        ("header", PacketHeader),  # Header
        ("car_idx", ct.c_uint8),  # Index of the car this lap history data relates to
        ("num_laps", ct.c_uint8),  # Number of laps in the data (including current partial lap)
        ("num_tyre_stints", ct.c_uint8),  # Number of tyre stints in the data
        ("best_lap_time_lap_num", ct.c_uint8),  # Lap the best lap time was achieved on
        ("best_sector1_time_lap_num", ct.c_uint8),  # Lap the best sector 1 time was achieved on
        ("best_sector2_time_lap_num", ct.c_uint8),  # Lap the best sector 2 time was achieved on
        ("best_sector3_time_lap_num", ct.c_uint8),  # Lap the best sector 3 time was achieved on
        ("lap_history_data", LapHistoryData * 100),  # 100 laps of max data
        ("tyre_stints_history_data", TyreStintHistoryData * 8),  # Tyre stint history data for this car's current session
    ]

    def __repr__(self) -> str:
        return (f"{type(self).__name__}(format={self.header.packet_format}, "
                f"frame={self.header.frame_identifier}, car_idx={self.car_idx})")
#----------------------------------------------------------------------------


# --- Tyre Sets Packet -----------------------------------------------------------
class TyreSetData(_Struct):
    """One car's tyre set data (tyre_sets_data packet)."""

    _fields_ = [
        ("actual_tyre_compound", ct.c_uint8),  # Actual tyres used by this driver - see enums.TyreCompound
        ("visual_tyre_compound", ct.c_uint8),  # Visual tyres used by this driver - see enums.TyreVisualCompound
        ("wear", ct.c_uint8),  # Tyre wear (percentage)
        ("available", ct.c_uint8),  # Whether this set is currently available
        ("recommended_session", ct.c_uint8),  # Recommended session for this tyre set
        ("life_span", ct.c_uint8),  # Laps left in this tyre set
        ("usable_live", ct.c_uint8),  # Max number of laps reccommended for this compound
        ("lap_delta_time", ct.c_uint16),  # Lap delta time in milliseconds compared to fitted set
        ("fitted", ct.c_uint8),  # Whether this set is fitted or not
    ]


class PacketTyreSetsData(_Struct):
    """tyre_sets_data packet, which holds tyre set data for all cars in the session."""

    _fields_ = [
        ("header", PacketHeader),  # Header
        ("car_idx", ct.c_uint8),  # Index of the car this tyre set data relates to
        ("tyre_sets_data", TyreSetData * 20),  # 13 (dry) + 7 (wet)
        ("fitted_set_idx", ct.c_uint8),  # Index into array of fitted tyre
    ]

    def __repr__(self) -> str:
        return (f"{type(self).__name__}(format={self.header.packet_format}, "
                f"frame={self.header.frame_identifier}, car_idx={self.car_idx})")
#----------------------------------------------------------------------------

# --- Motion Ex Packet -----------------------------------------------------------
class PacketMotionExData(_Struct):
    """Motion Ex packet gives extended data fro the car being driven with the goal
    of being able to drive a motion platform setup."""

    _fields_ = [
        ("header", PacketHeader),  # Header
        ("suspension_position", ct.c_float * 4),  # Note: All wheel arrays have the following order: RL, RR, FL, FR.
        ("suspension_velocity", ct.c_float * 4),    # RL, RR, FL, FR.
        ("suspension_acceleration", ct.c_float * 4), # RL, RR, FL, FR.
        ("wheel_speed", ct.c_float * 4),    # Speed of each wheel
        ("wheel_slip_ratio", ct.c_float * 4),   # Slip ratio for each wheel
        ("wheel_slip_angle", ct.c_float * 4),   # Slip angle for each wheel
        ("wheel_lat_force", ct.c_float * 4),   # Lateral force for each wheel
        ("wheel_long_force", ct.c_float * 4),   # Longitudinal force for each wheel
        ("height_of_cog_above_ground", ct.c_float),  # Height of the centre of gravity above the ground
        ("local_velocity_x", ct.c_float),  # Velocity in local space - meters/s
        ("local_velocity_y", ct.c_float),  # Velocity in local space - meters/s
        ("local_velocity_z", ct.c_float),  # Velocity in local space - meters/s
        ("angular_velocity_x", ct.c_float),  # Angular velocity x-component - radians/s
        ("angular_velocity_y", ct.c_float),  # Angular velocity y-component - radians/s
        ("angular_velocity_z", ct.c_float),  # Angular velocity z-component - radians/s
        ("angular_acceleration_x", ct.c_float),  # Angular acceleration x-component - radians/s^2
        ("angular_acceleration_y", ct.c_float),  # Angular acceleration y-component - radians/s^2
        ("angular_acceleration_z", ct.c_float),  # Angular acceleration z-component - radians/s^2
        ("front_wheels_angle", ct.c_float),  # Current front wheels angle in radians
        ("wheel_vert_force", ct.c_float * 4),  # Vertical force for each wheel
        ("front_aero_height", ct.c_float),  # Front plank edge height above the road surface
        ("rear_aero_height", ct.c_float),  # Rear plank edge height above the road surface
        ("front_roll_angle", ct.c_float),  # Roll angle of the front suspension
        ("rear_roll_angle", ct.c_float),  # Roll angle of the rear suspension
        ("chassis_yaw", ct.c_float),  # Yaw angle of the chassis relative to the direction of motion - radians
        ("chassis_pitch", ct.c_float),  # Pitch angle of the chassis relative to the direction of motion - radians
        ("wheel_camber", ct.c_float * 4),  # Camber of each wheel in radians
        ("wheel_camber_gain", ct.c_float * 4), # Camber gain of each wheel in radians, 
                                                # difference between the active camber and dynamic camber
    ]


    def __repr__(self) -> str:
        return (f"{type(self).__name__}(format={self.header.packet_format}, "
                f"frame={self.header.frame_identifier})")
#----------------------------------------------------------------------------


# --- Time Trial Data Packet -----------------------------------------------------------
class TimeTrialDataSet(_Struct):
    """Time trial data set packet. Only relevent to time trial mode.
    It is not sent in other game modes."""

    _fields_ = [
    ("car_idx", ct.c_uint8),  # Index of the car this data relates to
    ("team_id", ct.c_uint16),  # Team id - see enums.TeamId
    ("lap_time_in_ms", ct.c_uint32),  # Lap time in milliseconds
    ("sector1_time_in_ms", ct.c_uint32),  # Sector 1 time in milliseconds
    ("sector2_time_in_ms", ct.c_uint32),  # Sector 2 time in milliseconds
    ("sector3_time_in_ms", ct.c_uint32),  # Sector 3 time in milliseconds
    ("traction_control", ct.c_uint8),  # 0 = assist off, 1 = asssist on
    ("gearbox_assist", ct.c_uint8),  # 0 = assist off, 1 = asssist on
    ("anti_lock_brakes", ct.c_uint8),  # 0 = assist off, 1 = asssist on
    ("equal_car_performance", ct.c_uint8),  # 0 = Realistic, 1 = Equal
    ("custom_setup", ct.c_uint8),  # 0 = No, 1 = Yes
    ("valid", ct.c_uint8)  # 0 = Invalid, 1 = Valid
    ]


class PacketTimeTrialData(_Struct):
    """time_trial_data packet. Only relevant to time trial mode, not sent in other game modes."""
    
    _fields_ = [
        ("header", PacketHeader),  # Header
        ("player_session_best_data_set", TimeTrialDataSet),  # Player session best data set
        ("personal_best_data_set", TimeTrialDataSet),  # Personal best data set
        ("rival_data_set", TimeTrialDataSet),  # Rival data set
    ]

    
    def __repr__(self) -> str:
        return (f"{type(self).__name__}(format={self.header.packet_format}, "
                f"frame={self.header.frame_identifier})")
#----------------------------------------------------------------------------


# --- Lap Positions Packet -----------------------------------------------------------
class PacketLapPositionsData(_Struct):
    """lap_positions packet, indicates which position each car was on at the start of each lap.
    Used to construct a lap positions chart. Max 50 laps will be transmitted per packet, if more
    than 50 laps are completed 2 packets will be transmitted so they can be merged for full lap
    positions history."""

    _fields_ = [
        ("header", PacketHeader),  # Header
        ("num_laps", ct.c_uint8),  # Number of laps in the data (including current partial lap)
        ("lap_start", ct.c_uint8),  # Index of the lap where the data starts, 0 indexed
        ("position_for_vehicle_idx", (ct.c_uint8 * _NUM_CARS) * 50),  # Array holding the position of the car in a given lap, 0 if no record.
    ]
#----------------------------------------------------------------------------


# ---Car Telemetry 2 Packet -----------------------------------------------------------
class CarTelemetry2Data(_Struct):
    """This packet details additional telemetry for all the cars in the race, as initial telemetry
    was getting to large.
    """

    _fields_ = [
        ("active_aero_mode", ct.c_uint8),  # 0 = Corner Mode, 1 = Straight Mode
        ("active_aero_available", ct.c_uint8),  # 0 = Unavailable, 1 = Available
        ("active_aero_activation_distance", ct.c_uint16),  # 0 = Active aero not available, non-zero - Active aero will be available in [X] metres
        ("overtake_available", ct.c_uint8),  # 0 = not available, 1 = available
        ("overtake_active", ct.c_uint8),  # 0 = not active, 1 = active
        ("overtake_activation_distance", ct.c_uint16),  # 0 = Overtake not available, non-zero - Overtake will be available in [X] metres
        ("regulations_2026", ct.c_uint8),  # 0 = vehicle conforms to pre-2026, 1 = 2026 regulations applicable
        ("driving_wrong_way", ct.c_uint8),  # Wheter the car is driving the wrong way
    ]


class PacketCarTelemetry2Data(_Struct):
    """car_telemetry_2 packet, which holds additional telemetry for all cars in the session."""

    _fields_ = [
        ("header", PacketHeader),  # Header
        ("car_telemetry_2_data", CarTelemetry2Data * _NUM_CARS),  # Additional telemetry data for all cars on track
    ]

    def __repr__(self) -> str:
        return (f"{type(self).__name__}(format={self.header.packet_format}, "
                f"frame={self.header.frame_identifier}, cars={_NUM_CARS})")
#----------------------------------------------------------------------------