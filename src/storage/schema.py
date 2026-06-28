"""SQLAlchemy repository definitions for the league storage layer.

These ORM rows are the *persistence* representation, deliberately decoupled from the
domain dataclasses in ``domain/models.py``. The repository converts between them, so the
domain layer stays free of any SQLAlchemy dependencies.

Scope is a classification + session metadata that labels it. Laps, traces and setups
are not persited yet, but will be added in the future.
In the future, we may also add a more complete database backend (Postgres, MySQL) and
this SQLite implementation will be replaced with a more robust solution.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, JSON, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SessionRow(Base):
    """One captured session's metadata and hierarchy keys."""

    __tablename__ = "sessions"

    # uint64 identity, stored as text to avoid SQLite's integer size limit (overflows at 2^63-1)
    session_uid: Mapped[str] = mapped_column(String, primary_key=True)

    # Season -> Weekend -> Session hierarchy key (uint32)
    season_link_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    weekend_link_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    session_link_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    game_format: Mapped[int]        # 2025 / 2026 etc..
    track_id: Mapped[int]            # see reference in ``f1telemetry/src/protocol/reference.py``
    session_type: Mapped[int]       # raw enum value -> safe_enum on load
    formula: Mapped[int]              # raw enum value -> safe_enum on load
    weather: Mapped[int]             # raw enum value -> safe_enum on load
    total_laps: Mapped[int]           # total laps in the session
    player_vehicle_index: Mapped[int]  # index of the player's vehicle in the participants list
    recorded_at: Mapped[datetime | None] = mapped_column(nullable=True)  # timestamp of when the session was recorded

    entries: Mapped[list[ClassificationEntryRow]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ClassificationEntryRow.position",)
    

class ClassificationEntryRow(Base):
    """One car's final-classification result within a session."""

    __tablename__ = "classification_entries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_uid: Mapped[str] = mapped_column(ForeignKey("sessions.session_uid"), nullable=False)

    vehicle_index: Mapped[int]  # index of the vehicle in the session's participants list
    position: Mapped[int]       # final position in the session (1-based)
    driver_name: Mapped[str]    # denormalized so a card renders self-contained
    team_id: Mapped[int]
    is_player: Mapped[bool]
    grid_position: Mapped[int]
    points: Mapped[int]
    num_laps: Mapped[int]
    num_pit_stops: Mapped[int]
    best_lap_time_ms: Mapped[int]
    total_race_time_s: Mapped[int]
    penalties_time_s: Mapped[int]
    num_penalties: Mapped[int]
    result_status: Mapped[int]  # raw enum value -> safe_enum on load
    result_reason: Mapped[int]  # raw enum value -> safe_enum on load
    tyre_stints: Mapped[list] = mapped_column(JSON)  # list of tyre stint dicts, denormalized for simplicity

    session: Mapped[SessionRow] = relationship(back_populates="entries")