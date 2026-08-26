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

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from math import nan
from statistics import median

from ..formatting import format_lap_time

_MIN_STINT_LAPS = 2             # DECISIONS -> UI: every session type, and it drops pit-lap artefacts too
_PACE_PADDING = 0.05            # gap between the axis floor and the fastest lap, as a fraction of the span
_PACE_SPAN_MS = 8000.0          # the pace axis is always exactly this tall; see pace_y_range
_GARAGE_FUEL_DELTA_KG = -0.5    # a lap burns 1.06-1.96 kg; above this: the car was in the garage
_STANDING_START_LAP = 1         # lap 1 of a race begins at rest in the grid box - not representative pace


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


def stint_average_ms(stint: TyreStint, in_laps: Collection[int] = (), *,
                     standing_start: bool = False) -> float | None:
    """A stint's average pace in ms over the laps that represent it, or None when none do.

    A plain mean of a stint's laps is not its pace. Three kinds of lap belong to the pit stop or to
    the start rather than to the run, and each is worth seconds against a degradation signal
    measured in tenths:

    * **the out-lap** - the lap after the stop carries the whole pit loss (+14 to +37 s in this
      database). Already flagged per lap, and flagged from the *unfiltered* stint ordinal, so an
      artefact stint the minimum-laps rule removed can never promote a post-pit lap to "race start".
    * **the in-lap** - the lap into the pits, from :func:`in_lap_numbers`, which only claims one
      where the lap numbers of two stints actually meet.
    * **the standing start** - lap 1 of a race or sprint begins at rest in the grid box, so it is
      seconds slower than any lap driven from speed. Keyed on the real lap *number*, not on the
      stint-relative offset: a race whose opening lap was never stored must not lose a genuine
      racing lap to this rule.

    Nothing else is excluded, and that limit is worth knowing: a lap spent in the gravel or behind
    a safety car still counts, because nothing stored says it was one (PRIORITIES -> E15). Fuel is
    not corrected for either - the charts say so outright, and a correction is Analytics work.
    """
    times = [lap.lap_time_ms for lap in stint.laps
             if lap.lap_time_ms
             and not lap.is_out_lap
             and lap.lap_number not in in_laps
             and not (standing_start and lap.lap_number == _STANDING_START_LAP)]
    return (sum(times) / len(times)) if times else None


def stint_average_label(stint: TyreStint, in_laps: Collection[int] = (), *,
                        standing_start: bool = False) -> str:
    """:func:`stint_average_ms` as a lap time, or an em dash when no lap represents the stint.

    An em dash rather than silence: a two-lap opening stint of a standing start and an in-lap
    genuinely has no pace to report, and a missing number would read as one the app forgot to fill
    in. Formatted through ``format_lap_time`` so the legend, the tooltips and the laps table all
    print a lap time the same way.
    """
    average = stint_average_ms(stint, in_laps, standing_start=standing_start)
    return format_lap_time(round(average)) if average is not None else "\u2014"


def pace_y_range(stints: Sequence[TyreStint], padding: float = _PACE_PADDING,
                 span_ms: float | None = _PACE_SPAN_MS) -> tuple[float, float] | None:
    """The pace chart's y-range in ms - a fixed window above the quickest lap, or None if untimed.

    **The axis is always the same height.** Fitting it to the data was dishonest at both ends.
    *Too wide*: a post-pit out-lap carries +14 to +37 s and, on a stint-relative axis, every one of
    them lands on x = 1, so the real 1-3 s degradation signal was squashed into a few percent of the
    plot - and an incident lap, which no rule can classify, did the same (one race here spreads
    49.7 s over four laps in the 120-140 s range). *Too narrow*: a run whose laps sit within 0.3 s
    of each other had that 0.3 s stretched over the full height, so laps that were effectively
    identical read as a dramatic fall-off.

    A fixed window answers both, and makes two sessions comparable at a glance, which fitting
    actively prevented. Over the plot's height it resolves about 20 ms per pixel, and 0.3 s of
    spread occupies about 4% of it - which is what "these laps were the same" should look like.

    Anchored at the quickest lap and extending *upward*: no lap can appear below it, so centring the
    window would spend half the plot on space nothing can occupy. ``padding`` is the small gap that
    keeps that lap off the border.

    The anchor counts **every** timed lap, pit laps included. With the height fixed, an out-lap
    cannot stretch the scale however slow it is, so there is nothing to exclude - and excluding
    would actively hurt: in practice and qualifying the quickest lap of the session is often a run's
    first stored lap, and anchoring above it dropped it off the bottom of the plot entirely.

    Laps outside the window are still plotted, clipped to the nearer edge with the true time in the
    tooltip. Pass ``span_ms=None`` to fit the data instead.
    """
    values = [float(lap.lap_time_ms)
              for stint in stints for lap in stint.laps if lap.lap_time_ms]
    if not values:
        return None
    low, high = min(values), max(values)
    if span_ms is None:
        span = (high - low) or _PACE_SPAN_MS
        return low - span * padding, high + span * padding
    pad = span_ms * padding
    return low - pad, low - pad + span_ms


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
    """Whether ``lap`` begins a new run: fresh tyres, or the car went back to the garage.

    "Stint" here means a *continuous run on one set*, which is what the chart needs. In a race that
    is the same thing as a set, because the car leaves the garage once. In practice and qualifying
    they come apart: one set often does several runs, and two fresh sets can do a single lap each. A
    line drawn straight through a garage visit claims a continuity that did not happen.

    Four signals, and each is load-bearing - see the helpers for the session that defeats the others.
    """
    return (_max_wear(lap) < _max_wear(previous)
            or _age_reset(lap, previous)
            or _compound(lap) != _compound(previous)
            or _returned_to_garage(lap, previous))


