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

__version__ = "0.7.0"

# Bump only when ingest output changes (see docs/PACKAGING.md "DB migration & pipeline-version").
# 2: classification entries carry ``is_ai`` (AI vs human), so league standings stop confusing
# drivers with the same race number
PIPELINE_VERSION = 2