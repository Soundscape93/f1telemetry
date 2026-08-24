"""Tyre stints for the session detail charts - Qt-free, so the rules stay unit-testable.

Turns a session's stored laps into the stints they were driven in, on a *stint-relative* axis:
every stint restarts at stint lap 1, so a medium stint's lap 5 sits directly under a hard stint's
lap 5 and the two compounds become comparable. Degradation is a function of stint age, not race lap.

Four rules here were measured against the real database rather than reasoned about, and each has a
session that breaks the naive alternative:

* **Split on cumulative wear dropping, or the compound changing - never on ``tyre_age_laps``.** The
  Car Status snapshot straddles the game's own increment, so age runs ``0, 2, 2, 4, 4`` *inside* one
  stint; splitting on it turned a 27-lap race into fourteen stints. Wear is monotonic within a stint
  and resets on a new set. (TELEMETRY_NOTES -> tyre_age_laps.)
* **Tyre life is ``100 - max(wear)``, the worst wheel.** The worst corner is what forces the stop; a
  mean smooths away the signal being looked for. Per-wheel values ride along for the tooltip.
* **A stint needs at least two laps**, in every session type. It also earns its keep as a filter: a
  pit in-lap leaves a one-lap artefact stint from a stale reading, dropped here with no special case.
* **A stint's first lap is an out-lap when the stint follows a pit stop**, which the pace chart
  excludes from its y-range - the game bundles the whole pit loss into that lap (+14 to +37 s against
  a 1-3 s degradation signal). Stint 1 lap 1 is a race start and is *not* excluded.

The order of the last two is load-bearing and not interchangeable: the out-lap flag comes from the
stint's ordinal in the *unfiltered* split, and only then are short stints dropped. Session
``12316788...`` is why - its opening stint is a single lap that the filter removes, and reading the
flag afterwards would promote the 170.8 s post-pit lap behind it to "race start" and stretch the
pace axis from 4 s to 75 s.

Offsets come from real lap *numbers*, never a list index: lap numbers are not contiguous (a red flag
or a dropped lap leaves a hole), and an index axis would silently close the gap and misplace every
lap after it. ``stint_series`` keeps those holes as holes.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import nan

_MIN_STINT_LAPS = 2         # DECISIONS -> UI: every session type, and it drops pit-lap artefacts too
_PACE_PADDING = 0.05        # headroom past the representative laps, as a fraction of their span
_MIN_PACE_SPAN_MS = 1000.0  # a floor, so a session whose laps are all but identical still gets an axis
_MAX_PACE_SPAN_MS = 8000.0  # the widest spread the pace axis will show; see pace_y_range


@dataclass(frozen=True)
class StintLap:
    """One lap inside a stint, placed on the stint-relative axis."""

    lap_number: int             # the real lap number - what the tooltip shows
    stint_lap: int              # 1-based offset within the stint, from lap numbers (holes preserved)
    lap_time_ms: int | None     # None when the game never timed the lap
    tyre_life: float            # 100 - max(wear): the worst wheel, per DECISIONS
    wear: tuple[float, ...]     # per-wheel cumulative %, RL RR FL FR - for the tooltip
    is_out_lap: bool            # first lap of a stint that follows a pit stop: plotted, never scaled to


@dataclass(frozen=True)
class TyreStint:
    """One set of tyres: the laps driven on it, and what it was."""

    index: int                  # 1-based over the stints that survived the minimum-laps filter
    visual_compound: int | None
    laps: tuple[StintLap, ...]
    follows_pit: bool           # from the *unfiltered* ordinal - see the module docstring

    @property
    def first_lap_number(self) -> int:
        return self.laps[0].lap_number

    @property
    def last_lap_number(self) -> int:
        return self.laps[-1].lap_number

    @property
    def lap_count(self) -> int:
        """How many laps were actually stored for this stint."""
        return len(self.laps)

    @property
    def axis_span(self) -> int:
        """How far the stint reaches along the axis, counting any missing laps inside it."""
        return self.laps[-1].stint_lap


def split_tyre_stints(laps: Sequence, min_laps: int = _MIN_STINT_LAPS) -> tuple[TyreStint, ...]:
    """The stints a session's laps were driven in, ordered by lap number.

    ``laps`` are ``domain.models.Lap`` rows as ``LapStore.list`` returns them. A lap with no tyre
    context is skipped - a stint is a statement about a set of tyres, and a lap that can't say which
    set it was on can't be placed on one.

    A boundary is a *drop* in the worst wheel's cumulative wear, or a change of visual compound.
    Stints shorter than ``min_laps`` are dropped only *after* the out-lap flags are assigned, so a
    removed artefact stint can never promote the stint behind it to "race start".
    """
    stored = sorted((lap for lap in laps if lap.tyre_context is not None),
                    key=lambda lap: lap.lap_number)

    groups: list[list] = []
    for lap in stored:
        if groups and not _starts_new_stint(lap, groups[-1][-1]):
            groups[-1].append(lap)
        else:
            groups.append([lap])

    stints: list[TyreStint] = []
    for ordinal, group in enumerate(groups):
        if len(group) < min_laps:
            continue                    # a pit in-lap's stale reading, or a single flying lap
        follows_pit = ordinal > 0       # unfiltered: only the session's own first stint is a start
        stints.append(TyreStint(
            index=len(stints) + 1,
            visual_compound=_compound(group[0]),
            laps=_place_on_axis(group, follows_pit),
            follows_pit=follows_pit))
    return tuple(stints)


def stint_axis_max(stints: Sequence[TyreStint]) -> int:
    """How far the shared x-axis runs: the longest stint's span, or 1 when there are no stints."""
    return max((stint.axis_span for stint in stints), default=1)


