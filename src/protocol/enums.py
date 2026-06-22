"""Spec-defined enumerations from the F1 25 / F1 26 UDP appendices and packet comments.

Small, closed sets the app branches on or that carry domain meaning.
They are ``ÌntEnum`` so members compare equal to the raw ints the ctypes wire structs
prduce (e.g. ``ResultSTATUS.FINISHED == 3`` is True), and a dict keyed by these members can be looked
up with a raw int. `ÌntFlag` is used for bitfields, e.g. button presses.
"""
from __future__ import annotations

from enum import IntEnum, IntFlag
from typing import TypeVar

_E = TypeVar('_E', bound=IntEnum)


def safe_enum(enum_class: type[_E], value: int) -> _E | int:
    """Return the enum member for ``value``, or the raw int if it's unknown.
    
    Use fore every wire-int -> enum conversion in the normalizer. For closed sets the fallback
    never fires; for sets that grow accross version it lets a newer value pass thorugh instaed
    of crashing the parse.
    """
    try:
        return enum_class(value)
    except ValueError:
        return value


class PacketId(IntEnum):
    """header.m_packetId - used by the registry/parser for dispatch."""

    MOTION = 0
    SESSION = 1
    LAP_DATA = 2
    EVENT = 3
    PARTICIPANTS = 4
    CAR_SETUPS = 5
    CAR_TELEMETRY = 6
    CAR_STATUS = 7
    FINAL_CLASSIFICATION = 8
    LOBBY_INFO = 9
    CAR_DAMAGE = 10
    SESSION_HISTORY = 11
    TYRE_SETS = 12
    MOTION_EX = 13
    TIME_TRIAL = 14
    LAP_POSITIONS = 15
    CAR_TELEMETRY_2 = 16        # F1 26 only (Format 2026)


class SessionType(IntEnum):
    """Session types for a session, according to the F1 25 / F1 26 UDP appendices."""

    UNKNOWN = 0
    PRACTICE1 = 1
    PRACTICE2 = 2
    PRACTICE3 = 3
    SHORT_PRACTICE = 4
    QUALIFYING1 = 5
    QUALIFYING2 = 6
    QUALIFYING3 = 7
    SHORT_QUALIFYING = 8
    ONE_SHOT_QUALIFYING = 9
    SPRINT_SHOOTOUT1 = 10
    SPRINT_SHOOTOUT2 = 11
    SPRINT_SHOOTOUT3 = 12
    SHORT_SPRINT_SHOOTOUT = 13
    ONE_SHOT_SPRINT_SHOOTOUT = 14
    RACE = 15
    RACE2 = 16
    RACE3 = 17
    TIME_TRIAL = 18


class Formula(IntEnum):
    """session.m_formula - used by the registry/parser for dispatch."""

    F1_MODERN = 0
    F1_CLASSIC = 1
    F2 = 2
    F1_GENERIC = 3
    BETA = 4
    ESPORTS = 6
    F1_WORLD = 8
    F1_ELIMINATION = 9
    F1_26 = 13      # F1 26 only (Format 2026)


class Weather(IntEnum):
    """Weather types for a session - according to the F1 25 / F1 26 UDP appendices."""

    CLEAR = 0
    LIGHT_CLOUD = 1
    OVERCAST = 2
    LIGHT_RAIN = 3
    HEAVY_RAIN = 4
    STORM = 5


class SafetyCarStatus(IntEnum):
    """session.m_safetyCarStatus"""

    NONE = 0
    FULL = 1
    VIRTUAL = 2
    FORMATION_LAP = 3


class DriverStatus(IntEnum):
    """session.m_driverStatus"""

    IN_GARAGE = 0
    FLYING_LAP = 1
    IN_LAP = 2
    OUT_LAP = 3
    ON_TRACK = 4


class PitStatus(IntEnum):
    """session.m_pitStatus"""

    NONE = 0
    PITTING = 1
    IN_PIT_AREA = 2


class Sector(IntEnum):
    """session.m_sector"""

    SECTOR1 = 0
    SECTOR2 = 1
    SECTOR3 = 2


