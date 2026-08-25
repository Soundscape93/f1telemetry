"""Application-level orchestration: turn a capture file into stored sessions.

`ìngest_capture`` is the parse -> assemble -> persist path that the recording UI runs after
a capture and that the integration test runs against a fixture. It's a plain function (no Qt)
so it can be tested directly; the GUI's ``IngestWorker``is a thin wrapper that calls it on a
background thread and reports the result through signals.
"""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum, auto

from .domain.captures import CaptureMeta
from .domain.models import SessionResult
from .ingest.archive import (CAPTURE_SUFFIXES, HashingReader, archive_capture, capture_codec, hash_capture,
                                is_capture_file, is_compressed_capture, open_capture)
from .ingest.recording import read_header, read_packet
from .protocol.parser import PacketParser
from .protocol.registry import build_registry
from .session.assembler import assemble
from .storage.captures import CaptureStore
from .storage.meta import LEGACY_PIPELINE_VERSION, MetaStore
from .storage.sessions import DeletedSession, SessionStore
from .version import PIPELINE_VERSION

log = logging.getLogger(__name__)


class _CaptureScan:
    """Capture-level facts accumulated while the packets stream past.
    
    Exists so the metadata row costs nothing extra: the hash, sizes, packet count and time span
    all fall out of the read ingest already performs, rather than a second decompression of a
    multi-hundred-MB archive.
    """

    def __init__(self) -> None:
        self._reader: HashingReader | None = None
        self.packet_count = 0
        self.first_recv_time: float | None = None
        self.last_recv_time: float | None = None
        self.session_uids: list[str] = []
    
    def wrap(self, fh) -> HashingReader:
        self._reader = HashingReader(fh)
        return self._reader
    
    def note_packet(self, recv_time: float) -> None:
        self.packet_count += 1
        if self.first_recv_time is None or recv_time < self.first_recv_time:
            self.first_recv_time = recv_time
        if self.last_recv_time is None or recv_time > self.last_recv_time:
            self.last_recv_time = recv_time
    
    def to_meta(self, capture_path: str, recorded_by: str | None) -> CaptureMeta:
        """The metadata row for the scanned capture. Only valid once the stream hit EOF."""
        return CaptureMeta(
            content_hash=self._reader.content_hash if self._reader else "",
            path=os.path.abspath(capture_path),
            file_name=os.path.basename(capture_path),
            file_size=os.path.getsize(capture_path),
            payload_size=self._reader.payload_size if self._reader else 0,
            codec=capture_codec(capture_path),
            packet_count=self.packet_count,
            session_uids=tuple(self.session_uids),
            recorded_by=recorded_by,
            ingested_at=datetime.now(timezone.utc),
            first_packet_at=_as_utc(self.first_recv_time),
            last_packet_at=_as_utc(self.last_recv_time),
        )
    

def _as_utc(recv_time: float | None) -> datetime | None:
    return None if recv_time is None else datetime.fromtimestamp(recv_time, timezone.utc)


def ingest_capture(capture_path: str, store: SessionStore, lap_store=None,
                   capture_store = None, recorded_by: str | None = None) -> list[SessionResult]:
    """Parse a .f1cap file, assemble its session, persists each, and return what was stored.
    
    A single capture can contain several sessions (multiple weekends and/or multiple sessions),
    so this returns a list - on ``SessionResult`` per session the assembler emitted. The Store
    is passed in (not constructed here) so callers control its lifetime and, for SQLite, the
    thread it lives on.

    Each session is stamped with ``recorded_at`` = the wall-clock time of its *earliest* packet
    (the capture's per-packet ``recv_time``), so two attempts of the same session driven within
    one recording get distinct, chronological timestamps. We read the capture directly here
    rather than via ``FileReplaySource`` because we need each packet's ``recv_time``, which that
    source drops.

    Sessions the user has deleted from the store are tombstoned (see ``SessionStore.delete``);
    those uids are skipped here so re-ingesting a capture doesn't resurrect a deliberately
    removed attempt. The returned list therefore covers only the sessions actually stored.

    ``capture_store`` is optional (like ``lap_store``): when given, the capture's metadata is
    recorded so it's queryable without decompressing it again. That row describes the *file* -
    it lists every session the capture contains, including tombstoned ones this call skipped -
    and is keyed by a content hash computed from the bytes as they stream past.
    """
    parser = PacketParser(build_registry())
    earliest: dict[int, float] = {}   # session_uid -> earliest packet recv_time
    scan = _CaptureScan()

    def parsed() -> Iterator:
        with open_capture(capture_path) as fh:
            reader = scan.wrap(fh)
            read_header(reader)
            while (record := read_packet(reader)) is not None:
                scan.note_packet(record.recv_time)
                packet = parser.parse(record.data)
                if packet is None:
                    continue
                uid = packet.header.session_uid
                if uid and record.recv_time < earliest.get(uid, float("inf")):
                    earliest[uid] = record.recv_time        # uid==0 is init noise, ignored downstream
                yield packet
    
    tombstoned = store.deleted_uids()           # sessions the user deleted on purpose - don't resurrect
    saved: list[SessionResult] = []
    for session in assemble(parsed()):
        scan.session_uids.append(str(session.session_uid))      # what the FILE holds, tombstones included
        if session.session_uid in tombstoned:
            continue
        recv_time = earliest.get(session.session_uid)
        if recv_time is not None:
            session = replace(
                session, recorded_at=datetime.fromtimestamp(recv_time, timezone.utc))
        store.save(session)
        if lap_store is not None:
            lap_store.save_laps(session.session_uid, session.laps)
        saved.append(session)

    if capture_store is not None:
        capture_store.record(scan.to_meta(capture_path, recorded_by))
    return saved


