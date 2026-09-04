"""Which roster names a session on the Sessions surface (E1c).

Each rule here is one of the sub-points the E1c decision pins down (DECISIONS -> UI), and the fakes
assert one of them outright: ``_RosterFiles.seed`` and ``roster_for`` raise on sight, because
seeding hydrates every session in the season and must never run while a list is being painted.

The fixture is this database's own case - *Mittwoch League* is a **GRAND_PRIX** season, because 2026
leagues run in multiplayer GP lobbies where League Racing has no DLC cars - which is why the mode
test is ``ROSTER_SEASON_MODES`` and not ``mode == LEAGUE``.
"""
import json
import unittest

from f1telemetry.src.domain.roster import LeagueMember, LeagueRoster
from f1telemetry.src.domain.season import Season, SeasonMode
from f1telemetry.src.ui.sessions.league_names import SessionRosters

_ROSTER = LeagueRoster(members=(
    LeagueMember(name="Roli", race_number=24, online_names=("RoliMei",)),
))
_OTHER_ROSTER = LeagueRoster(members=(
    LeagueMember(name="Kevin", race_number=50, online_names=("soundscape93",)),
))


def _season(season_id: int, mode: SeasonMode) -> Season:
    return Season(mode=mode, number=1, game_format=2026, season_id=season_id)


class _Seasons:
    """The two ``SeasonStore`` reads the provider makes, counted so caching can be asserted."""

    def __init__(self, assigned: dict, seasons: dict):
        self._assigned = assigned
        self._seasons = seasons
        self.assigned_calls = 0

    def assigned_seasons(self) -> dict:
        self.assigned_calls += 1
        return dict(self._assigned)

    def get_season(self, season_id):
        return self._seasons.get(season_id)


class _RosterFiles:
    """``SeasonRosterFiles``' saved-file read. The seeding paths fail the test if they are called."""

    def __init__(self, saved=None, error=None):
        self._saved = saved or {}
        self._error = error
        self.load_calls = 0

    def load(self, season_id):
        self.load_calls += 1
        if self._error is not None:
            raise self._error
        return self._saved.get(season_id)

    def seed(self, *args, **kwargs):
        raise AssertionError("seed hydrates every session in the season - E1c forbids it here")

    def roster_for(self, *args, **kwargs):
        raise AssertionError("roster_for falls back to seeding - E1c forbids it here")


def _provider(mode=SeasonMode.GRAND_PRIX, saved=None, error=None, assigned=None):
    seasons = _Seasons(assigned if assigned is not None else {900: 1}, {1: _season(1, mode)})
    files = _RosterFiles(saved={1: _ROSTER} if saved is None else saved, error=error)
    return SessionRosters(seasons, files), seasons, files


class RosterModeTests(unittest.TestCase):
    """Which season modes hand their roster to the Sessions surface."""

    def test_a_grand_prix_season_resolves_its_saved_roster(self):
        """The case a ``mode == LEAGUE`` gate silently drops - and this database's only real league."""
        provider, _, _ = _provider(mode=SeasonMode.GRAND_PRIX)
        self.assertIs(provider.roster_for_session(900), _ROSTER)

    def test_a_league_season_resolves_its_saved_roster(self):
        provider, _, _ = _provider(mode=SeasonMode.LEAGUE)
        self.assertIs(provider.roster_for_session(900), _ROSTER)

    def test_my_team_never_resolves_a_roster(self):
        """A solo mode races fixed-identity AI; a roster there would rename cars it does not own."""
        provider, _, files = _provider(mode=SeasonMode.MY_TEAM)
        self.assertIsNone(provider.roster_for_session(900))
        self.assertEqual(files.load_calls, 0, "a solo season's roster file is never even read")

    def test_driver_career_never_resolves_a_roster(self):
        provider, _, _ = _provider(mode=SeasonMode.DRIVER_CAREER)
        self.assertIsNone(provider.roster_for_session(900))