class ResultStatus(IntEnum):
    """session.m_resultStatus and final_classification.m_resultStatus."""
    INVALID = 0
    INACTIVE = 1
    ACTIVE = 2
    FINISHED = 3
    DID_NOT_FINISH = 4
    DISQUALIFIED = 5
    NOT_CLASSIFIED = 6
    RETIRED = 7


class ResultReason(IntEnum):
    """final_classification.m_resultReason and Retirement event reason (struct)."""
    INVALID = 0
    RETIRED = 1
    FINISHED = 2
    TERMINAL_DAMAGE = 3
    INACTIVE = 4
    NOT_ENOUGH_LAPS_COMPLETED = 5
    BLACK_FLAGGED = 6
    RED_FLAGGED = 7
    MECHANICAL_FAILURE = 8
    SESSION_SKIPPED = 9
    SESSION_SIMULATED = 10


class ErsDeployMode(IntEnum):
    """car_status.m_ersDeployMode. Value 3 is 'overtake' in 2025, renamed 'boost' in 2026."""

    NONE = 0
    MEDIUM = 1
    HOTLAP = 2
    OVERTAKE = 3
    BOOST = 3      # alias: 2026 name for the same value


class ActualTyreCompound(IntEnum):
    """car_status.m_actualTyreCompound."""

    # F1 Modern
    INTER = 7
    WET = 8
    C5 = 16
    C4 = 17
    C3 = 18
    C2 = 19
    C1 = 20
    C0 = 21
    C6 = 22

    # F1 Classic
    DRY = 9
    WET_CLASSIC = 10

    # F2
    SUPER_SOFT = 11
    SOFT = 12
    MEDIUM = 13
    HARD = 14
    WET_F2 = 15


class VisualTyreCompound(IntEnum):
    """car_status.m_visualTyreCompound."""

    # F1 Visual & Classic (can be different from actual compound)
    INTER = 7
    WET = 8
    SOFT = 16
    MEDIUM = 17
    HARD = 18

    # F2 '20
    WET_F2 = 15
    SUPER_SOFT = 19
    SOFT_F2 = 20
    MEDIUM_F2 = 21
    HARD_F2 = 22


class Surface(IntEnum):
    """car_telemetry.m_surfaceType — physics surface under each wheel."""

    TARMAC = 0
    RUMBLE_STRIP = 1
    CONCRETE = 2
    ROCK = 3
    GRAVEL = 4
    MUD = 5
    SAND = 6
    GRASS = 7
    WATER = 8
    COBBLESTONE = 9
    METAL = 10
    RIDGED = 11

class RuleSet(IntEnum):
    """session.m_ruleSet."""

    PRACTICE_AND_QUALIFYING = 0
    RACE = 1
    TIME_TRIAL = 2
    ELIMINATION = 12


class Button(IntFlag):
    """car_status.m_buttonStatus - bitfield of pressed buttons."""

    CROSS = 0x00000001
    TRIANGLE_Y = 0x00000002
    CIRCLE_B = 0x00000004
    SQUARE_X = 0x00000008
    D_PAD_LEFT = 0x00000010
    D_PAD_RIGHT = 0x00000020
    D_PAD_UP = 0x00000040
    D_PAD_DOWN = 0x00000080
    OPTIONS_MENU = 0x00000100
    L1_LB = 0x00000200
    R1_RB = 0x00000400
    L2_LT = 0x00000800
    R2_RT = 0x00001000
    LEFT_STICK_CLICK = 0x00002000
    RIGHT_STICK_CLICK = 0x00004000
    RIGHT_STICK_LEFT = 0x00008000
    RIGHT_STICK_RIGHT = 0x00010000
    RIGHT_STICK_UP = 0x00020000
    RIGHT_STICK_DOWN = 0x00040000
    SPECIAL = 0x00080000
    UDP_ACTION_1 = 0x00100000
    UDP_ACTION_2 = 0x00200000
    UDP_ACTION_3 = 0x00400000
    UDP_ACTION_4 = 0x00800000
    UDP_ACTION_5 = 0x01000000
    UDP_ACTION_6 = 0x02000000
    UDP_ACTION_7 = 0x04000000
    UDP_ACTION_8 = 0x08000000
    UDP_ACTION_9 = 0x10000000
    UDP_ACTION_10 = 0x20000000
    UDP_ACTION_11 = 0x40000000
    UDP_ACTION_12 = 0x80000000