def archive_and_ingest(capture_path: str, store: SessionStore, lap_store=None,
                     capture_store = None, recorded_by: str | None = None) -> list[SessionResult]:
    """Archive a raw capture, ingest it, and delete the raw only once ingest succeeds.
     
    The Qt-free orchestration behind ``IngestWorker`` (which is a thin wrapper over this, as it
    is over ``ingest_capture``). The ordering is the safety property (DECISIONS -> Storage):

        1. Compress the raw capture *first*, keeping the original (``remove_original=False``).
        2. Ingest the **archive** - the decompressor verifies its own frame checksum end-to-end as
            the bytes stream past, so a corrupt archive fails the ingest.
        3. Delete the raw only after that succeeds - never before its bytes are proven readable in
            the archive.
    
    So a capture that fails to parse is left as *both* a raw file (for debugging) and a small
    archive (uploadable to the league folder), and the sole readable copy is never destroyed on
    trust. New archives are zstd; ``.gz`` stays readable forever.

    An already-archived input (a re-ingest of a ``.gz`` / ``.zst``) is ingested in place: nothing
    is re-compressed, and nothing is deleted. Archiving is non-fatal - if it fails, the raw is
    ingested directly and kept.

    Returns ``(sessions, archive_path, archive_error)``: ``archive_path`` is the new archive that
    was written ("" when none was - a re-ingest, or an archive failure), and ``archive_error`` a
    message when archiving failed.
    """
    archive_path = ""
    archive_error = ""
    raw_to_delete: str | None = None

    if is_compressed_capture(capture_path):
        ingest_path = capture_path          # re-ingest: already archived, leave it be
    else:
        try:
            # archive first, keeping the raw; the raw is removed only after ingest succeeds
            archive_path = str(archive_capture(capture_path, remove_original=False))
            ingest_path = archive_path
            raw_to_delete = capture_path
        except Exception as exc:
            archive_error = str(exc)           # non-fatal: fall back to ingesting the raw
            ingest_path = capture_path
    
    sessions = ingest_capture(
        ingest_path, store, lap_store=lap_store, capture_store=capture_store,
        recorded_by=recorded_by
    )

    # Ingest read the archive the EOF without error, so the raw's bytes are safe in it.
    if raw_to_delete is not None and os.path.exists(raw_to_delete):
        os.remove(raw_to_delete)
    
    return sessions, archive_path, archive_error


# --- pipeline version gate & guieded re-ingest -------------------------------------------------------------
#
# Three change types decide "must the user re-ingest?" (docs/PACKAGING.md):
#   1. additive schema changes                  -> silent, ``ensure_schema`` on every store reconstruction
#   2. additive + needs values from packets     -> the column exists, but rows are stale;
#                                               THIS is what PIPELINE_VERSION gates
#  3. non-additive                              -> Albemic, deffered unit the first one exists
# Only (2) is handled here. The version is bumped in ``version.py`` when ingest starts producing
# diffrent or new derived data - never for a UI-only release.


class PipelineState(Enum):
    """How a database's derived data relates to this build's ingest pipeline."""

    CURRENT = auto()      # stamped with this build's version - nothing to do
    UPGRADE_AVAILABLE = auto()  # older: this build derives data the stored rows don't have
    AHEAD = auto()        # newer: written by a later build. Re-ingest would DOWNGRADE


@dataclass(frozen=True)
class PipelineCheck:
    """The start-up check comparison result: what the database holds vs what this build produces."""

    state: PipelineState
    stored: int
    current: int


def check_pipeline_version(meta_store: MetaStore, session_store: SessionStore,
                           current: int = PIPELINE_VERSION) -> PipelineCheck:
    """Compare the database's pipeline stamp with this build's, adopting an unstamped one.
    
    Runs *after* ``create_all`` + ``ensure_schema`` (every store does both in its constructor),
    so the silent additive migration always precedes this: the column exists by the time we ask
    whether its values are stale.

    An **unstamped** database is one of two things, and the difference matters:

    * **no sessions** - brand new, nothing has been derived yet, so it is stamped with
      ``current`` immediately. A first launch must never prompt.
    * **has sessions** - it predates the stamp itself, so its rows were derived by an unknown
      older pipeline: treated as :data:`LEGACY_PIPELINE_VERSION` and offered the re-ingest. It
      is deliberately *not* stamped here - only a completed rebuild (or an explicit
      "don't ask again") writes the new value.

    Writing is confined to that one adopt-a-fresh-database case; every other path is read-only.
    """
    stored = meta_store.pipeline_version()
    if stored is None:
        if session_store.stored_uids():      # has sessions, predates the stamp
            stored = LEGACY_PIPELINE_VERSION
        else:                                 # no sessions, adopt the current build's version
            stored = current
            meta_store.set_pipeline_version(current)

    if stored < current:
        state = PipelineState.UPGRADE_AVAILABLE
    elif stored > current:
        state = PipelineState.AHEAD
    else:
        state = PipelineState.CURRENT
    return PipelineCheck(state=state, stored=stored, current=current)


def resolve_capture_path(meta: CaptureMeta, captures_dir: str | os.PathLike | None = None) -> str:
    """Where a known capture's bytes are *now*, or None if the archive can't be found.

    ``CaptureRow.path`` is advisory by design (DECISIONS -> Storage): captures move between
    machines and data roots, and the content hash - not the location - is the identity. So the
    recorded path is tried first, then the app's captures directory under the recorded file
    name. That second lookup covers the case that actually happens: a data root that moved
    (a dev checkout's ``captures/`` vs a frozen build's ``%LOCALAPPDATA%``), or a capture
    ingested from Downloads and later copied into place."""
    if meta.path and os.path.isfile(meta.path):
        return meta.path
    if captures_dir:
        candidate = os.path.join(str(captures_dir), meta.file_name)
        if os.path.isfile(candidate):
            return candidate
    return None


# --- missing-capture prune --------------------------------------------------------------

@dataclass(frozen=True)
class PruneSummary:
    """What one prune pass forgot - and what we deliberately did not."""

    pruned: tuple[str, ...] = ()        # files names whose metadata row was removed
    kept: tuple[str, ...] = ()         # files names that turned up again before the delete


