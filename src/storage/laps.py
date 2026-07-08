"""LapStore - persists the player's laps, their per-lap tyre context, and their dense traces.

Repository-per-aggregate sibling of SessionStore/SeasonStore: it owns the ``laps`` table and the
Parquet trace files together. A lap's timing + tyre context are DB rows; its dense LapTrace is a
Parquet file (see ``trace_files``) named ``<session_uid>/lap_<n>.parquet`` under ``trace_dir``.

Laps are managed by ``session_uid`` explicitly (no FK to ``sessions``): ``save_laps`` is a full
replace for that uid - deleting the old rows AND their trace files before writing the new set - and
``delete`` removes both. ``trace_dir`` is injectable so tests point it at a temp dir and a future
``data_root()`` can route it to a per-user location when the app is packaged.
"""
from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ..domain.models import CarDamage, Lap, LapTyreContext
from .migrations import ensure_schema
from .schema import Base, LapRow
from .trace_files import read_trace, write_trace

_DEFAULT_URL = "sqlite:///f1league.db"


class LapStore:
    """A SQLite + Parquet store for the player's laps and their dense traces."""

    def __init__(self, url: str = _DEFAULT_URL, trace_dir: str = "lap_traces",
                 echo: bool = False) -> None:
        self._engine = create_engine(url, echo=echo)
        Base.metadata.create_all(self._engine)  # new tables (incl. laps)
        ensure_schema(self._engine)             # additive columns on existing tables
        self._Session = sessionmaker(bind=self._engine)
        self._trace_dir = Path(trace_dir)

    # --- Lifecycle ---------------------------------------------------
    def close(self) -> None:
        """Dispose the engine and its pooled connections. Safe to call more than once."""
        self._engine.dispose()

    def __enter__(self) -> "LapStore":
        return self
    
    def __exit__(self, *exc) -> None:
        self.close()

    # --- write -----------------------------------------------------------------
    def save_laps(self, session_uid: str, laps: tuple[Lap, ...]) -> None:
        """Persists a session's laps, replacing any previously stored for the same uid.
        
        Removes the old rows and their Parquet files first, so a re-ingest that produced fewer
        laps doesn't leave orphans behind. 
        """
        uid = str(session_uid)
        session_dir = self._trace_dir / uid
        if session_dir.exists():
            shutil.rmtree(session_dir)                  # drop stale trace files for this uid
        with self._Session.begin() as db:
            for row in db.scalars(select(LapRow).where(LapRow.session_uid == uid)):
                db.delete(row)                            # drop stale DB rows for this uid
            db.flush()
            for lap in laps:
                trace_rel = None
                if lap.trace is not None:
                    session_dir.mkdir(parents=True, exist_ok=True)
                    trace_rel = f"{uid}/lap_{lap.lap_number}.parquet"
                    write_trace(str(self._trace_dir / trace_rel), lap.trace)
                db.add(self._to_row(uid, lap, trace_rel))

    def delete(self, session_uid: str) -> None:
        """Delete a session's laps (rows + trace files). Returns how many lap rows were removed."""
        uid = str(session_uid)
        session_dir = self._trace_dir / uid
        if session_dir.exists():
            shutil.rmtree(session_dir)                  # drop trace files for this uid
        with self._Session.begin() as db:
            rows = db.scalars(select(LapRow).where(LapRow.session_uid == uid)).all()
            for row in rows:
                db.delete(row)                            # drop DB rows for this uid
            return len(rows)
        
    # --- read -----------------------------------------------------------------
    def load_laps(self, session_uid: str) -> tuple[Lap, ...]:
        """Reconstructs a session's laps (with traces + tyre context), ordered by lap numbner."""
        with self._Session.begin() as db:
            rows = db.scalars(
                select(LapRow).
                where(LapRow.session_uid == str(session_uid))
                .order_by(LapRow.lap_number)).all()
            return tuple(self._to_domain(row) for row in rows)
        
    def list(self, session_uid: str) -> tuple[Lap, ...]:
        """A session's laps WITHOUT their dense traces, ordered by lap number.
        
        The cheap listing for the lap overview: reads only the DB rows (timing + tyre context "
        damage), never the Parquet trace files, so browsing a session's laps costs one query.
        Each returned lap has ``trace=None``; call ``load``to hydrate a single lap's trace.
        """
        with self._Session.begin() as db:
            rows = db.scalars(
                select(LapRow)
                .where(LapRow.session_uid == str(session_uid))
                .order_by(LapRow.lap_number)).all()
            return tuple(self._to_domain(row, with_trace=False) for row in rows)
        
    def load(self, session_uid: str, lap_number: int) -> Lap | None:
        """One fully-hydrated lap (timing + tyre context + damage + its dense trace), or None.
        
        The detail page loads a single lap this way rather than a whole session's traces, and the
        iteration-2 overlay loads its N laps by calling this once per selected laps - so no path
        reads every Parquet file in a session just to show one.
        """
        with self._Session.begin() as db:
            row = db.scalar(
                select(LapRow).where(
                    LapRow.session_uid == str(session_uid),
                    LapRow.lap_number == lap_number))
            return self._to_domain(row, with_trace=True) if row else None
        
    # --- domain <-> row conversion --------------------------------------------
    @staticmethod
    def _to_row(session_uid: str, lap: Lap, trace_rel: str | None) -> LapRow:
        tc = lap.tyre_context
        return LapRow(
            session_uid=session_uid,
            lap_number=lap.lap_number,
            lap_time_ms=lap.lap_time_ms,
            sector1_ms=lap.sector1_ms,
            sector2_ms=lap.sector2_ms,
            sector3_ms=lap.sector3_ms,
            is_valid=lap.is_valid,
            trace_path=trace_rel,
            tyre_actual_compound=tc.actual_compound if tc else None,
            tyre_visual_compound=tc.visual_compound if tc else None,
            tyre_age_laps=tc.age_laps if tc else None,
            tyre_wear=list(tc.wear) if tc else None,
            tyre_damage=list(tc.damage) if tc else None,
            tyre_blisters=list(tc.blisters) if tc else None,
            damage=dataclasses.asdict(lap.damage) if lap.damage else None,
        )
    
    def _to_domain(self, row: LapRow, with_trace: bool = True) -> Lap:
        tyre_context = None
        if row.tyre_actual_compound is not None:
            tyre_context = LapTyreContext(
                actual_compound=row.tyre_actual_compound,
                visual_compound=row.tyre_visual_compound,
                age_laps=row.tyre_age_laps,
                wear=tuple(row.tyre_wear or (0.0, 0.0, 0.0, 0.0)),
                damage=tuple(row.tyre_damage or (0, 0, 0, 0)),
                blisters=tuple(row.tyre_blisters or (0, 0, 0, 0)),
            )
        damage = None
        if row.damage is not None:
            damage = CarDamage(**{**row.damage, "brakes": tuple(row.damage["brakes"])})
        trace = None
        if with_trace and row.trace_path:
            trace = read_trace(str(self._trace_dir / row.trace_path))
        return Lap(
            lap_number=row.lap_number,
            lap_time_ms=row.lap_time_ms,
            sector1_ms=row.sector1_ms,
            sector2_ms=row.sector2_ms,
            sector3_ms=row.sector3_ms,
            is_valid=row.is_valid,
            trace=trace,
            tyre_context=tyre_context,
            damage=damage,
        )

