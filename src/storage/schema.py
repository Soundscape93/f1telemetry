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

from sqlalchemy import BigInteger, ForeignKey, JSON, String, text
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
    # AI difficulty rating (0..110) from the Session packet; 0 means "not captured" - either stored before PIPELINE_VERSION 3 or a session with no AI.
    ai_difficulty: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    # ordered session-type ints for the whole weekend; distinguishes Sprint Race from Race
    # (both report session_type 15). Additive column - [] for rows saved before it existed.
    weekend_structure: Mapped[list] = mapped_column(JSON, default=list, server_default=text("'[]'"))
    # every distinct condition the session reported, raw enum ints in the first-seen order (E14).
    # weather above stays the end-of-session snapshot and this is an additional fact. Additive
    # column - [] for rows saved before it existed, which reads as "not captured", not "one
    # condition", so a stale row never claims a session was mixed or wasn't.
    weather_seen: Mapped[list] = mapped_column(JSON, default=list, server_default=text("'[]'"))
    # static track geometry (metres) from the Session packet; None for pre-feature rows.
    track_length_m: Mapped[int | None] = mapped_column(nullable=True)
    sector2_start_m: Mapped[float | None] = mapped_column(nullable=True)
    sector3_start_m: Mapped[float | None] = mapped_column(nullable=True)
    # ordered garage-setup snapshots for the player; JSON list of {from_lap, setup{...}}.
    # Additive column - [] for rows saved before setup history existed.
    setup_history: Mapped[list] = mapped_column(JSON, default=list, server_default=text("'[]'"))
    recorded_at: Mapped[datetime | None] = mapped_column(nullable=True)  # timestamp of when the session was recorded
    # True when the classification was synthesized from telemetry (no Final Classification packet).
    # Additive column - 0 for rows saved before it existed (ensure_schema ALTERs it in on startup).
    is_reconstructed: Mapped[bool] = mapped_column(default=False, server_default=text("0"))

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
    # server_default so ensure_schema's ADD COLUMN can back-fill existing rows (a NOT NULL
    # column added to a populated table needs a SQL-level default, not just a Python one).
    nationality_id: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    is_player: Mapped[bool]
    grid_position: Mapped[int]
    points: Mapped[int]
    num_laps: Mapped[int]
    num_pit_stops: Mapped[int]
    best_lap_time_ms: Mapped[int]
    # server_default so ensure_schema's ADD COLUMN back-fills existing rows (see nationality_id)
    best_lap_num: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    total_race_time_s: Mapped[int]
    penalties_time_s: Mapped[int]
    num_penalties: Mapped[int]
    result_status: Mapped[int]  # raw enum value -> safe_enum on load
    result_reason: Mapped[int]  # raw enum value -> safe_enum on load
    tyre_stints: Mapped[list] = mapped_column(JSON)  # list of tyre stint dicts, denormalized for simplicity
    # AI vs human, from Participants Packet. server_default to ensure_schema's ADD COLUMN, back-fills existing rows
    is_ai: Mapped[bool] = mapped_column(default=False, server_default=text("0"))

    session: Mapped[SessionRow] = relationship(back_populates="entries")