def find_missing_captures(capture_store: CaptureStore,
                          captures_dir: str | os.PathLike | None = None) -> list[CaptureMeta]:
    """Known caputes whose archive :func:`resolve_capture_path` can no longer find.
    
    The read half of the prune, deliberately separated from the write half so the user can be
    shown exactly what would be forgotten before anything is. Purely af filter over
    ``resolve_capture_path``: "missing" means the same thing here as it does to a re-ingest
    (``ReingestSummary.missing``), never a second, stricter option.

    It cannot tell a **deleted** capture from a **moved** one - only that the bytes are not
    where the app looks (``CaptureMeta.path`` is advisory; the content hash is the identity).
    Judging that is the caller's job: the UI warns when *every* capture is missing, which is the
    signature of a captures folder that moved rather than files were deleted.
    """
    return [meta for meta in capture_store.list_captures()
            if resolve_capture_path(meta, captures_dir) is None]


# --- locating captures that moved --------------------------------------------------------------

@dataclass(frozen=True)
class RelocateSummary:
    """What one search-for-moved-captures pass recoveredm and what it still coudn't find."""

    relocated: tuple[tuple[str, str], ...] = ()   # (file name, the path it was found at)
    still_missing: tuple[str, ...] = ()           # file names nothing in the folder matched
    scanned: int = 0                              # capture files seen in the search folder
    hashed: int = 0                              # of those, how many were read to confirm
    errors: tuple[str, ...] = ()                   # "<file name>: <error>" per unreadable file
    cancelled: bool = False


def _walk_captures(root: str | os.PathLike) -> Iterator[str]:
    """Every capture file under ``root``, recursively, in a stable order.

    Recursive because both folders this is ever pointed at are trees: the league's shared folder
    is ``<League>/<Season>/<Round>-<Track>/`` (DECISIONS -> Storage), and a captures folder that
    "moved" has usually moved *into* a subfolder of wherever the user points us. Non-captures are
    rejected by suffix, so walking a large drive costs directory listings and nothing else.
    """
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in sorted(filenames):
            if is_capture_file(name):
                yield os.path.join(dirpath, name)


def relocate_moved_captures(capture_store: CaptureStore, search_dir: str | os.PathLike, *,
                            captures_dir: str | os.PathLike | None = None,
                            on_progress: Callable[[int, int, str], None] | None = None,
                            cancelled: Callable[[], bool] | None = None,
                            hash_file: Callable[[str], str] = hash_capture) -> RelocateSummary:
    """Find captures whose file moved and re-point their metadata at it. **Never** moves a file.

    The missing half of the prune (docs/ROADMAP -> Capture compression), and it belongs *before*
    it: ``find_missing_captures`` can only report that bytes are not where the app looks, and a
    moved capture and a deleted one are identical at the row level. This is the app going to look
    rather than asking the user to give up - so ``prune_missing_captures`` becomes the answer for
    captures that are genuinely gone, instead of the only answer available.

    **Only known-missing captures are hunted for.** The search space is
    ``find_missing_captures``, not the whole ``captures`` table: a row whose file resolves is
    already correct, and re-pointing it at a second copy found on a memory stick would be a
    regression, not a fix.

    **Name and size pre-filter; the content hash decides.** A candidate is read only when its
    ``(basename, size)` matches a missing row - which costs a ``stat`` - and is relocated only
    when the hash of its decompressed payload equals the row's identity. So the pass is cheap on
    a folder full of strangers, and it can never file one recording's metadata against another
    recording's bytes. The cost of that rigour is the one case it cannot solve: a capture that
    was renamed *and* moved never reaches the hash, and stays a job for the prune.

    It **re-points, it does not copy home**: a capture found on an external drive leaves the row
    pointing at that drive, and unplugging it makes the capture missing again. Copying a capture
    into the local captures folder is what the league *import* flow is for; conflating the two
    would silently duplicate hundreds of megabytes behind a button that says "find".

    ``cancelled`` is polled per file, and ``hash_file`` is injectable purely so the tests can
    drive the matching without real multi-hundred-megabyte archives.
    """
    missing = find_missing_captures(capture_store, captures_dir)
    total = len(missing)
    if not missing:
        log.info("Capture search: nothing is missing, nothing to look for")
        return RelocateSummary()

    # (file name, size) -> the missing captures that could be this file. A list, not one value:
    # two recordings can share a name and a size, and only the hash can tell them apart.
    wanted: dict[tuple[str, int], list[CaptureMeta]] = {}
    for meta in missing:
        wanted.setdefault((meta.file_name, meta.file_size), []).append(meta)

    relocated: list[tuple[str, str]] = []
    found_hashes: set[str] = set()
    errors: list[str] = []
    scanned = hashed = 0
    was_cancelled = False

    log.info("Capture search: %d missing capture(s) under %s", total, search_dir)
    for path in _walk_captures(search_dir):
        if not wanted:              # everything we came for has been found
            break
        if cancelled is not None and cancelled():
            was_cancelled = True
            log.info("Capture search cancelled after %d file(s)", scanned)
            break

        scanned += 1
        try:
            size = os.path.getsize(path)
        except OSError:         # vanished or unreadable mid-walk; not our problem
            continue
        candidates = wanted.get((os.path.basename(path), size))
        if not candidates:
            continue                # can't be one of ours - never worth decompressing

        if on_progress is not None:
            on_progress(len(relocated), total, os.path.basename(path))
        try:
            content_hash = hash_file(path)
        except Exception as exc:                # a corrupt candidate must not abort the whole pass
            log.exception("Capture search: could not read candidate %s", path)
            errors.append(f"{os.path.basename(path)}: {exc}")
            continue
        hashed += 1

        match = next((m for m in candidates if m.content_hash == content_hash), None)
        if match is None:
            log.info("Capture search: %s matches a missing capture by name and size but not by "
                     "content - leaving it alone", path)
            continue

        found_at = os.path.abspath(path)
        capture_store.relocate(content_hash, found_at, size, capture_codec(path))
        log.info("Capture search: relocated %s to %s", match.file_name, found_at)
        relocated.append((match.file_name, found_at))
        found_hashes.add(content_hash)
        candidates.remove(match)
        if not candidates:
            wanted.pop((match.file_name, match.file_size), None)

    summary = RelocateSummary(
        relocated=tuple(relocated),
        still_missing=tuple(m.file_name for m in missing
                            if m.content_hash not in found_hashes),
        scanned=scanned,
        hashed=hashed,
        errors=tuple(errors),
        cancelled=was_cancelled,
    )
    log.info("Capture search finished: %s", summary)
    return summary


