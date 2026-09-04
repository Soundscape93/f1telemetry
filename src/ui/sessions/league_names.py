"""Which league roster names a session, for the Sessions surface - Qt-free, so the rule is
unit-testable the way ``race_control`` and ``lap_context`` are.

The Sessions surface shows the *captured* name, so a league member who raced with online-name
sharing turned off reads as ``Player``. The weekend page has always resolved that through a roster;
this gives Sessions the same answer without giving it the weekend page's cost.

**It decides the roster, not the name.** ``components.display_name_fn`` is already the one name
resolver in the app - the captured alias wins whenever it is not generic, and the roster is only a
fallback for ``""`` / ``"Player"`` - and ``display_name_fn(None)`` is exactly today's behaviour. So
this module answers "which roster, if any" and every call site wraps the answer in that existing
function. Two definitions of how a league name reads would be one too many, and ``components`` is
shared: it must not import from a surface.

**The saved file only, never a seed** (DECISIONS -> UI, E1c). ``SeasonRosterFiles.roster_for`` falls
back to seeding a roster from captures, and seeding needs ``rounds_with_results``, which hydrates
**every session in the season** - 37 in this database - and that must not run on the GUI thread
while a list is being painted. ``load`` reads one small JSON file and touches no sessions. What that
costs is stated rather than hidden: a roster-mode season whose file the user never created reads
exactly as it does today, and the fix is the "Create roster file" button the season detail page
already has.

**The mode test is ``ROSTER_SEASON_MODES``, not ``mode == LEAGUE``.** LEAGUE *and* GRAND_PRIX are
raced against other people; 2026 leagues run in multiplayer GP lobbies because League Racing has no
DLC cars, so a real league is commonly a GRAND_PRIX season. ``mode == LEAGUE`` would resolve nothing
for it.

**An unassigned session has no season, so it has no roster** - the right answer rather than a gap,
because nothing links it to a league.

**It never raises.** A hand-edited roster file can be malformed, and the seasons pages answer that
with a message box. This one is called once per card while a list is painted, where a modal per card
would be the worse failure - so an unreadable file degrades to the captured name, cached so it is
read once rather than once per row.
"""
from __future__ import annotations

from ...domain.roster import LeagueRoster
from ...domain.season import ROSTER_SEASON_MODES


class SessionRosters:
    """Resolves a session uid to the league roster that should name its drivers, and caches."""

    def __init__(self, season_store, roster_files):
        self._seasons = season_store
        self._files = roster_files
        self._assigned: dict[int, int] | None = None        # uid -> season_id: None: not read yet
        self._rosters: dict[int, LeagueRoster | None] = {}  # season_id -> roster or None if none applies

    def roster_for_session(self, session_uid) -> LeagueRoster | None:
        """The roster naming this session's drivers, or None to leave the captured names alone.

        None covers every case the surface treats identically: the session is unassigned, its season
        is a solo mode, its season has no saved roster file, or that file could not be read. Callers
        hand the result straight to ``display_name_fn``, whose None branch is today's behaviour, so
        no caller has to tell those cases apart.

        The uid is accepted as ``str`` or ``int``: it travels through the surface's signals as a
        string, because session uids are uint64 and a Qt ``int`` signal would overflow.
        """
        season_id = self._assignments().get(int(session_uid))
        if season_id is None:
            return None
        if season_id not in self._rosters:
            self._rosters[season_id] = self._load(season_id)
        return self._rosters[season_id]

    def invalidate(self) -> None:
        """Drop both caches, so the next request re-reads the assignemnts and the roster file.

        Called at the top of a page's ``reload``. Assigning a session on the Seasons surface and
        hand-editing a roster JSON both have to show up on the next paint, and neither sends this
        module a signal - so the cache is per-paint by design, which is also what keeps it right
        after an ingest.
        """
        self._assigned = None
        self._rosters.clear()

    def _assignments(self) -> dict[int, int]:
        """uid -> season_id for every assigned session; one query, read once per paint."""
        if self._assigned is None:
            self._assigned = self._seasons.assigned_seasons()
        return self._assigned

    def _load(self, season_id: int) -> LeagueRoster | None:
        """This season's saved roster, or None if it takes no roster or has none saved."""
        season = self._seasons.get_season(season_id)
        if season is None or season.mode not in ROSTER_SEASON_MODES:
            return None
        try:
            return self._files.load(season_id)
        except (OSError, ValueError):
            return None
