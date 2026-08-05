"""Startup self-check: is this build's optional machinery actually present?

Several of the app's dependencies are imported lazily or shipped as bundled data, which makes them
exactly what a packaging change can silently drop — PyInstaller ships the *fallback* rather than
failing the build, so the app starts fine and only misbehaves later, at the worst moment (a
recorded weekend that won't archive; a lap view offering an "install pyqtgraph" hint). This module
asks the question up front. See docs/PACKAGING.md → "Risks & fallbacks".

Qt-free on purpose: it is testable without a QApplication and can run before one exists. It only
*reports* — what to do about a degraded build is the caller's decision.

**Why the probes are not uniform.** A capability is probed by *importing* it, because that is the
only thing that catches a module which is present but will not load — pyarrow's Windows DLL quirk
is the named example, and ``find_spec`` says yes while the import still fails. The single
exception is pyqtgraph, which is deliberately imported lazily so the app starts quickly; probing
it by import here would undo that for every launch. It is probed with ``find_spec`` instead, which
answers "did the bundle ship it at all" — the packaging regression this module exists for — and
misses only the load-time failure, which is not silent anyway.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib.util import find_spec
from typing import Callable, Sequence

from .paths import resource_path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Capability:
    """One probed capability: whether it resolved, how, and what is lost if it did not."""

    name: str           # stable id, for the log line and tests
    label: str          # user-facing name
    ok: bool
    detail: str          # how it resolved, or why it did not
    consequence: str      # what degrades, only worth showing when ok is False


def _probe_charts() -> Capability:
    """pyqtgraph, probed without importing, so the lazy import stays lazy."""
    found = find_spec("pyqtgraph") is not None
    return Capability(
        name="charts",
        label="Telemetry graphs and track map",
        ok=found,
        detail="pyqtgraph is available" if found else "pyqtgraph is not available (not shipped or failed to load)",
        consequence=(
            "The lap detail page shows an install hint in place of the telemetry graphs and track map."
        )
    )


def _probe_compression() -> Capability:
    """zstandard, a real import: the whole risk is a wheel whose C extension will not load."""
    try:
        import zstandard
    except Exception as exc:
        return Capability(
            name="compression", label="Capture compression", ok=False,
            detail=f"zstandard could not be imported: {type(exc).__name__}: {exc}", 
            consequence=( 
                "New recordings cannot be compressed, and .f1cap.zst captures shared by other "
                "league members cannot be read."
            )
        )
    backend = getattr(zstandard, "backend", "unknown")
    return Capability(
        name="compression", label="Capture compression", ok=True,
        detail=f"zstandard {getattr(zstandard, '__version__', '?')} ({backend} backend)",
        consequence="",
    )


def _probe_traces() -> Capability:
    """pyarrow, a real import and free: main_window.py already pulls it in via storage laps."""
    try:
        import pyarrow
        import pyarrow.parquet      # noqa: F401 - the whole submodule traces are actually written with
    except Exception as exc:
        return Capability(
            name="traces", label="Lap trace storage", ok=False,
            detail=f"pyarrow could not be imported: {type(exc).__name__}: {exc}",
            consequence="Lap traces cannot be written or read, so reading a capture will fail.",
        )
    return Capability(
        name="traces", label="Lap trace storage", ok=True,
        detail=f"pyarrow {getattr(pyarrow, '__version__', '?')}",
        consequence="",
    )


def _probe_flags() -> Capability:
    """The bundled flag SVG. Not an import - a datas entry, which a spec change can drop."""
    try:
        flags_dir = resource_path("ui", "assets", "flags")
        count = len(list(flags_dir.glob("*.svg"))) if flags_dir.is_dir() else 0
    except Exception as exc:
        return Capability(
            name="flags", label="Country flags", ok=False,
            detail=f"the flag assets could not be read: {type(exc).__name__}: {exc}",
            consequence="Result tables and driver standings show no nationality flags.",
        )
    return Capability(
        name="flags", label="Country flags", ok=count > 0,
        detail=(f"{count} flag assets at {flags_dir}" if count 
                else f"no flag assets at {flags_dir}"),
        consequence="Result tables and driver standings show nationality flags.",
    )


_PROBES: tuple[Callable[[], Capability], ...] = (
    _probe_charts, _probe_compression, _probe_traces, _probe_flags
)


def check_capabilities(probes: Sequence[Callable[[], Capability]] = _PROBES) -> tuple[Capability, ...]:
    """Run every probe and return the results, in probe order.
    
    Never raises. A probe that throws is repeated as a failed capability rather than taking the
    start-up path down with it. A self-check that can crash the app is worse than no self-check.
    ``probes`` is injectable so the aggregation is testable without a broken environment.
    """
    results = []
    for probe in probes:
        try:
            results.append(probe())
        except Exception as exc:
            results.append(Capability(
                name=getattr(probe, "__name__", "unknown"),
                label="Unknown component", ok=False,
                detail=f"the check itself failed: {type(exc).__name__}: {exc}",
                consequence="This part of the app may not work.",
            ))
    return tuple(results)


def degraded(capabilities: Sequence[Capability]) -> tuple[Capability, ...]:
    """Only the capabilities that did not resolve."""
    return tuple(c for c in capabilities if not c.ok)


def log_capabilities(capabilities: Sequence[Capability]) -> None:
    """Write one line per capability - WARNING for a degraded one, INFO otherwise.
    
    Always logged, including the healthy case: when a user sends a log, "charts: ok" is the
    line that rules the bundle out, and its absence is itself the finding.
    """
    for cap in capabilities:
        if cap.ok:
            log.info("capability %s: ok - %s", cap.name, cap.detail)
        else:
            log.warning("capability %s: DEGRADED - %s", cap.name, cap.detail)