def prune_missing_captures(capture_store: CaptureStore, content_hashes: Iterable[str],
                           captures_dir: str | os.PathLike | None = None) -> PruneSummary:
    """Forget the metadata of captures whose archive is gone. **Never** touches a file.
    
    Metadata cleanup only: it drops the ``captures`` row (and its ``capture_sessions`` children,
    by cascade) so future re-ingests stop listing an archive that will never come back under
    ``ReingestSummary.missing``. Sessions, Laps, season assignments, rosters and tombestones are
    keyed on ``session_uid`` and not FK'd to ``captures`` (core invariant #4), so standings and
    curation cannot move. And it is recoverarble: if the file ever turns up, importing it records
    the row again - replace-by-hash means nothing is duplicated.

    Every hash is **re-checked here** rather than trusted from the caller's list: a confirmation
    dialog stays open of as long the user takes, and an external drive can be reconnected in
    that time. A capture that resolves again is kept and reported in ``PruneSummary.kept``.
    Unkown hashes are skipped, so the pass is idempotent and safe to repeat.
    """
    pruned: list[str] = []
    kept: list[str] = []
    for content_hash in content_hashes:
        meta = capture_store.get(content_hash)
        if meta is None:                # already forgotten - nothing to do
            continue
        if resolve_capture_path(meta, captures_dir) is not None:
            log.info("Prune: %s turned up again, keeping its metadata", meta.file_name)
            kept.append(meta.file_name)
            continue
        capture_store.delete(content_hash)
        log.info("Prune: forgot %s (last known path: %s)", meta.file_name, meta.path)
        pruned.append(meta.file_name)

    log.info("Prune finished: %d forgotten, %d kept", len(pruned), len(kept))
    return PruneSummary(pruned=tuple(pruned), kept=tuple(kept))


@dataclass(frozen=True)
class ReingestSummary:
    """What one guided re-ingest pass managed to rebuild."""

    captures_total: int
    captures_ingested: int
    sessions_total: int                 # stored sessions when the pass started
    sessions_rebuilt: int               # of those, how many were re-derived from a capture
    missing: tuple[str, ...] = ()       # captures whose archive is gone - unrebuildable
    errors: tuple[str, ...] = ()        # "<file name: error>", one per capture that failed
    cancelled: bool = False

    @property
    def is_complete(self) -> bool:
        """Whether the pass finished cleanly enough to stamp the new PIPELINE_VERSION.

        Missing archives deliberately do NOT block it: nothing the app can ever do will rebuild
        those rows, so refusing to stamp would re-offer the same impossible upgrade on every
        launch. A cancel or a real ingest error does block it - both are worth retrying.
        """
        return not self.cancelled and not self.errors


def reingest_all(capture_store: CaptureStore, session_store: SessionStore, *,
                 lap_store=None,
                 captures_dir: str | os.PathLike | None = None,
                 on_progress: Callable[[int, int, str], None] | None = None,
                 cancelled: Callable[[], bool] | None = None,
                 ingest: Callable[..., list[SessionResult]] = ingest_capture) -> ReingestSummary:
    """Re-derive every stored session from the capture archives ``captures`` enumerates.

    The Qt-free half of the guided re-ingest (docs/PACKAGING.md -> Phase 2); the UI's
    ``ReingestWorker`` is a thin wrapper that runs this on a background thread and forwards
    ``on_progress`` as Qt signals - the same split as ``archive_and_ingest`` / ``IngestWorker``.

    **Idempotent and resumable by construction**, so a cancelled or half-finished pass costs
    nothing and can simply be run again: ``ingest_capture`` replaces by ``session_uid`` and
    ``CaptureStore.record`` by content hash, while season assignments, rosters and tombstones
    are keyed on the uid and deliberately not FK'd to ``sessions`` (core invariant #4) - so
    rebuilding derived rows never touches standings, round placements or curation. Sessions the
    user deleted stay deleted: ingest skips tombstoned uids.

    Archives are ingested **in place** (``ingest_capture``, not ``archive_and_ingest``): nothing
    is re-compressed, and a re-ingest never deletes a file. ``recorded_by`` is fed back from the
    existing metadata row - it isn't in the capture file, so this is the only thing that keeps a
    re-ingest from erasing it.

    ``cancelled`` is a zero-arg predicate polled *between* captures: a capture is never
    interrupted half-way, so the store is never left holding a partial session. ``ingest`` is
    injectable purely so the tests can drive the accounting without a real capture.
    """
    captures = capture_store.list_captures()
    total = len(captures)
    stored_before = session_store.stored_uids()
    rebuilt: set[int] = set()
    missing: list[str] = []
    errors: list[str] = []
    ingested = 0
    was_cancelled = False

    log.info("Re-ingest starting: %d captures, %d stored sessions", total, len(stored_before))
    for index, meta in enumerate(captures, start=1):
        if cancelled is not None and cancelled():
            was_cancelled = True
            log.info("Re-ingest cancelled at %d of %d captures", index - 1, total)
            break
        if on_progress is not None:
            on_progress(index, total, meta.file_name)

        path = resolve_capture_path(meta, captures_dir)
        if path is None:
            log.info("Re-ingest: no archive found for %s (last known path: %s)",
                     meta.file_name, meta.path)
            missing.append(meta.file_name)
            continue
        try:
            sessions = ingest(path, session_store, lap_store=lap_store,
                              capture_store=capture_store, recorded_by=meta.recorded_by)
        except Exception as exc:                    # one bad archive must not abort the whole pass
            log.exception("Re-ingest failed for %s", path)
            errors.append(f"{meta.file_name}: {exc}")
            continue
        rebuilt.update((int(s.session_uid) for s in sessions))
        ingested += 1

    summary = ReingestSummary(
        captures_total=total,
        captures_ingested=ingested,
        sessions_total=len(stored_before),
        sessions_rebuilt=len(rebuilt & stored_before),
        missing=tuple(missing),
        errors=tuple(errors),
        cancelled=was_cancelled,
    )
    log.info("Re-ingest finished: %s", summary)
    return summary


