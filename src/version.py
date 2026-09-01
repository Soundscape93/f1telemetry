"""Single source of truth for the app and data-pipeline versions.

``__version__`` is the user-facing SemVer release. It is bumped by ``packaging/bump_version.py``
when the release PR is labelled, and lands as a real commit *before* the tag exists; CI only
**verifies** that the tag, this file and ``pyproject.toml`` agree (``packaging/check_version.py``)
and never stamps it, so the published artifact is exactly the tagged commit.

``PIPELINE_VERSION`` is an internal integer bumped *only* when ingest starts producing different
or new derived data; it gates the guided re-ingest. Keep the two independent - a release that
changes only UI must not force a re-ingest, and a pipeline change without a release still needs
the bump. See docs/PACKAGING.md.
"""
from __future__ import annotations

__version__ = "0.9.0"

# Bump only when ingest output changes (see docs/PACKAGING.md "DB migration & pipeline-version").
# 2: classification entries carry ``is_ai`` (AI vs human), so league standings stop confusing
# drivers with the same race number
# 3: sessions carry ``ai_difficulty`` from the Session packet; rows ingested before this read 0
# 4: laps carry their context - ``driver_status`` / ``pit_status`` from Lap Data, the computed
#    garage, out-lap and in-lap flags, and the Session packet's safety-car and red-flag state;
#    rows ingested before this read None and fall back to the fuel/stint-shape inference
# 5: sessions carry their Event packets - the whole field's penalties (type, infringement, lap and
#    time) and the on-track passes between two racing cars; sessions ingested before this hold none
#    at all, so empty reads as "not captured" and never as "nothing happened". Also the conditions
#    at session start - track and air temperature and the in-game clock - read from the first
#    Session packet past the settle window; rows ingested before this read None for all three.
#    Both landed under one number: 5 was never released, so a released user pays one prompt for
#    the pair (see PACKAGING -> "When to bump")
PIPELINE_VERSION = 5
