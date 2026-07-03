"""League roster - maps in-game driver identity to a league member.

A league weekend is an independent online lobby, a member's car index and shown name can
differ each time, and their name shows at all only if they set telemetry to public.
The stable anchors are the online name (when public) and the race number (a profile setting,
always visible). This hand-maintained roster lets standings resolve a captured entry to the
same member across weekends - online name first, race number as a fallback for anyone who
didn't make their telemetry public. The app's canonical roster is a JSON file, not a
database, so it adds no schema. CSV is supported as a user-friendly import format that is
validated and converted into that per-season JSON file.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .season import RoundResults

_GENERIC_SHOWN_NAMES = {"", "Player"}
_GENERIC_SHOWN_NAMES_CASEFOLD = {name.casefold() for name in _GENERIC_SHOWN_NAMES}


@dataclass(frozen=True)
class LeagueMember:
    """One league member: the canonical name shown in standings, their race number, and any
    online names they appear under in telemetry when their privacy is public."""

    name: str
    race_number: int
    online_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class LeagueRoster:
    members: tuple[LeagueMember, ...] = ()

    def member_for(self, entry) -> LeagueMember | None:
        """Return the roster member for an entry, or None if it is unknown."""
        shown_name = entry.driver_name
        for member in self.members:
            if shown_name in member.online_names:
                return member
        for member in self.members:
            if member.race_number == entry.race_number:
                return member
        return None

    def member_of(self, entry) -> str:
        """Resolve a classification entry to a member's canonical name.

        Online name first (exact match against any known online name), then race number. An
        entry matching neither is returned under its own shown name - an unknown driver still
        appears in standings, just unmatched.
        """
        member = self.member_for(entry)
        return member.name if member is not None else entry.driver_name

    def member_key(self, entry) -> int:
        """A stable grouping key for standings: the resolved member's race number, or the
        entry's own number when unmatched.

        Number-based (not name-based) so two roster-unknown humans who both show as ``"Player"``
        never collapse into one standings row - league race numbers are unique per driver. An
        entry matched by a drifting online name still groups under its member's number.
        """
        member = self.member_for(entry)
        return member.race_number if member is not None else entry.race_number


def league_display_name(entry, roster: LeagueRoster) -> str:
    """Display a league entry: public captured alias first, roster alias fallback if generic.

    Humans commonly appear as ``"Player"`` when online-name sharing is disabled. In that case
    the per-season roster gives us a useful fallback by race number. ``LeagueMember.name`` is
    only a human helper; the first ``online_names`` alias is the preferred roster display name.
    """
    shown_name = _clean_text(entry.driver_name)
    if not _is_generic_shown_name(shown_name):
        return shown_name
    member = roster.member_for(entry)
    if member is None:
        return shown_name
    return member.online_names[0] if member.online_names else member.name


def load_roster(path: str | Path) -> LeagueRoster:
    """Load a roster from canonical JSON."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return _roster_from_json_data(data)


def save_roster(path: str | Path, roster: LeagueRoster) -> None:
    """Write a roster as canonical per-season JSON."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "members": [
            {
                "name": member.name,
                "race_number": member.race_number,
                "online_names": list(member.online_names),
            }
            for member in roster.members
        ]
    }
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)


def load_roster_csv(path: str | Path) -> LeagueRoster:
    """Load a roster CSV import source.

    Required columns: name, race_number. Optional column: online_names, as semicolon-separated
    aliases. Header matching is case-insensitive and tolerates spaces/underscores. Extra
    columns are ignored.
    """
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("roster CSV has no header row")

        fields = {_normalize_header(name) for name in reader.fieldnames}
        missing = {"name", "race_number"} - fields
        if missing:
            raise ValueError(
                f"roster CSV missing required column(s): {', '.join(sorted(missing))}"
            )

        members = []
        for row in reader:
            normalized = {
                _normalize_header(key): value
                for key, value in row.items()
                if key is not None
            }
            members.append(
                {
                    "name": _clean_text(normalized.get("name")),
                    "race_number": normalized.get("race_number"),
                    "online_names": _split_online_names(normalized.get("online_names")),
                }
            )

    return _roster_from_json_data({"members": members})


def roster_from_rounds(rounds: Iterable[RoundResults]) -> LeagueRoster:
    """Seed a roster from captured classification names/numbers."""
    names_by_number: dict[int, set[str]] = {}

    for round_result in rounds:
        for session in round_result.sessions:
            if session.classification is None:
                continue
            for entry in session.classification.entries:
                names_by_number.setdefault(entry.race_number, set()).add(
                    entry.driver_name.strip()
                )

    members = []
    for number in sorted(names_by_number):
        aliases = sorted(
            name for name in names_by_number[number]
            if not _is_generic_shown_name(name)
        )
        members.append(
            {
                "name": aliases[0] if aliases else f"Driver {number}",
                "race_number": number,
                "online_names": aliases,
            }
        )

    return _roster_from_json_data({"members": members})


def merge_rosters(primary: LeagueRoster, fallback: LeagueRoster) -> LeagueRoster:
    """Keep primary member names, add fallback aliases/missing race numbers."""
    by_number: dict[int, LeagueMember] = {
        member.race_number: member
        for member in primary.members
    }

    for member in fallback.members:
        existing = by_number.get(member.race_number)
        if existing is None:
            by_number[member.race_number] = member
            continue

        aliases = tuple(dict.fromkeys(existing.online_names + member.online_names))
        by_number[member.race_number] = LeagueMember(
            name=existing.name,
            race_number=existing.race_number,
            online_names=aliases,
        )

    return LeagueRoster(tuple(by_number[number] for number in sorted(by_number)))


def _roster_from_json_data(data) -> LeagueRoster:
    members: list[LeagueMember] = []
    seen_numbers: set[int] = set()

    for raw in data.get("members", []):
        try:
            number = int(raw["race_number"])
            name = _clean_text(raw["name"])
            if not name:
                raise ValueError("name is required")

            online_names = tuple(
                alias
                for alias in (_clean_text(value) for value in raw.get("online_names", ()))
                if alias
            )
            member = LeagueMember(
                name=name,
                race_number=number,
                online_names=online_names,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid roster member {raw!r}: {exc}") from exc

        if number in seen_numbers:
            raise ValueError(f"duplicate race number {number} in roster")
        seen_numbers.add(number)
        members.append(member)

    return LeagueRoster(members=tuple(members))


def _normalize_header(value: str) -> str:
    return "_".join(value.strip().lower().replace("_", " ").split())


def _clean_text(value) -> str:
    return "" if value is None else str(value).strip()


def _is_generic_shown_name(value) -> bool:
    return _clean_text(value).casefold() in _GENERIC_SHOWN_NAMES_CASEFOLD


def _split_online_names(value) -> list[str]:
    return [name.strip() for name in _clean_text(value).split(";") if name.strip()]