# --- league capture import --------------------------------------------------------------
#
# The other half of the capture-as-interchange design (DECISIONS -> Storage): a member drops a 
# recording in the shared folder, an admin pulls it into their own database. Read and write are
# split the way the prune is - `find_missing_captures`is what the user is shown and
# `import_captures` is what acts - so hundreds of megabytes are never copied before a human said
# yes. Placed at the end of the module rather than beside `archive_and_ingest` purely so it can
# call `resolve_capture_path`and `_walk_captures` without forward references.

@dataclass(frozen=True)
class ImportCandidate:
    """A file in the source folder that looks like a capture this database doesn't have."""

    path: str
    file_name: str
    file_size: int


@dataclass(frozen=True)
class ImportSummary:
    """What one import pass brought in and what it deliberately did not."""

    imported: tuple[str, ...] = ()                 # copied in and ingested
    sessions_stored: int = 0                       # sessions those captures added to the database
    recovered: tuple[str, ...] = ()                 # already known, but the local archive had gone missing
    updated: tuple[str, ...] = ()                   # already known and present; only "recorded_by" changed
    skipped: tuple[str, ...] = ()                   # already imported and still present; nothing to do
    errors: tuple[str, ...] = ()                    # "<file name>: <error>", one per capture that failed
    cancelled: bool = False


def find_importable_captures(source_dir: str | os.PathLike, capture_store: CaptureStore) -> list[ImportCandidate]:
    """Captures in ``source_dir`` that look new, cheaply enough to run before asking the user.

    The read half of the import: a recursive walk, one ``stat`` per capture file, and a single
    ``known_files()`` query - no archive is opened, so this is fast enough to run synchronously
    on a shared drive and report a count and a size before any thread starts.

    ``(file name, size)`` is a **pre-filter, not a decision**. It exists to avoid decompressing
    a folder the admin has already imported five times; the content hash in
    :func:`import_captures` is what actually rules on identity, so a capture renamed along the
    way costs one wasted read rather than becoming a duplicate. The inverse - two genuinely
    different recordings sharing a name *and* a byte-exact size - would be skipped, which is why
    the pre-filter is only safe given the game's timestamp naming and multi-hundred-megabyte
    files.
    """
    known = capture_store.known_files()
    candidates: list[ImportCandidate] = []
    for path in _walk_captures(source_dir):
        try:
            size = os.path.getsize(path)
        except OSError:         # vanished or unreadable mid-walk
            continue
        name = os.path.basename(path)
        if (name, size) in known:
            continue
        candidates.append(ImportCandidate(path=path, file_name=name, file_size=size))
    log.info("Import scan: %d candidate(s) in %s", len(candidates), source_dir)
    return candidates


def _split_capture_name(file_name: str) -> tuple[str, str]:
    """``("20260802_210340", "f1cap.zst").
    
    Not ``os.path.splitext``: a capture suffix is two parts, so that would cut in the wrong place
    and strand ``.f1cap``in a stem.
    """
    for suffix in CAPTURE_SUFFIXES:
        if file_name.endswith(suffix):
            return file_name[: -len(suffix)], suffix
    return file_name, ""


def _unique_destination(directory: str, file_name: str) -> str:
    """A path in ``directory`` for ``file_name`` that doesn't exist yet.

    A name clash here is **not** a duplicate import - the content hash has already said this is a
    recording we don't hold. It means two different recordings share a name, which the game's
    timestamp naming makes rare but not impossible when two members record the same race. So the
    incoming file is numbered rather than either overwriting what's there or being dropped.
    """
    destindation = os.path.join(directory, file_name)
    if not os.path.exists(destindation):
        return destindation
    stem, suffix = _split_capture_name(file_name)
    counter = 2
    while True:
        candidate = os.path.join(directory, f"{stem}-{counter}{suffix}")
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def _is_inside(path: str, directory: str) -> bool:
    """Whether ``path`` already lives under ``directory``, symlinks resolved."""
    root = os.path.realpath(directory)
    try:
        return os.path.commonpath([root, os.path.realpath(path)]) == root
    except ValueError:        # drives differ on Windows
        return False


def _copy_capture(candidate: ImportCandidate, captures_dir: str) -> str:
    """Copy a capture into the local captures folder and return where it landed.

    Copy-home is the point, not an optimisation (DECISIONS -> Storage): the shared drive is
    **transport** and the local archive is the **home**, so nothing in the database is ever left
    pointing at a folder that syncs, disconnects, or gets tidied up by somebody else. The source
    file is never touched, moved or deleted.

    **A capture that is already inside the captures folder is ingested in place.** Importing from
    any folder that *contains* the data root - a home directory, a whole drive - otherwise makes
    the app copy its own archive beside itself under a ``-2`` name, which is pure waste. Reading
    it in place also makes "point the importer at your own captures folder" a legitimate way to
    pick up a loose capture that was never ingested.

    Written to a ``.part`` name and ``os.replace``d into place - the same guarantee
    ``archive_capture`` gives, so an interrupted copy can't leave a half-written file that looks
    like a whole capture.
    """
    if _is_inside(candidate.path, captures_dir):
        return candidate.path

    destination = _unique_destination(captures_dir, candidate.file_name)
    temp = f"{destination}.part"
    try:
        shutil.copy2(candidate.path, temp)
        os.replace(temp, destination)
    except Exception:
        if os.path.exists(temp):
            os.remove(temp)
        raise
    return destination


