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


# --- editing an existing calendar ------------------------------------------------------------
#
# A calendar can be re-authored after the season exists, but a round that already has a session
# assigned to it is frozen: it keeps BOTH its round_number and its track_id. Assignments are keyed
# on (season_id, round_number) and deliberately carry no FK to the rounds table (invariant #4), so
# moving such a round would silently re-file a stored result under a different track, and dropping
# one would orphan it - invisible in the UI, but still in the database and ready to reappear if the
# calendar ever grew back.
#
# The rule collapses to a positional check: for each locked round (n, t), the proposed calendar
# must still have a round n whose track is t. That covers reordering, inserting before, deleting
# before and truncating without treating them as separate cases - and it correctly permits an edit
# that happens to leave a locked round exactly where it was.

CONFLICT_REMOVED = "removed"        # the proposed calendar has no round with that number
CONFLICT_RETRACKED = "retracked"    # that round number now points at a different track

@dataclass(frozen=True)
class CalendarConflict:
    """One assigned round that a proposed calendar would invalidate."""

    round_number: int
    track_id: int
    reason: str
    proposed_track_id: int | None = None  # only set for CONFLICT_RETRACKED


class CalendarConflictError(ValueError):
    """A calendar edit was refused because it would invalidate assigned rounds.

    Carries the conflicts themselves so a caller can render them however it likes; the message is
    the plain-language version, for logs and for callers that just want a string.
    """

    def __init__(self, conflicts) -> None:
        self.conflicts: tuple[CalendarConflict, ...] = tuple(conflicts)
        super().__init__(describe_conflicts(self.conflicts))


def locked_rounds(rounds, assigned_round_numbers) -> tuple[SeasonRound, ...]:
    """The rounds of ``rounds`` that already hold an assigned session, in round order."""
    assigned = set(assigned_round_numbers)
    return tuple(
        sorted((r for r in rounds if r.round_number in assigned), key=lambda r: r.round_number)
    )


def calendar_conflicts(proposed, locked) -> tuple[CalendarConflict, ...]:
    """Which ``locked`` rounds the ``proposed`` calendar would break. Empty tuple means it's safe."""
    by_number = {r.round_number: r.track_id for r in proposed}
    conflicts = []
    for round in locked:
        proposed_track = by_number.get(round.round_number)
        if proposed_track is None:
            conflicts.append(
                CalendarConflict(
                    round.round_number, round.track_id,CONFLICT_REMOVED)
            )
        elif proposed_track != round.track_id:
            conflicts.append(
                CalendarConflict(
                    round.round_number, round.track_id, CONFLICT_RETRACKED, proposed_track)
            )
    return tuple(conflicts)


def describe_conflicts(conflicts) -> str:
    """One line per conflict, naming the round and what the edit would have done to it."""
    lines = []
    for conflict in conflicts:
        where = f"Round {conflict.round_number} ({track_name(conflict.track_id)})"
        if conflict.reason == CONFLICT_REMOVED:
            lines.append(f"{where} would be removed from the calendar.")
        else:
            lines.append(
                f"{where} would become {track_name(conflict.proposed_track_id)}."
            )
    return "\n".join(lines)
