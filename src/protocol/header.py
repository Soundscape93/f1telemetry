"""F1 telemetry packet header (shared across formats 2025 and 2026).
 
The header is byte-identical in both formats, so it is parsed generically: read
`packet_format` and `packet_id`, then dispatch to the right version-specific struct.
It nests as the first field of every packet struct.
"""
from __future__ import annotations

import ctypes as ct

from .base import _Struct


class PacketHeader(_Struct):
    _fields_ = [
        ("packet_format", ct.c_uint16),             # 2025 or 2026
        ("game_year", ct.c_uint8),                  # Game year of the data, e.g. 25 or 26
        ("game_major_version", ct.c_uint8),         # Major version of the game, - "X.00"
        ("game_minor_version", ct.c_uint8),         # Minor version of the game, - "1.XX"
        ("packet_version", ct.c_uint8),             # Version of this packet type, all start from 1
        ("packet_id", ct.c_uint8),                  # Identifier for the packet type, see enums.PacketId
        ("session_uid", ct.c_uint64),               # Unique identifier for the session
        ("session_time", ct.c_float),               # Session timestamp
        ("frame_identifier", ct.c_uint32),          # Identifier for the frame the data was retrieved on
        ("overall_frame_identifier", ct.c_uint32),  # Overall identifier for the frame the data was retrieved on,
                                                    # doesn't go back after flashbacks
        ("player_car_index", ct.c_uint8),           # Index of a players car in the array
        ("secondary_player_car_index", ct.c_uint8), # Index of the secondary player's car in the array (splitscreen)
                                                    # 255 if no second player
    ]