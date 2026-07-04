"""Shared, Qt-free presentation helpers for the seasons surface.

Small label formatters used across the seasons pages (overview, create, detail) so each page
renders a season the same way. Kept separate from any widget so they stay trivially reusable.
"""

from __future__ import annotations

from ...domain.season import SeasonMode

_MODE_LABELS = {
    SeasonMode.MY_TEAM: "My Team",
    SeasonMode.DRIVER_CAREER: "Driver Career",
    SeasonMode.GRAND_PRIX: "Grand Prix (Solo/Multiplayer)",
    SeasonMode.LEAGUE: "Multiplayer (League)",
}


def mode_label(mode) -> str:
    """Return a human-readable label for a SeasonMode, tolerant of enum renames."""
    return _MODE_LABELS.get(mode, mode.name)


def format_label(game_format: int) -> str:
    """Return a human-readable label for a game format number."""
    return {2025: "F1 25", 2026: "F1 26"}.get(game_format, f"F1 {game_format}")


def season_title(season) -> str:
    """Return a human-readable title for a season."""
    bits = [mode_label(season.mode), f"Season {season.number}"]
    if season.nickname:
        bits.append(f"“{season.nickname}”")
    return "   ·   ".join(bits)
