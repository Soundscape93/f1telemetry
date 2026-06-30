"""League roster - maps in-game driver identity to a league member.

A league weekend is an independent online lobby, a member's car index and shown name can
differ each time, and their name shows at all only if they set set telemetry to public.
The stable anchors are the online name (when public) and the race number (a profile setting,
always visible). This hand-maintained roster lets standings resolve a captured entry to the 
same member across weekends - online name first, race number as a fallback for anyone who
didn't make their telemetry public. It's a JSON file, not a database, so it adds no schema.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LeagueMember:
    """One league member: the canonical name shown in standings, their race number, and any
    online names they appear under in telemetry when teir privacy is public."""

    name: str
    race_number: int
    online_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class LeagueRoster:
    members: tuple[LeagueMember, ...] = ()

    def member_of(self, entry) -> str:
        """Resolve a classification entry to a member's canonical name.
 
        Online name first (exact match against any known online name), then race number. An
        entry matching neither is returned under its own shown name - an unknown driver still
        appears in standings, just unmatched. Used as both the grouping key and the display
        name when computing league standings.
        """

        shown_name = entry.driver_name
        for member in self.members:
            if shown_name in member.online_names:
                return member.name
        for member in self.members:
            if member.race_number == entry.race_number:
                return member.name
        return shown_name
    

def load_roster(path: str | Path) -> LeagueRoster:
    """Load a roster from JSON:

        eg:
        {"members": [
            {"name": "Kevin", race_number": 50, "online_names": ["soundscape93", "kevin93"]},
            {"name": "Sam", race_number": 7}
        ]}

    ``online_names`` is optional (a member who never sets public telemetry is matched by
    number alone). Raises ``ValueError``on a malformed member or a duplicate race number.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    members: list[LeagueMember] = []
    seen_numbers: set[int] = set()
    for raw in data.get("members", []):
        try:
            number = int(raw["race_number"])
            member = LeagueMember(
                name=raw["name"],
                race_number=number,
                online_names=tuple(raw.get("online_names", ())),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid roster member {raw!r}: {exc}") from exc
        if number in seen_numbers:
            raise ValueError(f"duplicate race number {number} in roster")
        seen_numbers.add(number)
        members.append(member)
        
    return LeagueRoster(members=tuple(members))
