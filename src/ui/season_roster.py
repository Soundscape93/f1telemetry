"""UI-side helpers for per-season league roster files.

The domain roster module owns parsing/validation and pure roster operations. This helper owns
the application convention around where roster files live and how a season gets its canonical
JSON file.

Rendering a season is read-only: :meth:`SeasonRosterFiles.roster_for` loads the saved file if
one exists, otherwise it seeds a roster from captures (and any previous league season) *in
memory* without touching disk. Writing the canonical JSON is always an explicit action -
:meth:`create_from_captures` materializes the seed so it can be hand-edited, and
:meth:`import_csv` converts a user-picked CSV. So merely viewing a season never creates a file.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from ..domain.roster import (
    LeagueRoster,
    load_roster,
    load_roster_csv,
    merge_rosters,
    roster_from_rounds,
    save_roster,
)
from ..domain.season import RoundResults, Season, SeasonMode

# A lazy source of all seasons: only invoked when a roster actually needs seeding, so the common
# "file already exists" render path does not pay for a seasons query.
SeasonsSource = Callable[[], Iterable[Season]]


class SeasonRosterFiles:
    """Manage canonical per-season roster JSON files for LEAGUE seasons."""

    def __init__(self, root: str | Path = "rosters") -> None:
        self._root = Path(root)

    def path_for(self, season_id: int | None) -> Path:
        """Return the canonical roster JSON path for a saved season."""
        if season_id is None:
            raise ValueError("season must be saved before it can have a roster")
        return self._root / f"season_{season_id}.json"

    def has_roster(self, season_id: int | None) -> bool:
        """Whether this season already has a saved canonical roster file."""
        return self.path_for(season_id).exists()

    def load(self, season_id: int | None) -> LeagueRoster | None:
        """Load a season's saved roster, or None if it has no roster file yet."""
        path = self.path_for(season_id)
        return load_roster(path) if path.exists() else None

    def seed(
        self,
        season: Season,
        rounds: Iterable[RoundResults],
        all_seasons: SeasonsSource,
    ) -> LeagueRoster:
        """Compute a roster from captures (merged over a previous league season) in memory.

        Does not write to disk - this is what a read-only view shows before a file exists.
        """
        seeded = roster_from_rounds(rounds)
        previous = self._previous_roster(season, all_seasons)
        return merge_rosters(previous, seeded) if previous is not None else seeded

    def roster_for(
        self,
        season: Season,
        rounds: Iterable[RoundResults],
        all_seasons: SeasonsSource,
    ) -> LeagueRoster:
        """The roster to display: the saved file if present, otherwise an in-memory seed.

        Read-only - viewing a season never writes a file.
        """
        loaded = self.load(season.season_id)
        return loaded if loaded is not None else self.seed(season, rounds, all_seasons)

    def create_from_captures(
        self,
        season: Season,
        rounds: Iterable[RoundResults],
        all_seasons: SeasonsSource,
    ) -> LeagueRoster:
        """Materialize the capture-seeded roster as canonical JSON so it can be hand-edited."""
        roster = self.seed(season, rounds, all_seasons)
        save_roster(self.path_for(season.season_id), roster)
        return roster

    def import_csv(self, season_id: int | None, csv_path: str | Path) -> LeagueRoster:
        """Import a user-selected CSV and write the canonical season JSON."""
        roster = load_roster_csv(csv_path)
        save_roster(self.path_for(season_id), roster)
        return roster

    def _previous_roster(
        self,
        season: Season,
        all_seasons: SeasonsSource,
    ) -> LeagueRoster | None:
        """Load the most recent previous LEAGUE season roster, if one exists."""
        candidates = [
            candidate
            for candidate in all_seasons()
            if candidate.mode == SeasonMode.LEAGUE
            and candidate.season_id != season.season_id
            and candidate.number < season.number
            and self.path_for(candidate.season_id).exists()
        ]
        if not candidates:
            return None

        previous = max(candidates, key=lambda s: (s.number, s.season_id or 0))
        return load_roster(self.path_for(previous.season_id))
