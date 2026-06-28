"""SessionStore - persists and retrieves SessionResults (Classification only).
Other storage classes will be added in the future Milestones.

Converts between the domain dataclasses and the SQLAlchemy rows in ``schema.py``.
A save is a full replace fo that session_uid (idempotent re-saves), and a load
reconstructs a SessionResults with its classification populated; laps/setups etc. 
stay empty until its added in the future.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ..domain.models import (
    Classification,
    ClassificationEntry,
    SessionResult,
    TyreStint,
)
from ..protocol.enums import (
    Formula,
    ResultReason,
    ResultStatus,
    SessionType,
    Weather,
    safe_enum
)

from .schema import Base, ClassificationEntryRow, SessionRow

_DEFAULT_URL = "sqlite:///f1league.db"


class SessionStore:
    """A SQLite-backed store for session classifications and metadata.
    This is a temporary solution until we have a proper database backend (Postgres, MySQL)."""
    def __init__(self, url: str = _DEFAULT_URL, echo: bool = False) -> None:
        self._engine = create_engine(url, echo=echo)
        Base.metadata.create_all(self._engine)
        self._Session = sessionmaker(self._engine)

    # --- lifecycle -----------------------------------------------------------
    def close(self) -> None:
        """Dispose the engine and close its pooled connections.

        Safe to call more than once. Prefer the context-manager form
        ``(with SessionStore(...) as store: ...``) where possible."""
        self._engine.dispose()

    def __enter__(self) -> "SessionStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- write --------------------------------------------------------------
    def save(self, result:SessionResult) -> None:
        """Persists a session, replacing any existing record with the same session_uid."""
        with self._Session.begin() as db:
            existing = db.get(SessionRow, str(result.session_uid))
            if existing is not None:
                db.delete(existing)                 # cascade removes its entries
                db.flush()                          # flush to avoid unique constraint violation
            db.add(self._to_row(result))

    # --- read ---------------------------------------------------------------
    def load(self, session_uid:int) -> SessionResult | None:
        """Reconstruct a stored SessionResult, or None if it isn't present."""
        with self._Session.begin() as db:
            row = db.get(SessionRow, str(session_uid))
            return self._to_domain(row) if row is not None else None
        
    def list_sessions(self) -> list[SessionResult]:
        """List every stored session, most recently recorded first."""
        with self._Session.begin() as db:
            rows = db.scalars(
                select(SessionRow).order_by(SessionRow.recorded_at.desc())).all()
            return [self._to_domain(row) for row in rows]
        
    # --- domain <-> row conversion -----------------------------------------------
    @staticmethod
    def _to_row(result: SessionResult) -> SessionRow:
        entries: list[ClassificationEntryRow] = []
        if result.classification is not None:
            for entry in result.classification.entries:
                entries.append(
                    ClassificationEntryRow(
                        vehicle_index=entry.vehicle_index,
                        position=entry.position,
                        driver_name=entry.driver_name,
                        team_id=entry.team_id,
                        is_player=entry.is_player,
                        grid_position=entry.grid_position,
                        points=entry.points,
                        num_laps=entry.num_laps,
                        num_pit_stops=entry.num_pit_stops,
                        best_lap_time_ms=entry.best_lap_time_ms,
                        total_race_time_s=entry.total_race_time_s,
                        penalties_time_s=entry.penalties_time_s,
                        num_penalties=entry.num_penalties,
                        result_status=int(entry.result_status),
                        result_reason=int(entry.result_reason),
                        tyre_stints=[
                            {
                                "actual": tyres.actual_compound,
                                "visual": tyres.visual_compound,
                                "end_lap": tyres.end_lap,
                            } 
                            for tyres in entry.tyre_stints
                        ],
                    )
                )
        return SessionRow(
            session_uid=str(result.session_uid),
            season_link_id=result.season_link_id,
            weekend_link_id=result.weekend_link_id,
            session_link_id=result.session_link_id,
            game_format=result.game_format,
            track_id=result.track_id,
            session_type=int(result.session_type),
            formula=int(result.formula),
            weather=int(result.weather),
            total_laps=result.total_laps,
            player_vehicle_index=result.player_vehicle_index,
            recorded_at=result.recorded_at or datetime.now(timezone.utc),
            entries=entries,
        )
    
    @staticmethod
    def _to_domain(row: SessionRow) -> SessionResult:
        entries = tuple(
            ClassificationEntry(
                vehicle_index=rows.vehicle_index,
                position=rows.position,
                driver_name=rows.driver_name,
                team_id=rows.team_id,
                is_player=rows.is_player,
                grid_position=rows.grid_position,
                points=rows.points,
                num_laps=rows.num_laps,
                num_pit_stops=rows.num_pit_stops,
                best_lap_time_ms=rows.best_lap_time_ms,
                total_race_time_s=rows.total_race_time_s,
                penalties_time_s=rows.penalties_time_s,
                num_penalties=rows.num_penalties,
                result_status=safe_enum(ResultStatus, rows.result_status),
                result_reason=safe_enum(ResultReason, rows.result_reason),
                tyre_stints=tuple(
                    TyreStint(
                        actual_compound=tyres["actual"],
                        visual_compound=tyres["visual"],
                        end_lap=tyres["end_lap"]
                    )
                    for tyres in rows.tyre_stints
                ),
            ) 
            for rows in sorted(row.entries, key=lambda e: e.position)
        )
        classification = Classification(entries=entries) if entries else None
        return SessionResult(
            session_uid=int(row.session_uid),
            season_link_id=row.season_link_id,
            weekend_link_id=row.weekend_link_id,
            session_link_id=row.session_link_id,
            game_format=row.game_format,
            track_id=row.track_id,
            session_type=safe_enum(SessionType, row.session_type),
            formula=safe_enum(Formula, row.formula),
            weather=safe_enum(Weather, row.weather),
            total_laps=row.total_laps,
            player_vehicle_index=row.player_vehicle_index,
            classification=classification,
            recorded_at=row.recorded_at,
        )
        


