"""Official 'All Tracks' calendars and the rules for authoring a custom one.

Track IDs follow the spec's Track IDs appendix. The 2026 calendar swaps Imola (27) for
Madrid (42) and reorders several rounds relative to 2025. A season is pinned to one format,
so its 'All Tracks' preset comes from here.

A *custom* calendar is authored by the user, but the game constrains how - and the constraint
depends on the (season) mode, not just the format:

- Career / My Team run a fixed sequence: you pick a *subset* of the official calendar of size
  exactly 10, 16, or 24, but the relative order is frozen (Abu Dhabi is always last, Madrid can
  never be first). No reordering, no duplicates.
- Grand Prix (solo) and League (multiplayer) are a sandbox: any number of tracks, freely
  reordered, and the same track may appear more than once. Grand Prix caps at 28; League has no
  confirmed cap and is left open-ended.

`calendar_rules(mode, game_format)` returns those constraints as a value object so the UI can
drive a single picker widget from them. Deriving the rules from `SeasonMode` does not violate
season.py's "SeasonMode is decoupled from the game's game_mode" note: that note is about the
granular per-session `game_mode` id, whereas the four season modes map cleanly onto the four
calendar-authoring behaviours.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from ..protocol.reference import TRACK_NAMES, track_name
from .season import SeasonMode, SeasonRound

_OFFICIAL_TRACK_ORDER: dict[int, tuple[int, ...]] = {
    # Melbourne, Shangai, Suzuka, Sakhir, Jeddah, Miami, Imola, Monaco, Catalunya, Montreal,
    # Austria, Silverstone, Spa, Hungaroring, Zandvoort, Monza, Baku, Singapore, Texas,
    # Mexico, Brazil, Las Vegas, Losail, Abu Dhabi
    2025: (0, 2, 13, 3, 29, 30, 27, 5, 4, 6, 17, 7, 10, 9, 26, 11, 20, 12, 15, 19, 16, 31, 32, 14),
    # Melbourne, Shangai, Suzuka, Sakhir, Jeddah, Miami, Montreal, Monaco, Catalunya, Austria,
    # Silverstone, Spa, Hungaroring, Zandvoort, Monza, Madrid, Baku, Singapore, Texas, Mexico,
    # Brazil, Las Vegas, Losail, Abu Dhabi
    2026: (0, 2, 13, 3, 29, 30, 6, 5, 4, 17, 7, 10, 9, 26, 11, 42, 20, 12, 15, 19, 16, 31, 32, 14),
}

# Tracks that don't exist in a given format's sandbox pool. Madrid (42) is a 2026 addition, so
# it isn't selectable in a 2025 season. Everything else in TRACK_NAMES (including Imola 27 and the
# reverse layouts 39/40/41) is offered in both formats.
_FORMAT_EXCLUDED_TRACKS: dict[int, frozenset[int]] = {
    2025: frozenset({42}),
    2026: frozenset(),
}

# Grand Prix (F1 World) caps a custom championship at 28 rounds; League (Racenet) has no
# confirmed cap and is left open-ended (None).
_GRAND_PRIX_MAX_ROUNDS = 28
_CAREER_LENGTHS = (10, 16, 24)


def calendar_from_track_ids(track_ids) -> tuple[SeasonRound, ...]:
    """Number an ordered iterable of track IDs into a calendar of `SeasonRound`s (1-based)."""
    return tuple(
        SeasonRound(round_number=i, track_id=track_id)
        for i, track_id in enumerate(track_ids, start=1)
    )


def official_calendar(game_format: int) -> tuple[SeasonRound, ...]:
    """Return the official 'All Tracks' calendar for the given game format, as a tuple of
    SeasonRound objects. Raises ValueError if the game format is unknown."""
    tracks = _OFFICIAL_TRACK_ORDER.get(game_format)
    if tracks is None:
        raise ValueError(f"no official calendar for game format {game_format}")
    return calendar_from_track_ids(tracks)


def selectable_tracks(game_format: int) -> tuple[int, ...]:
    """Return the sandbox pool for a format: every known track valid in that format, ordered by
    track name for findability. Raises ValueError if the game format is unknown."""
    if game_format not in _OFFICIAL_TRACK_ORDER:
        raise ValueError(f"no track pool for game format {game_format}")
    excluded = _FORMAT_EXCLUDED_TRACKS.get(game_format, frozenset())
    track_ids = [tid for tid in TRACK_NAMES if tid not in excluded]
    return tuple(sorted(track_ids, key=track_name))


class CalendarStyle(Enum):
    """How a season's calendar is authored."""

    PRESET_SUBSET = auto()  # pick a fixed-length subset of the official order (Career / My Team)
    SANDBOX = auto()        # freely add / order / repeat tracks (Grand Prix / League)


@dataclass(frozen=True)
class CalendarRules:
    """The constraints on authoring one season's calendar, derived from its mode and format.

    ``pool`` is the ordered set of selectable track IDs - the official order for a preset subset,
    or the format's sandbox pool otherwise. ``allowed_lengths`` pins the exact valid sizes for a
    preset subset (and is None for a sandbox); ``max_rounds`` is None when open-ended.
    """

    style: CalendarStyle
    pool: tuple[int, ...]
    allowed_lengths: tuple[int, ...] | None
    min_rounds: int
    max_rounds: int | None
    reorderable: bool
    allow_duplicates: bool


def calendar_rules(mode: SeasonMode, game_format: int) -> CalendarRules:
    """Return the calendar-authoring rules for a season of the given mode and format. Raises
    ValueError if the game format is unknown."""
    if game_format not in _OFFICIAL_TRACK_ORDER:
        raise ValueError(f"no calendar rules for game format {game_format}")
    if mode in (SeasonMode.MY_TEAM, SeasonMode.DRIVER_CAREER):
        return CalendarRules(
            style=CalendarStyle.PRESET_SUBSET,
            pool=_OFFICIAL_TRACK_ORDER[game_format],
            allowed_lengths=_CAREER_LENGTHS,
            min_rounds=min(_CAREER_LENGTHS),
            max_rounds=max(_CAREER_LENGTHS),
            reorderable=False,
            allow_duplicates=False,
        )
    # Grand Prix and League: sandbox. League is open-ended; Grand Prix caps at 28.
    max_rounds = None if mode is SeasonMode.LEAGUE else _GRAND_PRIX_MAX_ROUNDS
    return CalendarRules(
        style=CalendarStyle.SANDBOX,
        pool=selectable_tracks(game_format),
        allowed_lengths=None,
        min_rounds=1,
        max_rounds=max_rounds,
        reorderable=True,
        allow_duplicates=True,
    )