def _returned_to_garage(lap, previous) -> bool:
    """Whether the car went back to the garage between these two laps, read from the fuel load.

    A full lap burns 1.06-1.96 kg across every session in this database, and fuel cannot be added on
    track - so a load that rises, or barely falls, means a garage visit and a new run.

    It is the only signal that separates two *fresh sets of the same compound*. A Q3 pair of new
    softs reads ``age 0`` on both laps, the same compound, and wear that rises rather than resets,
    so nothing in the tyre data tells them apart; fuel shows -0.22 to +0.05 kg where a lap costs 1.2.
    Measured across the whole database: 22 detections in practice and qualifying, every one matching
    a run boundary, against 1 in 322 race transitions - and that one is in ``12316788...``, whose
    lap 3 is missing and whose lap 2 took 170 s.

    Deliberately *not* ``tyre_age_laps == 0`` on both laps, which looks like the same signal and is
    not: a post-pit out-lap reports age 0 at wear 0.00 and the lap after it still reports age 0, so
    that rule breaks three race stints that are currently correct.

    A proxy, and known to be one. ``driver_status`` in the Lap Data packet states outright when the
    car is in the garage (PRIORITIES -> E17); once that is stored this becomes the fallback for rows
    ingested before it.
    """
    now, before = lap.fuel_in_tank, previous.fuel_in_tank
    return (now is not None and before is not None
            and now - before > _GARAGE_FUEL_DELTA_KG)


def _age_reset(lap, previous) -> bool:
    """Whether the tyre-age counter *fell*, which only a fresh set can do.

    Narrow on purpose, and not a contradiction of TELEMETRY_NOTES. That warns against deriving
    boundaries from age *increments* - the Car Status snapshot straddles the game's own increment,
    so one stint reads ``0, 2, 2, 4, 4`` and a "must increment by one" rule turned a 27-lap race
    into fourteen stints. A *fall* is a different signal: nothing but a new set puts a lower number
    there.

    It earns its place because wear alone can miss a set change. In ``10198131...`` (Jeddah P1) a
    tyre-saving practice programme on softs is followed by a qualifying simulation on a fresh set of
    the same compound, and the new set's first reading is *higher* than the old set's last - 17.97
    against 15.92. Compound unchanged, wear never drops, so the two runs merged into one curve
    claiming a single set had worn 9.51 -> 15.92 -> 17.97, which is simply not what happened.

    Checked across every stored lap: this adds exactly one boundary, that one. 26 of the 27 age
    falls in the database already coincide with a wear drop, and 4 wear drops have no age fall, so
    neither test subsumes the other.
    """
    now, before = _age(lap), _age(previous)
    return now is not None and before is not None and now < before


def _age(lap) -> int | None:
    """The stored tyre age, or None - never coerced to 0, which would read as a reset."""
    context = lap.tyre_context
    return context.age_laps if context is not None else None


def _place_on_axis(group: list, follows_pit: bool) -> tuple[StintLap, ...]:
    """Put a run's laps on the sint-relative axis, from lap numbers rather than list position."""
    base = group[0].lap_number
    opener_is_out_lap = follows_pit and _is_slow_opener(group)
    return tuple(
        StintLap(
            lap_number=lap.lap_number,
            stint_lap=lap.lap_number - base + 1,
            lap_time_ms=lap.lap_time_ms,
            tyre_life=100.0 - _max_wear(lap),
            wear=_wear(lap),
            is_out_lap=(opener_is_out_lap and position == 0)
        )
        for position, lap in enumerate(group)
    )


def _is_slow_opener(group: list) -> bool:
    """Whether a run's first lap really is an out-lap - which is to say, slower than the rest of it.

    Following a stop is not enough on its own. In a race the first stored lap of a post-pit run *is*
    the out-lap, carrying the whole pit loss. In practice and qualifying the real out-lap is usually
    not stored at all - no Session History time, or it starts too far past the line - so the first
    stored lap of a run is a *flying* lap, and can be the quickest of the session. Suzuka P1
    (``14040810...``) is the case: its second run opens at 1:33.219, faster than either lap of the
    first, and calling that an out-lap put the wrong label on the best lap of the session.

    Compared against the median of the rest rather than the minimum, so one wild lap inside the run
    cannot suppress the flag.
    """
    first, rest = group[0], group[1:]
    others = [lap.lap_time_ms for lap in rest if lap.lap_time_ms]
    if not first.lap_time_ms or not others:
        return False
    return first.lap_time_ms > median(others)


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
