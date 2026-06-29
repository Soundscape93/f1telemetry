"""Official 'All Tracks' calendars, per game format, as ordered track IDs.

Track IDs follow the spec's Track IDs appendix. The 2026 calendar swaps Imola (27) for
Madrid (42) and reorders several rounds relative to 2025. A season is pinned to one format,
so its 'All Tracks' presets comes from here; 'Custom' calendars are built by the user instead.
"""

from __future__ import annotations

from .season import SeasonRound

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


def official_calendar(game_format: int) -> tuple[SeasonRound, ...]:
    """Return the official 'All Tracks' calendar for the given game format, as a tuple of
    SeasonRound objects. Raises ValueError if the game format is unknown."""
    tracks = _OFFICIAL_TRACK_ORDER.get(game_format)
    if tracks is None:
        raise ValueError(f"no official calendar for game format {game_format}")
    return tuple(
        SeasonRound(round_number=i, track_id=track_id) for i, track_id in enumerate(tracks, start=1)
    )