def representative_laps(stints: Sequence[TyreStint]) -> tuple[StintLap, ...]:
    """Every timed lap allowed to set the pace chart's scale - the ordinary racing laps.

    Both pit-affected laps come out, for the same reason: neither measures the tyre. The out-lap is
    structural and certain (the first lap of a stint that follows a stop) and carries +14 to +37 s.
    The in-lap is inferred from stint contiguity and is milder - measured across this database, a
    median +3.68 s - but that is the same order as the 1-3 s degradation signal the chart exists to
    show, and on one race here the in-lap is the single lap setting the whole scale.

    ``in_lap_numbers`` declines to claim a lap it cannot be sure about, so a session with laps
    missing around the stop keeps its in-lap in the range and lets ``max_span`` deal with it.
    """
    in_laps = in_lap_numbers(stints)
    return tuple(lap for stint in stints for lap in stint.laps
                 if not lap.is_out_lap and lap.lap_number not in in_laps and lap.lap_time_ms)


def in_lap_numbers(stints: Sequence[TyreStint]) -> frozenset[int]:
    """The lap numbers we can honestly call in-laps: the driver pitted at the end of them.

    Inferred, not stored - pit events live in Event packets the assembler doesn't read yet
    (PRIORITIES -> E15). A stint ending immediately before the next one begins means the tyre change
    happened between those two laps, so the earlier one is the lap into the pits.

    The contiguity check is what makes that safe to say. In ``11708585...`` stint 2's last stored lap
    is 18 but the next stint opens at 22 - laps 19-20 are missing and 21 was a stale artefact - so
    lap 18 is *not* the in-lap, and is deliberately not claimed as one.
    """
    return frozenset(
        stint.last_lap_number
        for stint, following in zip(stints, stints[1:])
        if following.first_lap_number == stint.last_lap_number + 1)


