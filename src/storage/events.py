"""EventStore - persists the Event packets a session produced: penalties and on-track passes.

Repository-per-aggregate sibling of ``LapStore``, and it copies that contract exactly: events are
managed by ``session_uid`` with **no foreign key** to ``sessions`` (core invariant #4), ``save_events``
is a full replace for one uid, and ``delete`` removes the lot. So the delete / tombstone / restore
paths need the same one-line additions ``lap_store`` already has, and nothing new is invented.

Both codes share one table with a ``code`` discriminator (DECISIONS -> Storage); see
``schema.SessionEventRow`` for why one table rather than two, and TELEMETRY_NOTES -> "Event packets"
for the measurements the shape was settled against.

The two readers are separate on purpose. The penalties box and the overtakes readout are different
surfaces with different appetites - a session holds a handful of penalties and up to 562 passes - so
neither pays for the other. There is deliberately **no count method**: the ``+N / -M`` a view shows
must be a ``len()`` over the rows that view already holds, or the header and the list beside it can
disagree.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from ..domain.models import SessionOvertake, SessionPenalty
from .engine import create_db_engine
from .migrations import ensure_schema
from .schema import Base, SessionEventRow

_DEFAULT_URL = "sqlite:///f1leaque.db"

# The Event packet's own string codes, stored verbatim as the row discriminator (Invariant #9's
# spirit: keep the game's raw value, interpret on read). The allow-list is there two and nothing else.
_PENALTY_CODE = "PENA"
_OVERTAKE_CODE = "OVTK"


class EventStore:
    """A SQLite store for a session's Event-packet events."""

    def __init__(self, url: str = _DEFAULT_URL, echo: bool = False) -> None:
        self._engine = create_db_engine(url, echo=echo)
        Base.metadata.create_all(self._engine)              # new tables (incl. session_events)
        ensure_schema(self._engine)                         # additive columns on existing tables
        self._Session = sessionmaker(bind=self._engine)

    # --- lifecycle ---------------------------------------------------------------------------
    def close(self) -> None:
        """Dispose the engine and its pooled connections. Safe to call more than once."""
        self._engine.dispose()

    def __enter__(self) -> "EventStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- write -----------------------------------------------------------------------------------
    def save_events(self, session_uid: str, penalties: tuple[SessionPenalty, ...] = (), 
                    overtakes: tuple[SessionOvertake, ...] = ()) -> None:
        """Persist a session's events, replacing any previously stored for the same uid.

        Both codes are replaced together because they are one aggregate: a re-ingest that produced
        fewer events - or none at all, which is what an old capture re-read by a build that filters
        harder would give - must not leave the surplus behind. Call it even with two empty tuples
        for exactly that reason; the delete half is the point.
        """
        uid = str(session_uid)
        with self._Session.begin() as db:
            for row in db.scalars(select(SessionEventRow).where(SessionEventRow.session_uid == uid)):
                db.delete(row)                  # drop stale rows for this uid
            db.flush()
            for penalty in penalties:
                db.add(self._penalty_to_row(uid, penalty))
            for overtake in overtakes:
                db.add(self._overtake_to_row(uid, overtake))

    def delete(self, session_uid: str) -> int:
        """Delete a session's events. Return how many rows were removed, both codes togehter."""
        uid = str(session_uid)
        with self._Session.begin() as db:
            rows = db.scalars(
                select(SessionEventRow).where(SessionEventRow.session_uid == uid)).all()
            for row in rows:
                db.delete(row)
            return len(rows)

    # --- read ------------------------------------------------------------------------------------
    def load_penalties(self, session_uid: str) -> tuple[SessionPenalty, ...]:
        """A session's penalties, every car's, ordered by lap then by frame.

        That order is the assembler's (``_build_penalties``) and the domain model's documented one,
        so it is re-stated here rather than inherited from insertion order: the store guarantees the
        contract whatever wrote the rows. Replay-recovered rows carry frame 0 and sort first within
        their lap, which is the only ordering they can offer.
        """
        with self._Session.begin() as db:
            rows = db.scalars(
                select(SessionEventRow)
                .where(SessionEventRow.session_uid == str(session_uid),
                       SessionEventRow.code == _PENALTY_CODE)
                .order_by(SessionEventRow.lap_number, SessionEventRow.frame,
                          SessionEventRow.id)).all()
            return tuple(self._to_penalty(row) for row in rows)

    def load_overtakes(self, session_uid: str) -> tuple[SessionOvertake, ...]:
        """A session's passes, every car's, in the order the game announced them.

        Arrival order is the only order this data has - two passes can share a frame, and a pass is
        not "greater" than another - so the row id, which is insertion order, is the sort key.
        """
        with self._Session.begin() as db:
            rows = db.scalars(
                select(SessionEventRow)
                .where(SessionEventRow.session_uid == str(session_uid),
                          SessionEventRow.code == _OVERTAKE_CODE)
                .order_by(SessionEventRow.id)).all()
            return tuple(self._to_overtake(row) for row in rows)

    # --- domain <-> row conversion ----------------------------------------------------------------
    @staticmethod
    def _penalty_to_row(session_uid: str, penalty: SessionPenalty) -> SessionEventRow:
        return SessionEventRow(
            session_uid=session_uid,
            code=_PENALTY_CODE,
            session_time_s=penalty.session_time_s,
            frame=penalty.frame,
            lap_number=penalty.lap_number,
            vehicle_index=penalty.vehicle_index,
            other_vehicle_index=penalty.other_vehicle_index,
            detail={
                "penalty_type": penalty.penalty_type,
                "infringement_type": penalty.infringement_type,
                "time_s": penalty.time_s,
                "places_gained": penalty.places_gained,
            },
        )

    @staticmethod
    def _overtake_to_row(session_uid: str, overtake: SessionOvertake) -> SessionEventRow:
        return SessionEventRow(
            session_uid=session_uid,
            code=_OVERTAKE_CODE,
            session_time_s=overtake.session_time_s,
            frame=overtake.frame,
            lap_number=overtake.lap_number,
            vehicle_index=overtake.overtaking_vehicle_index,
            other_vehicle_index=overtake.overtaken_vehicle_index,
            detail={},
        )

    @staticmethod
    def _to_penalty(row: SessionEventRow) -> SessionPenalty:
        """Rebuild a penalty. ``get`` on every optional field, because None is a real answer.

        A missing key and a stored ``None`` must both read as "not applicable" - and neither may
        become 0, which on ``places_gained`` means "gained no places" and is a different fact.
        """
        detail = row.detail or {}
        return SessionPenalty(
            vehicle_index=row.vehicle_index,
            penalty_type=detail.get("penalty_type", 0),
            infringement_type=detail.get("infringement_type", 0),
            lap_number=row.lap_number,
            other_vehicle_index=row.other_vehicle_index,
            time_s=detail.get("time_s"),
            places_gained=detail.get("places_gained"),
            session_time_s=row.session_time_s,
            frame=row.frame,
        )

    @staticmethod
    def _to_overtake(row: SessionEventRow) -> SessionOvertake:
        return SessionOvertake(
            overtaking_vehicle_index=row.vehicle_index,
            overtaken_vehicle_index=row.other_vehicle_index,
            lap_number=row.lap_number,
            session_time_s=row.session_time_s,
            frame=row.frame,
        )
                