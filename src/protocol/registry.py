"""Maps (packet_format, packet_id) to the wire-struct class that decodes is.

The registry is used by the parser to dispatch to the right struct for each packet, and by the normalizer to know which struct to decode into for each packet.

Registering with PacketId members keeps the table readable; lookups use the raw int form the header.
"""
from __future__ import annotations

from .enums import PacketId
from .v2025.structs import (
    PacketMotionData,
    PacketSessionData,
    PacketLapData,
    PacketEventData,
    PacketParticipantsData,
    PacketCarSetupData,
    PacketCarTelemetryData,
    PacketCarStatusData,
    PacketFinalClassificationData,
    PacketLobbyInfoData,
    PacketCarDamageData,
    PacketSessionHistoryData,
    PacketTyreSetsData,
    PacketMotionExData,
    PacketTimeTrialData,
    PacketLapPositionsData,
)

from .v2026.structs import (
    PacketMotionData as PacketMotionData_2026,
    PacketSessionData as PacketSessionData_2026,
    PacketLapData as PacketLapData_2026,
    PacketEventData as PacketEventData_2026,
    PacketParticipantsData as PacketParticipantsData_2026,
    PacketCarSetupData as PacketCarSetupData_2026,
    PacketCarTelemetryData as PacketCarTelemetryData_2026,
    PacketCarStatusData as PacketCarStatusData_2026,
    PacketFinalClassificationData as PacketFinalClassificationData_2026,
    PacketLobbyInfoData as PacketLobbyInfoData_2026,
    PacketCarDamageData as PacketCarDamageData_2026,
    PacketSessionHistoryData as PacketSessionHistoryData_2026,
    PacketTyreSetsData as PacketTyreSetsData_2026,
    PacketMotionExData as PacketMotionExData_2026,
    PacketTimeTrialData as PacketTimeTrialData_2026,
    PacketLapPositionsData as PacketLapPositionsData_2026,
    PacketCarTelemetry2Data as PacketCarTelemetry2Data_2026,
)

class PacketRegistry:
    """Lookup from (packet_format, packet_id) to a wire-struct class."""

    def __init__(self) -> None:
        self._map: dict[tuple[int, int], type] = {}

    def register(self, packet_format: int, packet_id: PacketId, struct_class: type) -> None:
        """Register a struct class for a (packet_format, packet_id) pair."""
        key = (packet_format, packet_id)
        if key in self._map:
            raise ValueError(
                f"Duplicate registration for key {key}: "
                f"{self._map[key].__name__} vs {struct_class.__name__}"
            )
        self._map[key] = struct_class

    def get(self, packet_format: int, packet_id: int) -> type | None:
        """Get the struct class for a (packet_format, packet_id) pair, or None if not found."""
        return self._map.get((packet_format, packet_id))
    

_PACKETS_2025 = [
    (PacketId.MOTION, PacketMotionData),
    (PacketId.SESSION, PacketSessionData),
    (PacketId.LAP_DATA, PacketLapData),
    (PacketId.EVENT, PacketEventData),
    (PacketId.PARTICIPANTS, PacketParticipantsData),
    (PacketId.CAR_SETUPS, PacketCarSetupData),
    (PacketId.CAR_TELEMETRY, PacketCarTelemetryData),
    (PacketId.CAR_STATUS, PacketCarStatusData),
    (PacketId.FINAL_CLASSIFICATION, PacketFinalClassificationData),
    (PacketId.LOBBY_INFO, PacketLobbyInfoData),
    (PacketId.CAR_DAMAGE, PacketCarDamageData),
    (PacketId.SESSION_HISTORY, PacketSessionHistoryData),
    (PacketId.TYRE_SETS, PacketTyreSetsData),
    (PacketId.MOTION_EX, PacketMotionExData),
    (PacketId.TIME_TRIAL, PacketTimeTrialData),
    (PacketId.LAP_POSITIONS, PacketLapPositionsData),
]

_PACKETS_2026 = [
    (PacketId.MOTION, PacketMotionData_2026),
    (PacketId.SESSION, PacketSessionData_2026),
    (PacketId.LAP_DATA, PacketLapData_2026),
    (PacketId.EVENT, PacketEventData_2026),
    (PacketId.PARTICIPANTS, PacketParticipantsData_2026),
    (PacketId.CAR_SETUPS, PacketCarSetupData_2026),
    (PacketId.CAR_TELEMETRY, PacketCarTelemetryData_2026),
    (PacketId.CAR_STATUS, PacketCarStatusData_2026),
    (PacketId.FINAL_CLASSIFICATION, PacketFinalClassificationData_2026),
    (PacketId.LOBBY_INFO, PacketLobbyInfoData_2026),
    (PacketId.CAR_DAMAGE, PacketCarDamageData_2026),
    (PacketId.SESSION_HISTORY, PacketSessionHistoryData_2026),
    (PacketId.TYRE_SETS, PacketTyreSetsData_2026),
    (PacketId.MOTION_EX, PacketMotionExData_2026),
    (PacketId.TIME_TRIAL, PacketTimeTrialData_2026),
    (PacketId.LAP_POSITIONS, PacketLapPositionsData_2026),
    (PacketId.CAR_TELEMETRY_2, PacketCarTelemetry2Data_2026),
]



def build_registry() -> PacketRegistry:
    """Construct the registry with every packet for every supported format."""
    registry = PacketRegistry()
    for packet_id, struct_class in _PACKETS_2025:
        registry.register(2025, packet_id, struct_class)

    for packet_id, struct_class in _PACKETS_2026:
        registry.register(2026, packet_id, struct_class)
    
    return registry



 

