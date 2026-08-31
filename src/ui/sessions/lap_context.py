"""What each lap *was* - read once, and used by the Laps box, the stint split and the pace average.

Three parts of the session detail have to agree about a lap: the indicator beside it in the Laps
box, whether the stint split treats it as a run boundary, and whether the run's average pace counts
it. Before this module each derived its own answer, and they disagreed - the pace chart called a
practice flying lap an in-lap and left it out of an average the table said nothing about. So the
classification is made once here, and the other two read it.

**Stored truth first, inference only for old rows.** A lap ingested at ``PIPELINE_VERSION`` 4 or
later carries what Lap Data actually reported, and that wins outright:

* **out-lap** - the pit-lane timer was running as the lap began, or the game called it an out-lap
  for most of it. The second half is what catches a *red-flag restart*, where the field leaves the
  pit lane with no stop and the timer never runs.
* **in-lap** - the pit-lane timer was still running as the car crossed the line. Deliberately not
  ``driver_status == IN_LAP``, which the game sets on the *planned* in-lap and leaves set while the
  driver stays out - three laps early in one race here, six in another.
* **safety car** and **red flag** - from the Session packet's own race-control state, attributed to
  the lap that was in progress.

The fifth, **standing start**, is not stored and does not need to be: lap 1 of a race or a sprint
begins at rest in the grid box, and only the caller knows which sessions those are (a Sprint Race
and a Grand Prix share a ``session_type``, core invariant #5). It is classified here beside the
other four so that the set of chips and the set of pace exclusions are the same set.

A lap stored before that carries none of it, and falls back to what the shipped rules could infer
from the shape of the stint split (``tyre_stints.in_lap_numbers`` and the slow-opener test). Both
paths are live and both are tested; ``Lap.has_lap_context`` is the only thing that chooses between
them.

**What that changed, measured.** In practice and qualifying the game never times the lap the driver
returns to the pits on, so it is never stored - which means an emitted practice lap is *never* an
in-lap or an out-lap (all 159 non-race laps in this database read ``FLYING`` end to end). The old
inference labelled one in six practice sessions anyway and dropped a genuine flying lap out of the
run average. It is now counted, which is the honest answer even though it moves some averages by a
second or so. Conversely a safety-car lap now comes *out*: one Shanghai race's final run averaged
1:55.967 with four safety-car laps in it and averages 1:36.776 without them.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from ...protocol.enums import SafetyCarStatus, safe_enum
from .tyre_stints import TyreStint, in_lap_numbers, split_tyre_stints

# Lap 1 of a race or a sprint begins at rest in the grid box, so it is seconds slower than any lap
# driven from speed. Keyed on the real lap *number* rather than a stint-relative offset: a race
# whose opening lap was never stored must not lose a genuine racing lap to this rule.
_STANDING_START_LAP_ = 1

# The chips the Laps box shows. Short because the column is narrow; the sentence that explains each
# one lives in the row's tooltip. There is exactly one per reason a lap can be left out of a run's
# average, which is the property that makes the average readable off the page: no lap is ever
# dropped without the table saying why.
_STANDING_START_CHIP = "START"
_OUT_LAP_CHIP = "OUT-LAP"
_IN_LAP_CHIP = "IN-LAP"
_SAFETY_CAR_CHIP = "SC"
_RED_FLAG_CHIP = "RED-FLAG"

_SAFETY_CAR_DEPLOYED = (int(SafetyCarStatus.FULL), int(SafetyCarStatus.VIRTUAL))


@dataclass(frozen=True)
class LapContext:
    """One Lap's context: what happened on it, and whether it can stand for the run's pace."""

    lap_number: int
    is_out_lap: bool = False
    is_in_lap: bool = False
    is_standing_start: bool = False
    is_restart: bool = False               # a standing start that follows a red flag, not the session's own
    safety_car: SafetyCarStatus | int | None = None             # Never = never captured, not "green"
    red_flagged: bool = False
    stored: bool = False                  # read from the lap, or inferred from the shape of the split

    @property
    def under_safety_car(self) -> bool:
        """Whether a safety-car was actually deployed - not merely a formation lap.
        
        ``FORMATION_LAP`` is reported for the first lap of every race here and says nothing about
        pace beyond the standing start already covering it, so it is not treated as a safety car.
        """
        return self.safety_car in _SAFETY_CAR_DEPLOYED

    @property
    def excluded_from_pace(self) -> bool:
        """Whether this lap is left out of its run's average, for a reason the UI can name."""
        return bool(self.is_out_lap or self.is_in_lap or self.is_standing_start
                    or self.under_safety_car or self.red_flagged)

    @property
    def indicators(self) -> tuple[str, ...]:
        """The chips shown beside the lap, in the order the lap ran: START, OUT, IN, SC, RED.

        Chronological rather than by severity, because that is how a lap reads - a lap can begin in
        the pit lane and end back in it, and ``OUT IN`` says that in the order it happened. Every
        chip is also a reason the lap is left out of its run's average, and every such reason has a
        chip, so an excluded lap can never look unexplained.
        """
        chips = []
        if self.is_standing_start:
            chips.append(_STANDING_START_CHIP)
        if self.is_out_lap:
            chips.append(_OUT_LAP_CHIP)
        if self.is_in_lap:
            chips.append(_IN_LAP_CHIP)
        if self.under_safety_car:
            chips.append(_SAFETY_CAR_CHIP)
        if self.red_flagged:
            chips.append(_RED_FLAG_CHIP)
        return tuple(chips)

    @property
    def reasons(self) -> tuple[str, ...]:
        """Full sentences for the tooltip, in the same order as :attr:`indicators`."""
        reasons = []
        if self.is_standing_start:
            reasons.append("Restart: the race restarted from the grid box after a red flag."
                           if self.is_restart else
                           "Standing start: the race started on the grid box.")
        if self.is_out_lap:
            reasons.append("Out-lap: this lap began in the pit lane.")
        if self.is_in_lap:
            reasons.append("In-lap: came into the pits at the end of this lap.")
        if self.under_safety_car:
            name = "Virtual safety car" if self.safety_car == SafetyCarStatus.VIRTUAL else "Safety car"
            reasons.append(f"{name}: the field was slowed on this lap.")
        if self.red_flagged:
            reasons.append("Red-flagged: the session was stopped on this lap.")
        return tuple(reasons)

    @property
    def tooltip(self) -> str| None:
        """What the Laps box says on hover, or None for an ordinary lap with nothing to explain."""
        if not self.reasons:
            return None
        lines = list(self.reasons)
        if self.excluded_from_pace:
            lines.append("Left out of the run's average pace.")
        return "\n".join(lines)