class LapRow(Base):
    """One of the player's completed laps: timing, per-lap tyre context, and a Parquet trace ref.
    
    Deliberately NOT a foreign key to ``sessions``(mirrors ``season_assignments``): the LapStore
    manages labs by ``session_uid``explicitly - replace-by-uid on a re-save, delete-by-uid on
    session delete - so a lap persistence never depends on cross-store cascade behaviour. The dense
    ~5400-sample trace lives in a Parquet file at ``trace_path``(relative to the store's trace
    dir), never in the database. Tyte context is lap-boundary snapshot: compound/age from Car
    Status, cumulative wear % from Car Damage (RL, RR, FL, FR). The lap-context columns are read
    from Lap-Data over the lap's own timed run and from the Session packet's race-control state.
    """

    __tablename__ = "laps"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_uid: Mapped[str] = mapped_column(String, index=True, nullable=False)
    lap_number: Mapped[int]
    lap_time_ms: Mapped[int | None] = mapped_column(nullable=True)
    sector1_ms: Mapped[int | None] = mapped_column(nullable=True)
    sector2_ms: Mapped[int | None] = mapped_column(nullable=True)
    sector3_ms: Mapped[int | None] = mapped_column(nullable=True)
    is_valid: Mapped[bool]
    trace_path: Mapped[str | None] = mapped_column(String, nullable=True)  # Parquet , relative to trace dir
    tyre_actual_compound: Mapped[int | None] = mapped_column(nullable=True)
    tyre_visual_compound: Mapped[int | None] = mapped_column(nullable=True)
    tyre_age_laps: Mapped[int | None] = mapped_column(nullable=True)
    tyre_wear: Mapped[list | None] = mapped_column(JSON, nullable=True)      # per-wheel wear %, RL,RR,FL,FR
    tyre_damage: Mapped[list | None] = mapped_column(JSON, nullable=True)    # per-wheel tyre damage %
    tyre_blisters: Mapped[list | None] = mapped_column(JSON, nullable=True)  # per-wheel blister %
    tyre_surface_temp: Mapped[list | None] = mapped_column(JSON, nullable=True)  # per-wheel tyre surface temp °C
    tyre_carcass_temp: Mapped[list | None] = mapped_column(JSON, nullable=True)  # per-wheel tyre inner/carcass temp °C
    damage: Mapped[dict | None] = mapped_column(JSON, nullable=True)         # non-tyre CarDamage snapshot
    fuel_in_tank: Mapped[float | None] = mapped_column(nullable=True)        # kg in tank at lap start
    # Lap context (PIPELINE_VERSION 4): what Lap Data and the Session packet said about this lap.
    # Additive-nullable like every column before them - a lap stored earlier reads them back as
    # None, which is what tells the charts to fall back to inference (see domain Lap.has_lap_context).
    driver_status: Mapped[int | None] = mapped_column(nullable=True)        # raw DriverStatus
    pit_status: Mapped[int | None] = mapped_column(nullable=True)           # raw PitStatus, peak
    preceded_by_garage: Mapped[bool | None] = mapped_column(nullable=True)  # garage before this lap
    is_out_lap: Mapped[bool | None] = mapped_column(nullable=True)          # began in the pit lane
    is_in_lap: Mapped[bool | None] = mapped_column(nullable=True)           # ended entering the pits
    safety_car: Mapped[int | None] = mapped_column(nullable=True)           # raw SafetyCarStatus
    red_flagged: Mapped[bool | None] = mapped_column(nullable=True)         # a red flag began here


class SessionEventRow(Base):
    """One Event-packet event kept from a session: a penalty, or a pass between two racing cars.

    **One table with a ``code`` discriminator, not one per code** (DECISIONS -> Storage). Penalties
    alone (129 rows across 73 captured sessions) would have fitted a JSON column on the session row
    the way ``setup_history`` does; overtakes would not - ~84 filtered rows a session, 562 in the
    worst - and splitting one aggregate across two shapes would double the read paths. So the
    columns here are what both codes share and ``detail`` carries the code-specific remainder, which
    makes adding ``COLL`` later a matter of rows rather than a migration.

    Deliberately NOT a foreign key to ``sessions`` (mirrors ``laps`` and ``season_assignments``):
    the EventStore manages events by ``session_uid`` explicitly - replace-by-uid on a re-save,
    delete-by-uid on a session delete - so nothing here depends on cross-store cascade behaviour
    (core invariant #4).

    ``vehicle_index`` is the car the event is *about*: the penalised car for ``PENA``, the
    overtaking car for ``OVTK``. ``other_vehicle_index`` is the second car when there is one - the
    car involved in the infringement (the wire's 255 "not applicable" sentinel becomes NULL, 79 of
    127 measured penalties) or the car that was passed.
    """

    __tablename__ = "session_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_uid: Mapped[str] = mapped_column(String, index=True, nullable=False)
    code: Mapped[str] = mapped_column(String)               # the Event packet's 4-char code: "PENA" or "OVTK"
    session_time_s: Mapped[float]                           # header session_time, seconds into the session
    frame: Mapped[int]                                      # header frame_identifier; 0 for a replay-only penalty
    lap_number: Mapped[int]                                 # PENA: the packet's own lap_num. OVTK: the passing car's
    vehicle_index: Mapped[int]                              # penalisez car / overtaking car
    other_vehicle_index: Mapped[int | None] = mapped_column(nullable=True)  # other car; Null when n/a
    # The code-specific remainder: penalty_type / infringement_type / time_s / places_gained for
    # PENA, and {} for OVTK, which has nothing left over. Keys are written even when their value is
    # None, because on a penalty "not applicable" and 0 are different answers (places_gained is
    # legitimately 0 in 73 of 127 measured rows).
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


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