def import_captures(candidates: Iterable[ImportCandidate], capture_store: CaptureStore, 
                    session_store: SessionStore, *, captures_dir: str | os.PathLike,
                    lap_store=None, recorded_by: str | None = None,
                    on_progress: Callable[[int, int, str], None] | None = None,
                    cancelled: Callable[[], bool] | None = None,
                    hash_file: Callable[[str], str] = hash_capture,
                    ingest: Callable[..., list[SessionResult]] = ingest_capture) -> ImportSummary:
    """Copy league captures into the local captures folder and ingest them.

    Takes the candidate *list* rather than a folder - like ``prune_missing_captures`` taking
    hashes - because what runs must be exactly what the user was shown and agreed to, not a
    second scan that might have found something else in the meantime.

    Each candidate is hashed first, which decides between four outcomes:

    * **new** - copied home and ingested. The capture row lands pointing at the local copy.
    * **known, and the local archive is still there** - skipped. Re-syncing a shared folder is a
      no-op, which is the whole reason the metadata table is keyed on a content hash.
    * **known, but the local archive has gone missing** - copied home and the row ``relocate``d.
      The shared folder is a backup of last resort, and this is the one path that uses it as one.
      Deliberately *not* re-ingested: the derived rows are already there, and rebuilding them is
      what "Re-read captures" is for.
    * **known, and only ``recorded_by`` differs** - updated in place. Without this, "already
      imported" would mean the value could never be corrected (DECISIONS -> Storage).

    ``recorded_by`` is optional and is the importer's claim about the file, not something the
    file asserts (PRIORITIES -> Cycle 2). Blank is a perfectly good answer and never overwrites a
    stored value.

    **A capture that fails to ingest keeps its local copy**, unlike ``archive_and_ingest``, which
    deletes a raw only once its bytes are proven. Nothing is at risk here - the source in the
    shared folder is untouched either way - and a capture that won't parse is precisely the one
    the admin wants a local copy of to look at.

    ``cancelled`` is polled *between* captures, so a copy or an ingest is never interrupted
    half-way. ``hash_file`` and ``ingest`` are injectable purely so the tests can drive the
    decision table without multi-hundred-megabyte archives.
    """
    candidates = list(candidates)
    total = len(candidates)
    captures_dir = str(captures_dir)
    os.makedirs(captures_dir, exist_ok=True)

    imported: list[str] = []
    recovered: list[str] = []
    updated: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    sessions_stored = 0
    was_cancelled = False

    log.info("Import starting: %d candidate(s) into %s", total, captures_dir)
    for index, candidate in enumerate(candidates, start=1):
        if cancelled is not None and cancelled():
            was_cancelled = True
            log.info("Import cancelled at %d of %d", index - 1, total)
            break
        if on_progress is not None:
            on_progress(index, total, candidate.file_name)

        try:
            content_hash = hash_file(candidate.path)
        except Exception as exc:                    # unreadable source: skip it, keep going
            log.exception("Import: could not read %s", candidate.path)
            errors.append(f"{candidate.file_name}: {exc}")
            continue

        known = capture_store.get(content_hash)
        if known is not None and resolve_capture_path(known, captures_dir) is not None:
            if recorded_by and recorded_by != known.recorded_by:
                capture_store.set_recorded_by(content_hash, recorded_by)
                log.info("Import: %s is already held; updated recorded_by", candidate.file_name)
                updated.append(candidate.file_name)
            else:
                log.info("Import: %s is already held, skipping", candidate.file_name)
                skipped.append(candidate.file_name)
            continue

        try:
            destination = _copy_capture(candidate, captures_dir)
        except Exception as exc:
            log.exception("Import: could not copy %s", candidate.path)
            errors.append(f"{candidate.file_name}: {exc}")
            continue

        if known is not None:
            # Known, but the local archive was gone - take the shared copy as the new home.
            # A RECOVERY, not a skip: a file really was copied and the row now points at it.
            capture_store.relocate(content_hash, destination,
                                   os.path.getsize(destination), capture_codec(destination))
            if recorded_by and recorded_by != known.recorded_by:
                capture_store.set_recorded_by(content_hash, recorded_by)
            log.info("Import: recovered missing archive %s from the shared folder",
                     os.path.basename(destination))
            recovered.append(os.path.basename(destination))
            continue


        try:
            sessions = ingest(destination, session_store, lap_store=lap_store,
                              capture_store=capture_store, recorded_by=recorded_by)
        except Exception as exc:                    # one bad archive must not abort the whole folder
            log.exception("Import: could not ingest %s", destination)
            errors.append(f"{candidate.file_name}: {exc}")
            continue
        sessions_stored += len(sessions)
        log.info("Import: %s -> %s (%d session(s))", candidate.file_name, destination, len(sessions))
        imported.append(os.path.basename(destination))

    summary = ImportSummary(
        imported=tuple(imported),
        sessions_stored=sessions_stored,
        recovered=tuple(recovered),
        updated=tuple(updated),
        skipped=tuple(skipped),
        errors=tuple(errors),
        cancelled=was_cancelled,
    )
    log.info("Import finished: %s", summary)
    return summary


# --- deleting a stored session --------------------------------------------------------------

@dataclass(frozen=True)
class DeleteOutcome:
    """What one guarded delete did, or refused to do and why."""

    deleted: bool
    session_uid: int
    season_id: int | None = None
    round_number: int | None = None
    laps_removed: int = 0

    @property
    def refused_assigned(self) -> bool:
        """Whether the delete was refused because the session sits in a season round.
        
        The one case a caller must tell apart fom an ordinary miss: both leave ``deleted``
        False, but only this one is worth reporting - and only this one is fixable by the user
        (unassing, then delete).
        """
        return not self.deleted and self.season_id is not None