def pace_y_range(stints: Sequence[TyreStint], padding: float = _PACE_PADDING,
                 max_span: float | None = _MAX_PACE_SPAN_MS) -> tuple[float, float] | None:
    """The pace chart's y-range in ms, from the representative laps only - or None if there are none.

    Two bounds, doing different jobs. ``representative_laps`` drops the pit laps, which are
    systematic: on a stint-relative axis every out-lap lands on x = 1, so letting them in would
    squash the real 1-3 s degradation signal into a few percent of the plot height.

    ``max_span`` then bounds what is left, anchored at the *fast* end - the fastest lap is the
    reference every other lap is read against, so it is the one thing that must never clip. It
    catches what no rule can classify: one race here spans 49.7 s on four incident laps in the
    120-140 s range, and the signal disappears just as thoroughly as under an out-lap. Measured
    across this database, ordinary lap-to-lap variance stays well inside 8 s - what runs past it is
    incidents and pit laps - so the cap costs a consistent driver nothing and rescues a chaotic race.

    Padding is taken from the *capped* span deliberately. From the raw one, a 40 s spread would pad
    by 2 s and burn a quarter of the window on dead air below the fastest lap.

    Laps past the range are still plotted, clipped, with the true time in the tooltip. Pass
    ``max_span=None`` to fit the whole spread.
    """
    values = [float(lap.lap_time_ms) for lap in representative_laps(stints)]
    if not values:
        return None
    low, high = min(values), max(values)
    if max_span is not None:
        high = min(high, low + max_span)    # cap the data window, never the fast end
    span = (high - low) or _MIN_PACE_SPAN_MS
    return low - span * padding, high + span * padding


def stint_series(stint: TyreStint, value_of: Callable[[StintLap], float],
                 skip: Callable[[StintLap], bool] | None = None) -> tuple[list[float], list[float]]:
    """A stint's line as x/y lists over the stint-relative axis, with holes kept as holes.

    A lap that was never stored becomes ``nan`` rather than being closed up, so the chart can break
    the line there (pyqtgraph's ``connect="finite"``) instead of drawing a straight segment across
    laps that don't exist. ``skip`` blanks a lap that *does* exist but must not join the line - the
    pace chart passes it the out-lap, which is drawn as its own clipped marker instead.
    """
    by_offset = {lap.stint_lap: lap for lap in stint.laps}
    offsets = range(1, stint.axis_span + 1)
    xs = [float(offset) for offset in offsets]
    ys = [nan if (lap := by_offset.get(offset)) is None or (skip is not None and skip(lap))
          else float(value_of(lap))
          for offset in offsets]
    return xs, ys


# --- reading one stored lap ----------------------------------------------------------------------
def _starts_new_stint(lap, previous) -> bool:
    """Whether ``lap`` begins a new set: the worst wheel's wear dropped, or the compound changed.

    Strict ``<``, with no tolerance. Checked against every lap-to-lap wear drop in the real database
    - thirty of them: the smallest is a ``-0.0`` float artefact that strict ``<`` already rejects,
    and every other one is a genuine set change. A tolerance would only be a rule nobody measured.
    """
    return _max_wear(lap) < _max_wear(previous) or _compound(lap) != _compound(previous)


def _place_on_axis(group: list, follows_pit: bool) -> tuple[StintLap, ...]:
    """Put a stint's laps on the stint-relative axis, from lap numbers rather than list position."""
    base = group[0].lap_number
    return tuple(
        StintLap(
            lap_number=lap.lap_number,
            stint_lap=lap.lap_number - base + 1,
            lap_time_ms=lap.lap_time_ms,
            tyre_life=100.0 - _max_wear(lap),
            wear=_wear(lap),
            is_out_lap=(follows_pit and position == 0))
        for position, lap in enumerate(group))


def _max_wear(lap) -> float:
    """The worst wheel's cumulative wear %. The worst corner is what forces the stop, not the mean."""
    context = lap.tyre_context
    return float(max(context.wear)) if context is not None and context.wear else 0.0


def _wear(lap) -> tuple[float, ...]:
    context = lap.tyre_context
    return tuple(float(value) for value in context.wear) if context is not None and context.wear else ()


def _compound(lap) -> int | None:
    context = lap.tyre_context
    return context.visual_compound if context is not None else None
