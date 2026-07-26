"""Single source of thruth for the app and data-pipeline versions.

``__version__`` is the user-facing SemVer release (CI will stamp it from the git tag in a later
phase.) ``PIPELINE_VERSION`` is an internal integer bumped *only* when ingest starts producing
diffrent or new derived data; it gates the guided re-ingest planned later. Keep the two
independent - a release that changes only UI must not force a re-ingest, and a pipeline change
without a release still needs the bump.
"""
from __future__ import annotations

__version__ = "0.2.0"

# Bump only when ingest output changes (see docs/PACKAGING.md "DB migration & pipeline-version").
PIPELINE_VERSION = 1