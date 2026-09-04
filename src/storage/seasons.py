"""SeasonStore - persists user-authored seasons and the assignment of the captured sessions
to their rounds.

Seasons, their calendars, and assignments are mutable user configurations, so this store is
about create/update/delete, rather thane the idempotent replace the session store does. The
session <-> round link lives in its own table keyed by session uid (no FK to sessions), so a
re-ingested capture keeps its manual placement.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from ..domain.season import RoundResults, Season, SeasonMode, SeasonRound
from ..domain.calendars import CalendarConflictError, calendar_conflicts, locked_rounds
from .engine import create_db_engine
from .schema import Base, SeasonRoundRow, SeasonRow, SeasonAssignmentRow

_DEFAULT_URL = "sqlite:///f1league.db"


class SeasonStore:
    """A SQLite-backed store for seasons, calendars, and session assignments."""

    def __init__(self, url: str = _DEFAULT_URL, echo: bool = False) -> None:
        self._engine = create_db_engine(url, echo=echo)
        Base.metadata.create_all(self._engine)
        self._Session = sessionmaker(self._engine)

    # --- lifecycle -----------------------------------------------------------------
    def close(self) -> None:
        """Dispose the engine and close its pooled connetions.
        
        Save to call more than once. Prefer the context-manager form
        (``with SeasonStore(...) as store: ``) where possible."""
        self._engine.dispose()

    def __enter__(self) -> SeasonStore:
        return self
    
    def __exit__(self, *exc) -> None:
        self.close()


    # --- seasons -----------------------------------------------------------------

    def create_season(self, mode: SeasonMode, number: int, game_format: int,
                      nickname: str | None = None, 
                      rounds: tuple[SeasonRound, ...] = ()) -> Season:
        """Create a season (optionally with its calendar) and return it with its new id."""
        with self._Session.begin() as db:
            row = SeasonRow(
                mode=int(mode),
                number=number,
                game_format=game_format,
                nickname=nickname,
                created_at=datetime.now(timezone.utc),
                rounds=[SeasonRoundRow(round_number=r.round_number, track_id=r.track_id)
                        for r in rounds],
            )
            db.add(row)
            db.flush()
            return self._to_domain(row)
        
    def get_season(self, season_id: int) -> Season | None:
        """Return the season with the given id, or None if not found."""
        with self._Session() as db:
            row = db.get(SeasonRow, season_id)
            return self._to_domain(row) if row is not None else None
        
    def list_seasons(self) -> list[Season]:
        """Return all seasons, ordered by id."""
        with self._Session() as db:
            rows = db.scalars(select(SeasonRow).order_by(SeasonRow.id)).all()
            return [self._to_domain(r) for r in rows]
        
    def delete_season(self, season_id: int) -> None:
        """Delete a season; its rounds and assignments cascade away with it."""
        with self._Session.begin() as db:
            row = db.get(SeasonRow, season_id)
            if row is not None:
                db.delete(row)
        
    def set_calendar(self, season_id: int, rounds: tuple[SeasonRound, ...], *,
                     protect_assigned: bool = True) -> None:
        """Replace the calendar of a season with the given rounds.

        A round that already has a session assigned keeps **both** its ``round_number`` and its
        ``track_id`` (see ``domain/calendars`` for why the check is positional). Raises
        ``CalendarConflictError``, carrying every offending round, rather than writing a calendar
        that would re-file or orphan a stored result.

        The guard lives here rather than only in the editor UI so the invariant is *guaranteed*
        rather than merely remembered at one call site. ``protect_assigned=False`` is the escape
        hatch for a caller that has already dealt with the assignments itself; nothing in the app
        passes it today.
        """
        with self._Session.begin() as db:
            row = db.get(SeasonRow, season_id)
            if row is None:
                raise KeyError(f"no season {season_id}")
            if protect_assigned:
                assigned = db.scalars(
                    select(SeasonAssignmentRow.round_number)
                    .where(SeasonAssignmentRow.season_id == season_id)
                ).all()
                current = [SeasonRound(round_number=r.round_number, track_id=r.track_id)
                           for r in row.rounds]
                conflicts = calendar_conflicts(rounds, locked_rounds(current, assigned))
                if conflicts:
                    raise CalendarConflictError(conflicts)
            row.rounds = [SeasonRoundRow(round_number=r.round_number, track_id=r.track_id)
                          for r in rounds]
            
    # --- assignments -------------------------------------------------------------

    def assign_session(self, session_uid: int, season_id: int, round_number: int) -> None:
        """Place a captured session into a round. moving it if already assigned elsewhere."""
        with self._Session.begin() as db:
            season = db.get(SeasonRow, season_id)
            if season is None:
                raise KeyError(f"no season {season_id}")
            if round_number not in {r.round_number for r in season.rounds}:
                raise ValueError(f"season {season_id} has no round {round_number}")
            existing = db.scalar(
                select(SeasonAssignmentRow).where(
                    SeasonAssignmentRow.session_uid == str(session_uid)
                )
            )
            if existing is not None:
                existing.season_id = season_id
                existing.round_number = round_number
            else:
                db.add(SeasonAssignmentRow(
                    season_id=season_id, round_number=round_number,
                    session_uid=str(session_uid),
                ))

    def unassign_session(self, session_uid: int) -> None:
        """Remove a session from its assigned round, if any."""
        with self._Session.begin() as db:
            existing = db.scalar(
                select(SeasonAssignmentRow).where(
                    SeasonAssignmentRow.session_uid == str(session_uid)
                )
            )
            if existing is not None:
                db.delete(existing)

    def assignments_for_season(self, season_id: int) -> list[tuple[int, int]]:
        """(round_number, session_uid) pairs for a season, ordered by round."""
        with self._Session() as db:
            rows = db.scalars(
                select(SeasonAssignmentRow)
                .where(SeasonAssignmentRow.season_id == season_id)
                .order_by(SeasonAssignmentRow.round_number)
            ).all()
            return [(r.round_number, int(r.session_uid)) for r in rows]

    def assignment_for(self, session_uid: int) -> tuple[int, int] | None:
        """The ``(season_id, round_number)`` a session is placed in, or None if unassigned.
        
        The reverse of ``assignments_for_season``: that answers "what is in this season?", this
        answers "where does this session live?" - the question a delete guard, and any
        sessions-centric surface, has to ask. A session has at most one assignment
        (``assign_session`` moves rather than duplicates), so this is a single row.
        """
        with self._Session() as db:
            row = db.scalar(
                select(SeasonAssignmentRow).where(
                    SeasonAssignmentRow.session_uid == str(session_uid))
            )
            return None if row is None else (row.season_id, row.round_number)

    def assigned_uids(self) -> set[int]:
        """Every session uid placed in a round, across **all** seasons.
        
        The capture picker needs this rather than on season's assignments: a session assigned
        to another round - or another season entirely - must still be assigned when it turns
        up in a diffrent round's candidate list. That it did not is the bug this fixes.
        """
        with self._Session() as db:
            return {int(uid) for uid in
                    db.scalars(select(SeasonAssignmentRow.session_uid)).all()}

    def assigned_seasons(self) -> dict[int, int]:
        """Every assigned session uid mapped to the season it is placed in - one query.

        The bulk form of :meth:`assignment_for`, and the round number is dropped on purpose: the
        Sessions surface asks "whose roster names this session?" for a whole list at once, and
        calling ``assignment_for`` per card would be one query per row. ``assigned_uids`` cannot
        answer it either - it says which uids are placed, never whose they are.

        A session has at most one assignment (``assign_session`` moves rather than duplicates), so
        the uid keys cannot collide.
        """
        with self._Session() as db:
            rows = db.execute(
                select(SeasonAssignmentRow.session_uid, SeasonAssignmentRow.season_id)
            ).all()
            return {int(uid): season_id for uid, season_id in rows}
                        
    # --- combined read -----------------------------------------------------------------

    def rounds_with_results(self, season_id: int, session_store) -> list[RoundResults]:
        """Each round of the season paired with the SessionResults assigned to it.
        
        The sessions are loaded fro mthe given session store (which must point at the same
        database). Assignments whose session row is currently missing - e.g. mid-reingest -
        are simply skipped, not errored.
        """
        season = self.get_season(season_id)
        if season is None:
            raise KeyError(f"no season {season_id}")
        
        by_round: dict[int, list[int]] = {}
        for round_number, session_uid in self.assignments_for_season(season_id):
            by_round.setdefault(round_number, []).append(session_uid)

        results: list[RoundResults] = []
        for round in season.rounds:
            uids = by_round.get(round.round_number, [])
            loaded = [session_store.load(uid) for uid in uids]
            sessions = tuple(s for s in loaded if s is not None)
            results.append(RoundResults(round_number=round.round_number,
                                        track_id=round.track_id,sessions=sessions))
        return results
    
    # --- conversion -----------------------------------------------------------------

    @staticmethod
    def _to_domain(row: SeasonRow) -> Season:
        """Convert a SeasonRow to a domain Season object, including its rounds."""
        return Season(
            mode=SeasonMode(row.mode),
            number=row.number,
            game_format=row.game_format,
            nickname=row.nickname,
            rounds=tuple(
                SeasonRound(round_number=r.round_number, track_id=r.track_id)
                for r in sorted(row.rounds, key=lambda r: r.round_number)
            ),
            season_id=row.id,
            created_at=row.created_at,
        )