@dataclass(frozen=True)
class SessionAnalysis:
    """A session's runs and its per-lap context, produced together so they cannot disagree."""

    stints: tuple[TyreStint, ...] = ()
    by_lap: dict[int, LapContext] = field(default_factory=dict)

    def for_lap(self, lap_number: int) -> LapContext:
        """This lap's context; an empty one for a lap that isn't in the session."""
        return self.by_lap.get(lap_number) or LapContext(lap_number)

    @property
    def excluded_laps(self) -> frozenset[int]:
        """Every lap number left out of its run's average - what ``stint_average_ms`` is passed."""
        return frozenset(number for number, context in self.by_lap.items() 
                         if context.excluded_from_pace)

    @property
    def stored(self) -> bool:
        """Whether this session's laps carry lap context, or are being read through the fallback."""
        return any(context.stored for context in self.by_lap.values())


def _restart_laps(ordered: Sequence) -> frozenset[int]:
    """Lap numbers that are a restart from the grid box after a red flag.

    A red flag sends the field down the pit lane, and the game does not time the lap that drives
    back out to the grid - so the next lap it *does* time begins at rest in the grid box, exactly
    like the session's own first lap. Both red flags in this database restart that way, each with
    the intervening lap number missing entirely (Shanghai sprint 2 -> 4, Shanghai race 11 -> 13).

    Read from the lap before, not from the lap itself: what the game leaves on the restart lap is
    ``driver_status == OUT_LAP``, left over from the pit-lane drive it never timed, and believing
    that would call a grid start an out-lap (see assembler ``_is_out_lap``). Only called for a
    session that starts on the grid - a practice or qualifying restart really is a pit-lane exit,
    and the lane timer already catches it.
    """
    return frozenset(lap.lap_number for previous, lap in zip(ordered, ordered[1:])
                     if previous.red_flagged)


def analyse_session(laps: Sequence, *, standing_start: bool, min_laps: int | None = None) -> SessionAnalysis:
    """Split a session into runs and classify every lap, in the one order that works.

    The order is forced and worth stating: the *fallback* in-lap and out-lap rules are derived from
    the shape of the split, so the split has to happen first; the split's own garage boundary reads
    the stored flag straight off each lap, so it needs nothing from here. Sessions whose laps carry
    lap context never touch the inferred half at all.

    ``standing_start`` says this session began on the grid, which only the caller knows - a Sprint
    Race and a Grand Prix share a ``session_type`` (core invariant #5), so it cannot be read off the
    session here.
    """
    ordered = sorted(laps, key=lambda lap: lap.lap_number)
    stints = (split_tyre_stints(ordered) if min_laps is None
              else split_tyre_stints(ordered, min_laps))
    stored = any(lap.has_lap_context for lap in ordered)
    restarts = _restart_laps(ordered) if standing_start else frozenset()

    if stored:
        out_laps = {lap.lap_number for lap in ordered if lap.is_out_lap}
        in_laps = {lap.lap_number for lap in ordered if lap.is_in_lap}
    else:
        # Inferred, and only from laps that survived into a run: a lap the minimum-laps filter
        # dropped has no stint ordinal to read a flag from, which is exactly how it behaved before.
        out_laps = {lap.lap_number for stint in stints for lap in stint.laps if lap.is_out_lap}
        in_laps = set(in_lap_numbers(stints))

    by_lap = {
        lap.lap_number: LapContext(
            lap_number=lap.lap_number,
            is_out_lap=lap.lap_number in out_laps,
            is_in_lap=lap.lap_number in in_laps,
            is_standing_start=((standing_start and lap.lap_number == _STANDING_START_LAP_) 
                               or lap.lap_number in restarts),
            is_restart=lap.lap_number in restarts,
            # safe_enum, not the raw int: stored as an int (core invariant #9), read back as the
            # member so a value newer than our own enum passes through instead of crashing the page.
            safety_car=(safe_enum(SafetyCarStatus, lap.safety_car) 
                        if lap.safety_car is not None else None),
            red_flagged=bool(lap.red_flagged),
            stored=lap.has_lap_context)
        for lap in ordered
    }
    return SessionAnalysis(stints=stints, by_lap=by_lap)