class NoRosterTests(unittest.TestCase):
    """The four ways this answers None, all of which leave the captured name exactly as it is."""

    def test_an_unassigned_session_has_no_roster(self):
        """Nothing links it to a league, so there is no roster to be right about."""
        provider, _, files = _provider(assigned={})
        self.assertIsNone(provider.roster_for_session(900))
        self.assertEqual(files.load_calls, 0)

    def test_a_roster_mode_season_with_no_saved_file_reads_as_it_does_today(self):
        """The knowingly accepted cost of not seeding: it degrades to today, never to worse."""
        provider, _, _ = _provider(saved={})
        self.assertIsNone(provider.roster_for_session(900))

    def test_an_assignment_to_a_season_that_is_gone_has_no_roster(self):
        seasons = _Seasons({900: 42}, {})            # assignments carry no FK to seasons
        provider = SessionRosters(seasons, _RosterFiles())
        self.assertIsNone(provider.roster_for_session(900))

    def test_a_malformed_roster_file_degrades_instead_of_raising(self):
        """This runs per card while a list is painted: a modal per row is the worse failure."""
        for error in (json.JSONDecodeError("bad", "{", 0), OSError("gone")):
            with self.subTest(error=type(error).__name__):
                provider, _, _ = _provider(error=error)
                self.assertIsNone(provider.roster_for_session(900))


class ReadingTests(unittest.TestCase):
    """What it reads, how often, and when it reads again."""

    def test_the_saved_file_is_read_and_nothing_is_seeded(self):
        """``_RosterFiles`` raises from seed/roster_for, so reaching them fails rather than hangs."""
        provider, _, files = _provider()
        provider.roster_for_session(900)
        self.assertEqual(files.load_calls, 1)

    def test_a_uid_resolves_the_same_as_a_string_and_an_int(self):
        """Session uids travel through this surface's signals as ``str`` - they are uint64."""
        provider, _, _ = _provider(assigned={15048156050429837240: 1})
        self.assertIs(provider.roster_for_session("15048156050429837240"), _ROSTER)
        self.assertIs(provider.roster_for_session(15048156050429837240), _ROSTER)

    def test_one_paint_reads_the_assignments_once_and_each_roster_once(self):
        """The whole point of the bulk read: a 40-card list is one query, not one per card."""
        provider, seasons, files = _provider(assigned={900: 1, 901: 1, 902: 1})
        for uid in (900, 901, 902):
            self.assertIs(provider.roster_for_session(uid), _ROSTER)
        self.assertEqual((seasons.assigned_calls, files.load_calls), (1, 1))

    def test_a_season_with_no_file_is_not_re_read_per_card(self):
        """The None answer is cached too, or an empty roster costs a stat call per row."""
        provider, _, files = _provider(saved={}, assigned={900: 1, 901: 1})
        provider.roster_for_session(900)
        provider.roster_for_session(901)
        self.assertEqual(files.load_calls, 1)

    def test_invalidate_re_reads_the_assignments_and_the_files(self):
        """Assigning a session on the Seasons surface must show here on the next paint."""
        provider, seasons, files = _provider()
        provider.roster_for_session(900)
        provider.invalidate()
        provider.roster_for_session(900)
        self.assertEqual((seasons.assigned_calls, files.load_calls), (2, 2))

    def test_two_seasons_keep_their_own_rosters(self):
        seasons = _Seasons({900: 1, 901: 2},
                           {1: _season(1, SeasonMode.LEAGUE), 2: _season(2, SeasonMode.GRAND_PRIX)})
        provider = SessionRosters(seasons, _RosterFiles(saved={1: _ROSTER, 2: _OTHER_ROSTER}))
        self.assertIs(provider.roster_for_session(900), _ROSTER)
        self.assertIs(provider.roster_for_session(901), _OTHER_ROSTER)


if __name__ == "__main__":
    unittest.main()
