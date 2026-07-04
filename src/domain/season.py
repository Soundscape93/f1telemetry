"""Season-layer domain models - user-authored championship configuration.

Unlike everything else in the domain layer, these don't come out of a capture: a Season is something
the user creates, and captured sessions get assigned ont its round. ``SeasonMode``is the user's own
organizing categorazation, intentionally separate from the game's ``game_mode``(which is more granular
and doesn't map one-to-one - a league weekend reports as an online custom lobby, not "league").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum

from .models import SessionResult


class SeasonMode(IntEnum):
    """How the user organizes a season. Not the game's mode."""

    MY_TEAM = 0
    DRIVER_CAREER = 1
    GRAND_PRIX = 2
    LEAGUE = 3


@dataclass(frozen=True)
class SeasonRound:
    """One round in a season's calendar; an ordingal and the track it's run at."""

    round_number: int
    track_id: int


@dataclass(frozen=True)
class Season:
    """A user-authored championship: a mode, a number, an optional nichname, and an ordered
    calendar of rounds, pinned to one game format (the  'all tracks' calendar differs by
    format). ``season_id``is none unit the season has been persisted.
    """

    mode: SeasonMode
    number: int
    game_format: int
    nickname: str | None = None
    rounds: tuple[SeasonRound, ...] = ()
    season_id: int | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class RoundResults:
    """A round paired with the captured sessions assigned to it. Each session carries its own
    ``session_type`` (Q1, Q2, Q3, SQ1, SQ2, SQ3, Sprint, Race, ect...) and classification, so
    this is all the season view needs to render a weekend.
    """

    round_number: int
    track_id: int
    sessions: tuple[SessionResult, ...] = ()