class CaptureRow(Base):
    """One capture file: its identity, where it lives, and what it holds.
    
    Keyed on the sha256 of the *decompressed* payload, so re-archiving a capture under a new
    codec (gzip -> zstd) updates the row rather than creating a second one, and importing the
    same recording twice from a shared league folder is a no-op. ``path`` is advisory: files get
    moved and copied between machines, and the hash - not the location - is the identity.
    """
    
    __tablename__ = "captures"

    content_hash: Mapped[str] = mapped_column(String, primary_key=True)  # sha256 of the decompressed payload; the identity
    path: Mapped[str] = mapped_column(String)
    file_name: Mapped[str] = mapped_column(String, index=True)  # indexed: folder-scan pre-filter
    file_size: Mapped[int] = mapped_column(BigInteger)
    payload_size: Mapped[int] = mapped_column(BigInteger)
    codec: Mapped[str] = mapped_column(String)
    packet_count: Mapped[int] = mapped_column(BigInteger)
    recorded_by: Mapped[str | None] = mapped_column(String, nullable=True)  # which user/member produced it; None = unknown/self
    ingested_at: Mapped[datetime | None] = mapped_column(nullable=True)
    first_packet_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_packet_at: Mapped[datetime | None] = mapped_column(nullable=True)

    sessions: Mapped[list["CaptureSessionRow"]] = relationship(
        back_populates="capture", cascade="all, delete-orphan")


class CaptureSessionRow(Base):
    """Which sessions a capture contains: the session_uid -> capture lookup.
    
    A child table rather than a JSON list on ``captures`` because the useful direction is
    *uid -> capture* ("which file do I re-ingest to back-fill this session?", ROADMAP ->
    Packaging), and JSON can't be joined or indexed. ``session_uid`` is deliberately NOT a
    foreign key to ``sessions`` {mirrors ``season_assignments`` and ``laps``}: it records what
    the *file* holds, which stays true whether or not that session is currently stored -
    including sessions ingest skipped as tombstoned.
    """

    __tablename__ = "capture_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    content_hash: Mapped[str] = mapped_column(ForeignKey("captures.content_hash"), index=True)
    session_uid: Mapped[str] = mapped_column(String, index=True)

    capture: Mapped[CaptureRow] = relationship(back_populates="sessions")

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


class MetaRow(Base):
    """One key/value of app-level state that belong to no aggregate.
    
    Today it holds exactly one key, ``pipeline_version``: the ``PIPELINE_VERSION`` the stored
    derived data was produced by, compared against this build's on start-up to offer a guieded
    re-ingest (docs/PACKAGING.md -> "DB migration & pipeline-version").

    A table rather than SQLite's ``PRAGMA user_version`` for twor reasons: the schema is kept
    engine-agnostic (a PRAGMA is not), and a *new table* needs no migration at all -
    ``create_all`` creates it, the ``deleted_sessions`` / ``captures``precedent. Values are TEXT
    so the table stays generic; the store parses the one integer key it owns.
    """
    
    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String)