def delete_session(session_uid: int, session_store: SessionStore, season_store, * ,
                   lap_store=None) -> DeleteOutcome:
    """Delete a stored session and its laps, refusing while it is assigned to a season round.

    The single write point for deleting a session, and the enforcer of the invariant
    ``SessionStore.delete``'s docstring used to merely assert. It lives here rather than on the
    store because the guard needs the *season* aggregate, and a store must not import a sibling
    store (repository-per-aggregate) - so this sits with the other multi-store orchestration,
    beside ``reingest_all`` and ``import_captures``.

    **Refuses rather than cleans up.** ``season_assignments`` is deliberately not FK'd to
    ``sessions`` (core invariant #4) precisely so a re-ingest cannot wipe a manual round
    placement; a delete must not either. Dropping the assignment on the way out would silently
    remove a result from the standings, and delete's whole premise - the capture survives, so
    the session can come back - would not hold for the placement, which nothing would restore.
    Refusing costs the user one Unassign click and is reversible; cleanup is not.

    Laps go with the session. Nothing else calls ``LapStore.delete``, so without this a deleted
    session left its lap rows and its Parquet traces under ``lap_traces/<uid>/`` forever -
    invisible, because the laps overview iterates *stored* sessions, but still on disk.
    ``lap_store`` is optional only so a caller that has none (tests, a future headless path) can
    still delete; pass it wherever one exists.
    """
    uid = int(session_uid)
    placement = season_store.assignment_for(uid)
    if placement is not None:
        season_id, round_number = placement
        log.info("Refusing to delete session %s: assigned to season %s round %s", 
                 uid, season_id, round_number)
        return DeleteOutcome(deleted=False, session_uid=uid,
                             season_id=season_id, round_number=round_number)

    if not session_store.delete(uid):
        log.info("Delete: no stored session %s", uid)
        return DeleteOutcome(deleted=False, session_uid=uid)

    laps_removed = lap_store.delete(str(uid)) if lap_store is not None else 0
    log.info("Deleted session %s (%d lap row(s), traces removed)", uid, laps_removed)
    return DeleteOutcome(deleted=True, session_uid=uid, laps_removed=laps_removed)


# --- restoring a deleted session --------------------------------------------------------------
#
# Restore is not "clear the tombstone": ``SessionStore.restore`` only does that half, and a
# cleared tombstone with no session row is a *worse* state than a deleted session (the next full
# re-ingest resurrects it silently). The feature is a single-capture re-ingest - find a capture
# that holds the uid, clear the tombstone, ingest that one file - because ``ingest_capture``
# replaces by uid, so one file holding it is sufficient and idempotent. Rebuilding one session by
# decompressing every archive in the database is what the guided re-ingest under Help is for.


class RestoreProblem(Enum):
    """Why a restore could not go ahead - the one thing the caller must tell apart."""

    NOT_DELETED = auto()           # the uid isn't tombstoned; there is nothing to bring back
    NO_CAPTURE_ROW = auto()         # nothing records which file held it -> only Forget can help
    ARCHIVE_MISSING = auto()        # the capture is known, but its bytes can't be found
    AMBIGUOUS_CAPTURE = auto()      # several findable captures and no content_hash: ask first
    INGEST_FAILED = auto()          # ingest raised; the tombstone was rolled back
    NOT_IN_CAPTURE = auto()         # ingest worked, but the file didn't hold the uid after all


@dataclass(frozen=True)
class RestoreOutcome:
    """What one restore attempt did, or refused to do and why.

    ``reason`` is an enum, never a message: the wording belongs to the UI, which has two quite
    different things to say about a missing archive (try Help -> Find moved captures...) and about
    a session no capture row mentions at all (Forget is the only way out). ``error`` carries the
    ingest exception, and only that - every other refusal is fully described by ``reason``.
    """

    restored: bool
    session_uid: int
    capture_name: str = ""              # the capture used, or the one that could not be found
    reason: RestoreProblem | None = None
    error: str = ""                     # the ingest failure's text; INGEST_FAILED only


def _ingest_order(meta: CaptureMeta) -> datetime:
    """Sort key for "newest ingest first", tolerant of the two shapes an ingest stamp arrives in.

    SQLite hands datetimes back **naive** while a freshly built ``CaptureMeta`` carries an aware
    one, and the column is nullable - so comparing them raw raises ``can't compare offset-naive
    and offset-aware datetimes`` the moment an unstamped row shares a list with a stored one.
    Everything is written as UTC, so normalizing to naive UTC orders correctly; a row with no
    stamp sorts oldest rather than taking the chooser down with it.
    """
    stamp = meta.ingested_at
    if stamp is None:
        return datetime.min
    return stamp.astimezone(timezone.utc).replace(tzinfo=None) if stamp.tzinfo else stamp


def restorable_captures(session_uid: int, capture_store: CaptureStore,
                        captures_dir: str | os.PathLike | None = None) -> list[tuple[CaptureMeta, str]]:
    """``(capture, path)`` for every known capture holding ``session_uid`` whose archive is findable.

    Newest ``ingested_at`` first. Shared on purpose: :func:`restore_session` resolves through it,
    and the deleted-sessions view offers exactly this list when more than one capture holds the
    uid. Two copies of a session are usually a member's original plus an imported copy, but they
    can differ in completeness (someone stopped recording early) and nothing here can tell which
    is better without decompressing both - so the choice is the user's, and both halves of the app
    must agree on what there is to choose from. A page computing its own list would eventually
    offer a file that restore then refuses as missing.
    """
    found: list[tuple[CaptureMeta, str]] = []
    for meta in sorted(capture_store.for_session(str(session_uid)), key=_ingest_order, reverse=True):
        path = resolve_capture_path(meta, captures_dir)
        if path is not None:
            found.append((meta, path))
    return found


