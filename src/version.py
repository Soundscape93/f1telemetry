"""Single source of thruth for the app and data-pipeline versions.

``__version__`` is the user-facing SemVer release (CI will stamp it from the git tag in a later
phase.) ``PIPELINE_VERSION`` is an internal integer bumped *only* when ingest starts producing
different or new derived data; it gates the guided re-ingest planned later. Keep the two
independent - a release that changes only UI must not force a re-ingest, and a pipeline change
without a release still needs the bump.
"""
from __future__ import annotations

__version__ = "0.2.0"

# Bump only when ingest output changes (see docs/PACKAGING.md "DB migration & pipeline-version").
# 2: classification entries carry ``is_ai`` (AI vs human), so league standings stop confusing
# drivers with the same race number
PIPELINE_VERSION = 2