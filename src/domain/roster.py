"""League roster - maps in-game driver identity to a league member.

A league weekend is an independent online lobby, a member's car index and shown name can
differ each time, and their name shows at all only if they set telemetry to public.
The stable anchors are the online name (when public) and the race number (a profile setting,
always visible). This hand-maintained roster lets standings resolve a captured entry to the
same member across weekends - online name first, race number as a fallback for anyone who
didn't make their telemetry public. The app's canonical roster is a JSON file, not a
database, so it adds no schema. CSV is supported as a user-friendly import format that is
validated and converted into that per-season JSON file.

**Race numbers are only unique among humans.** The AI field runs the real-world numbers, so a
member on 11 shares it with Sergio Perez, and a naive number match merges the two into one
standings row. Identity therefore resolves in strict evidence order - online name, then race
number *for human cars only*, then the entry's own identity - and it resolves a whole
classification at a time (:meth:`LeagueRoster.session_keys`) so two cars in one session can never
land on the same standings row. See docs/DECISIONS.md -> "Identity & rosters".
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from collections.abc import Hashable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..protocol.reference import DRIVER_NAMES
from .season import RoundResults

_GENERIC_SHOWN_NAMES = {"", "Player"}
_GENERIC_SHOWN_NAMES_CASEFOLD = {name.casefold() for name in _GENERIC_SHOWN_NAMES}

# the game's AI driver appendix. Used only as a *fallback* signal for classification rows stored before ``is_ai`` was captured
_AI_DRIVER_NAMES_CASEFOLD = frozenset(name.casefold() for name in DRIVER_NAMES.values())


def is_ai_entry(entry) -> bool:
    """Whether the *game* said this car is AI-controlled (Participants ``m_aiControlled``).

    Authoritative, so it is the one signal allowed to veto an online-name match: a genuinely
    AI-controlled car is never a league member, whatever the roster says.
    """
    return bool(getattr(entry, "is_ai", False))


def looks_like_ai(entry) -> bool:
    """``is_ai`` plus a name heuristic fallback, for rows captured before ``is_ai`` was stored.
        
    An entry whose shown name is one of the game's AI drivers is treated as AI. This is a
    heuristic - a human *could* pick "Lando Norris" as a gamertag - so it only ever blocks the
    race-number fallback (where a false positive costs an unmatched row), never an explicit
    roster alias match (where the user has said in so many words who this is).
    """
    if is_ai_entry(entry):
        return True
    return _clean_text(getattr(entry, "driver_name", "")).casefold() in _AI_DRIVER_NAMES_CASEFOLD


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
        """Return the roster member for an entry, or None if it is unknown.
        
        Evidence order: an explicit online-name alias, then the race number for human cars only.
        Per-entry and therefore context-free - :meth:`session_keys` is the one to use for 
        standings, because only it can see the rest of the classification.
        """
        member = self._member_by_online_name(entry)
        if member is not None:
            return member
        return self._member_by_race_number(entry)

    def member_of(self, entry) -> str:
        """Resolve a classification entry to a member's canonical name.

        Online name first, then race number (humans only). An entry matching neither is returned
        under its own shown name - an unknown driver still appears in standings, just unmatched.
        """
        member = self.member_for(entry)
        return member.name if member is not None else entry.driver_name

    def member_key(self, entry) -> Hashable:
        """A stable, *tagged* grouping key for one entry.

        Tagged (``("member", ...)`` / ``("ai", ...)`` / ``("driver", ...)``) so keys from
        different resolution paths can never collide: a roster member on 11 and an unmatched
        driver on 11 are different rows, which a bare ``11`` could not express. Members key on
        canonical name (unique per roster), AI on its canonical driver name (stable across
        rounds), and everyone else on race number - so a human whose shown name drifts between
        lobbies still groups, and two roster-unknown humans on different numbers still don't.
        """
        member = self.member_for(entry)
        if member is not None:
            return ("member", member.name)
        return self._own_key(entry)

    def session_keys(self, entries: Sequence) -> tuple[Hashable, ...]:
        """Grouping keys for one whole classification, guaranteed distinct within it.

        Resolving per session rather than per entry is what prevents a silent merge: two rows in
        one final classification are two different cars, so they must never share a standings
        row. Strongest evidence wins - every online-name match is claimed first, then the
        race-number fallback fills in from what is left, skipping members already claimed. Any
        repeat that survives (only possible among unmatched cars) is split by
        :func:`_disambiguate` rather than merged.
        """
        entries = tuple(entries)
        resolved: list[LeagueMember | None] = [None] * len(entries)
        claimed: set[str] = set()

        for i, entry in enumerate(entries):                 # pass 1: explicit alias, strongest evidence
            member = self._member_by_online_name(entry)
            if member is not None and member.name not in claimed:
                resolved[i] = member
                claimed.add(member.name)

        for i, entry in enumerate(entries):                 # pass 2: race number, humans, unclaimed only
            if resolved[i] is not None:
                continue
            member = self._member_by_race_number(entry)
            if member is not None and member.name not in claimed:
                resolved[i] = member
                claimed.add(member.name)

        keys = [
            ("member", member.name) if member is not None else self._own_key(entry)
            for entry, member in zip(entries, resolved, strict=True)
        ]
        return _disambiguate(keys, entries)

    # --- resolution steps -------------------------------------------------------------------
    def _member_by_online_name(self, entry) -> LeagueMember | None:
        """Explicit alias match, case-insensitive. Never matches an AI car, never matches on a 
        generic shown name - a roster listing ``Player`` as an alias would otherwise swallow
        every privacy restricted human in the lobby."""
        if is_ai_entry(entry):
            return None
        shown = _clean_text(getattr(entry, "driver_name", "")).casefold()
        if not shown or shown in _GENERIC_SHOWN_NAMES_CASEFOLD:
            return None
        for member in self.members:
            if any(shown == alias.casefold() for alias in member.online_names):
                return member
        return None

    def _member_by_race_number(self, entry) -> LeagueMember | None:
        """Race-number fallback: humans only, and only when the number is unambiguous.

        Skipping AI is the collision fix - the AI field runs real-world numbers, so an AI on 11
        is not the member on 11. A number shared by two members (allowed only when both carry
        online names) resolves by alias or not at all."""
        if looks_like_ai(entry):
            return None
        matches = [m for m in self.members if m.race_number == entry.race_number]
        return matches[0] if len(matches) == 1 else None

    def _own_key(self, entry) -> Hashable:
        """The key for an entry that resolved to no member: its own identity, tagged by kind."""
        if looks_like_ai(entry):
            # AI names are canonical (normalizer bakes the appendix name in), so they are
            # stable across rounds in a way an AI's race number need not be.
            return ("ai", _clean_text(getattr(entry, "driver_name", "")).casefold())
        return ("driver", entry.race_number)
    

def _disambiguate(keys: list[Hashable], entries: Sequence) -> tuple[Hashable, ...]:
    """Split any key shared by two entries of the same classification.

    Never merge two cars just because they look alike: repeats are broken by shown name first,
    then by vehicle index for the genuinely indistinguishable case (two privacy-restricted humans
    on the same race number, both shown as ``"Player"``). Such a season is unresolvable by
    construction - the split is the honest outcome, and the fix is a public online name or a
    unique number. Deterministic, and a no-op for the overwhelmingly common all-distinct case.
    """
    counts = Counter(keys)
    if all(count == 1 for count in counts.values()):
        return tuple(keys)

    seen: set[Hashable] = set()
    out: list[Hashable] = []
    for key, entry in zip(keys, entries, strict=True):
        candidate = key
        if counts[key] > 1:
            candidate = key + (_clean_text(getattr(entry, "driver_name", "")).casefold(),)
        while candidate in seen:
            candidate = candidate + (entry.vehicle_index,)
        seen.add(candidate)
        out.append(candidate)
    return tuple(out)


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
    """Seed a roster from captured classification names/numbers.

    AI cars are skipped: they are not league members, and admitting them would poison the seed
    twice over - a member row per AI number, and (worse) an AI name landing in the
    ``online_names`` of the member who shares that number, which the alias match would then
    honour. A seeded roster is the human field only.
    """
    names_by_number: dict[int, set[str]] = {}

    for round_result in rounds:
        for session in round_result.sessions:
            if session.classification is None:
                continue
            for entry in session.classification.entries:
                if looks_like_ai(entry):
                    continue
                names_by_number.setdefault(entry.race_number, set()).add(
                    entry.driver_name.strip()
                )

    members = []
    used_names: set[str] = set()
    for number in sorted(names_by_number):
        aliases = sorted(
            name for name in names_by_number[number]
            if not _is_generic_shown_name(name)
        )
        members.append(
            {
                "name": _unique_seed_name(
                    aliases[0] if aliases else f"Driver {number}", number, used_names),
                "race_number": number,
                "online_names": aliases,
            }
        )

    return _roster_from_json_data({"members": members})


def _unique_seed_name(name: str, number: int, used: set[str]) -> str:
    """Keep seeded canonical names unique - they are the standings grouping key.

    One online name legitimately appears under two race numbers when a member changes their
    number mid-season: the seed then holds two members and still has to name them apart, or
    validation would reject a perfectly ordinary season. Qualifying with the race number is
    enough, and reads sensibly in the file the user goes on to hand-edit.
    """
    candidate = name if name.casefold() not in used else f"{name} ({number})"
    suffix = 2
    while candidate.casefold() in used:
        candidate = f"{name} ({number}, {suffix})"
        suffix += 1
    used.add(candidate.casefold())
    return candidate


def merge_rosters(primary: LeagueRoster, fallback: LeagueRoster) -> LeagueRoster:
    """Keep primary member names, add fallback aliases and members the primary lacks.

    Members match by canonical name first, then by race number - and by number only when it
    identifies exactly one primary member, since a league may deliberately run two members on one
    number (each then told apart by online name).
    """
    merged = list(primary.members)

    def _index_of(member: LeagueMember) -> int | None:
        for i, existing in enumerate(merged):
            if existing.name.casefold() == member.name.casefold():
                return i
        sharing = [
            i for i, existing in enumerate(merged)
            if existing.race_number == member.race_number
        ]
        return sharing[0] if len(sharing) == 1 else None

    for member in fallback.members:
        index = _index_of(member)
        if index is None:
            merged.append(member)
            continue
        existing = merged[index]
        merged[index] = LeagueMember(
            name=existing.name,
            race_number=existing.race_number,
            online_names=tuple(dict.fromkeys(existing.online_names + member.online_names)),
        )

    return LeagueRoster(tuple(sorted(merged, key=lambda m: (m.race_number, m.name))))


def _roster_from_json_data(data) -> LeagueRoster:
    members: list[LeagueMember] = []

    for raw in data.get("members", ()):
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
            raise ValueError(f"invalid roster member: {raw!r}: {exc}") from exc

        members.append(member)

    _validate_members(members)
    return LeagueRoster(members=tuple(members))


def _validate_members(members: Sequence[LeagueMember]) -> None:
    """Enforce what identity resolution depends on.

    Canonical names must be unique because they *are* the standings grouping key. Race numbers
    should be unique too, but a league that lets two members share one is no longer a data error
    now that the online name can tell them apart - so the duplicate is allowed exactly when every
    member holding that number has at least one online name, and rejected otherwise (nothing
    could ever separate them).
    """
    seen_names: set[str] = set()
    by_number: dict[int, list[LeagueMember]] = {}
    for member in members:
        folded = member.name.casefold()
        if folded in seen_names:
            raise ValueError(f"duplicate member name: {member.name!r}, in roster")
        seen_names.add(folded)
        by_number.setdefault(member.race_number, []).append(member)

    for number, sharing in sorted(by_number.items()):
        if len(sharing) > 1 and any(not member.online_names for member in sharing):
            raise ValueError(
                f"duplicate race number {number} in roster: members sharing a race number must "
                "each have at least one online name, because only the online name can tell them "
                "apart"
            )


def _normalize_header(value: str) -> str:
    return "_".join(value.strip().lower().replace("_", " ").split())


def _clean_text(value) -> str:
    return "" if value is None else str(value).strip()


def _is_generic_shown_name(value) -> bool:
    return _clean_text(value).casefold() in _GENERIC_SHOWN_NAMES_CASEFOLD


def _split_online_names(value) -> list[str]:
    return [name.strip() for name in _clean_text(value).split(";") if name.strip()]