def _re_tombstone(session_store: SessionStore, tomb: DeletedSession, lap_store=None) -> None:
    """Put a failed restore's tombstone back exactly as it was - the rollback this design exists for.

    Two half-states are possible once the tombstone has been cleared, and both are covered here:

    * **cleared, no session row** - the ordinary failure (a corrupt archive, a capture that turned
      out not to hold the uid). ``delete()`` writes nothing when there is no row, so the tombstone
      has to be re-written directly.
    * **cleared, row present** - a capture holding several sessions where ours was saved before a
      later one raised. ``delete()`` removes the resurrected row, and its laps go with it exactly
      as they do in :func:`delete_session`; nothing else calls ``LapStore.delete``.

    ``tombstone()`` runs last in both cases, with the original values, so the end state is
    identical to before the attempt - including ``deleted_at``, which must not jump to "just now"
    because a restore failed.
    """
    if session_store.delete(tomb.session_uid) and lap_store is not None:
        lap_store.delete(str(tomb.session_uid))
    session_store.tombstone(tomb.session_uid, track_id=tomb.track_id, 
                            session_type=tomb.session_type, recorded_at=tomb.recorded_at,
                            deleted_at=tomb.deleted_at)


def restore_session(session_uid: int, session_store: SessionStore, capture_store: CaptureStore, *, 
                    lap_store=None, content_hash: str | None = None, 
                    captures_dir: str | os.PathLike | None = None,
                    ingest: Callable[..., list[SessionResult]] = ingest_capture) -> RestoreOutcome:
    """Bring a deleted session back by re-ingesting one capture that holds it, or refuse honestly.

    The Qt-free half of Restore; ``RestoreWorker`` is a thin wrapper that runs it on a background
    thread, the same split as ``reingest_all`` / ``ReingestWorker``. ``ingest`` is injectable for
    the same reason: the ordering and the rollback are testable without a real archive.

    **The ordering is the safety property.** ``ingest_capture`` reads ``deleted_uids()`` at the
    *start*, so the tombstone must be cleared before ingesting - which opens a window where the
    uid is un-tombstoned with no session row. Everything that can be decided is therefore decided
    *before* the tombstone is touched (is it deleted at all, is there a capture row, can its
    archive be found, is the choice unambiguous), and anything that fails after it has been
    cleared rolls back through :func:`_re_tombstone`. A restore either completes or leaves the
    database exactly as it found it; it never half-succeeds.

    **The capture is verified, not assumed.** ``capture_sessions`` rows can be stale - pruned,
    re-recorded, or written by an older ingest - so the returned sessions are checked for the uid
    rather than trusting the row that pointed here. Passing ``capture_store`` through to the
    ingest also *corrects* such a row as a side effect (``record`` replaces by hash with what the
    file actually holds), so a ``NOT_IN_CAPTURE`` refusal leaves the session honestly shown as
    having no capture, and Forget as its way out.

    ``content_hash`` picks one capture when several hold the uid; without it, several findable
    captures are refused as ``AMBIGUOUS_CAPTURE`` rather than guessed at - see
    :func:`restorable_captures`.
    """
    uid = int(session_uid)
    # One read serves three purposes: the "is it even deleted?" gate, and the track/type/deleted_at
    # values the rollback has to put back - which are unreadable once the tombstone is cleared.
    tomb = next((row for row in session_store.deleted_sessions() if row.session_uid == uid), None)
    if tomb is None:
        log.info("Restore: session %s is not deleted", uid)
        return RestoreOutcome(restored=False, session_uid=uid, reason=RestoreProblem.NOT_DELETED)
    
    found = restorable_captures(uid, capture_store, captures_dir)
    if content_hash is not None:
        found = [(meta, path) for meta, path in found if meta.content_hash == content_hash]
    if not found:
        # Nothing to ingest - but *why* decides what the user can do about it, so tell the two
        # apart with the one extra read that costs nothing on the failure path.
        known = capture_store.for_session(str(uid))
        if content_hash is not None:
            known = [meta for meta in known if meta.content_hash == content_hash]
        if not known:
            log.info("Restore: no capture recorded for session %s", uid)
            return RestoreOutcome(restored=False, session_uid=uid, 
                                  reason=RestoreProblem.NO_CAPTURE_ROW)
        newest = max(known, key=_ingest_order)
        log.info("Restore: capture %s for session %s is missing (%s)", uid, newest.file_name)
        return RestoreOutcome(restored=False, session_uid=uid, capture_name=newest.file_name,
                              reason=RestoreProblem.ARCHIVE_MISSING)
    if len(found) > 1:
        log.info("Restore: %d captures hold session %s, you must pick one", len(found), uid)
        return RestoreOutcome(restored=False, session_uid=uid, 
                              reason=RestoreProblem.AMBIGUOUS_CAPTURE)

    meta, path = found[0]
    session_store.restore(uid)        # from here on, every exit either succeeds or rolls back
    try:
        sessions = ingest(path, session_store, lap_store=lap_store,
                          capture_store=capture_store, recorded_by=meta.recorded_by)
    except Exception as exc:            # a failed restore must not leave the uid un-tombstoned
        log.exception("Restore failed for session %s from %s", uid, path)
        _re_tombstone(session_store, tomb, lap_store)
        return RestoreOutcome(restored=False, session_uid=uid, capture_name=meta.file_name,
                              reason=RestoreProblem.INGEST_FAILED, error=str(exc))

    if uid not in {int(session.session_uid) for session in sessions}:
        log.info("Restore: %s does not hold session %s after all", meta.file_name, uid)
        _re_tombstone(session_store, tomb, lap_store)
        return RestoreOutcome(restored=False, session_uid=uid, capture_name=meta.file_name,
                              reason=RestoreProblem.NOT_IN_CAPTURE)

    log.info("Restored session %s from %s", uid, meta.file_name)
    return RestoreOutcome(restored=True, session_uid=uid, capture_name=meta.file_name)
