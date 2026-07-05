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
    game_mode: Mapped[int]            # raw mode id -> reference.game_mode_name; buckets sessions into mode-based windows
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
    race_number: Mapped[int] = mapped_column(default=0)  # denormalized so a card renders self-contained
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


class DeletedSessionRow(Base):
    """A tombstone for a session deleted from the store.

    Re-ingesting a capture re-assembles every session it contains, which would silently
    resurrect ones the user deleted on purpose (an aborted/crashed attempt they repeated).
    A tombstone records that a ``session_uid`` is unwanted so ingest skips it. Keyed on the
    uid - the ``sessions`` row is gone, so this is deliberately not a foreign key - and it
    carries a few descriptive fields so a future 'deleted sessions' view can show what each
    tombstone was without the capture. Cleared by ``SessionStore.restore``.
    """

    __tablename__ = "deleted_sessions"

    session_uid: Mapped[str] = mapped_column(String, primary_key=True)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    track_id: Mapped[int | None] = mapped_column(nullable=True)
    session_type: Mapped[int | None] = mapped_column(nullable=True)
    recorded_at: Mapped[datetime | None] = mapped_column(nullable=True)


class SeasonRow(Base):
    """A user-authored season: mode, number, optional nickname, pinned game format."""

    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    mode: Mapped[int]           # SeasonMode value
    number: Mapped[int]
    game_format: Mapped[int]
    nickname: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime | None] = mapped_column(default=None)

    rounds: Mapped[list["SeasonRoundRow"]] = relationship(
        back_populates="season",
        cascade="all, delete-orphan",
        order_by="SeasonRoundRow.round_number",
    )
    assignments: Mapped[list["SeasonAssignmentRow"]] = relationship(
        back_populates="season",
        cascade="all, delete-orphan",
    )


class SeasonRoundRow(Base):
    """One round of a season's calendar."""

    __tablename__ = "season_rounds"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id")) 
    round_number: Mapped[int]
    track_id: Mapped[int]

    season: Mapped[SeasonRow] = relationship(back_populates="rounds")


class SeasonAssignmentRow(Base):
    """Places a captured session into a season's round.
    
    ``session_uid``references a session by its uid but is deliberately NOT a foreign key to
    ``sessions``: re-ingesting a capture replaces that session's row, and a FK would cascade
    the delete and wipe the manual assignemnt. It cascades with its *season* instead.
    """

    __tablename__ = "season_assignments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"))
    round_number: Mapped[int]
    session_uid: Mapped[str]  = mapped_column(String, unique=True)  # FK to sessions intentionally omitted, see class docstring

    season: Mapped[SeasonRow] = relationship(back_populates="assignments")