"""Compressed on-disk storage for raw UDP capture files.

A capture is archived after recording (see DECISIONS -> storage) and read back trough
``open_capture``, which dispatches on the file's suffix. **Reading is codec-agnostic and
permanent**: ``.f1cap.gz`` archives written befor zstd switch stay importable forever -
a new codec is only ever an addition to the reader, never a replacement. Writing uses
``_DEFAULT_CODEC``.

zstd over gzip for new archives: better ratio and substantially faster (multithreaded), which
matters at ~1.5 GB of raw datagrams per race weekend. ``zstandard`` is imported lazily inside
the zstd branch, so the app and the test suite stay importable without it and a gzip-only user
never needs the dependency (same pattern as pyqtgraph in ``TracePlot``).

``HashingReader`` computes a capture's content hash while its bytes stream past. The hash is
taken over the **decompressed** payload, so it is codec-independent: re-archiving a capture
from gzip to zstd changes every byte on disk but not its identity. That is what makes the hash
usable as the dedupe key for league capture imports (see DECISIONS -> Storage).
"""
from __future__ import annotations

import gzip
import hashlib
import os
import shutil
from pathlib import Path
from typing import BinaryIO

CODEC_NONE = "none"
CODEC_GZIP = "gzip"
CODEC_ZSTD = "zstd"

_GZIP_SUFFIX = ".f1cap.gz"
_ZSTD_SUFFIX = ".f1cap.zst"
_SUFFIXES = {CODEC_GZIP: ".gz", CODEC_ZSTD: ".zst"}

_DEFAULT_CODEC = CODEC_ZSTD
# zstd-3 is 18% smaller than gzip-6 AND 8x faster to write. Ratio curve flattens past
# zstd-10 costs 6x the UPC for 2% less size
_LEVELS = {CODEC_GZIP: 6, CODEC_ZSTD: 3}

RAW_SUFFIX = ".f1cap"
CAPTURE_SUFFIXES = (RAW_SUFFIX, _GZIP_SUFFIX, _ZSTD_SUFFIX)


def capture_codec(path: str | Path) -> str:
    """The codec a capture path is stored in, from its suffix."""
    name = str(path)
    if name.endswith(_ZSTD_SUFFIX):
        return CODEC_ZSTD
    if name.endswith(_GZIP_SUFFIX):
        return CODEC_GZIP
    return CODEC_NONE


def is_compressed_capture(path: str | Path) -> bool:
    return capture_codec(path) != CODEC_NONE


def is_capture_file(path: str | Path) -> bool:
    """Whether a name looks like one of ours - raw or archived, any codec.
    
    Deliberately *not* ``capture_codec(...) != CODEC_NONE``: that answers "how is this
    compressed?" and calls a stray ``.txt`` and uncompressed capture. This answers "is this
    worth looking at at all?", which is what a folder scan needs before it stats or reads anything.
    """
    return str(path).endswith(CAPTURE_SUFFIXES)


def compressed_capture_path(path: str | Path, codec: str = _DEFAULT_CODEC) -> Path:
    """The archive path for a raw capture; an aleady archived path is returned unchanged."""
    source = Path(path)
    if is_compressed_capture(source):
        return source
    try:
        suffix = _SUFFIXES[codec]
    except KeyError:
        raise ValueError(f"cannot write capture codec {codec!r}") from None
    return source.with_name(f"{source.name}{suffix}")


def open_capture(path: str | Path) -> BinaryIO:
    """Open a capture for reading, transparently decompressing gzip and zstd archives."""
    codec = capture_codec(path)
    if codec == CODEC_GZIP:
        return gzip.open(path, "rb")
    if codec == CODEC_ZSTD:
        import zstandard
        
        fh = open(path, "rb")
        try:
            # read_across_frames: tolerate a multi-frame archive; closefd: closing the reader
            # closes the underlying file, so `with open_capture(...)` leaks nothing.
            return zstandard.ZstdDecompressor().stream_reader(
                fh, read_across_frames=True, closefd=True
            )
        except Exception:
            fh.close()
            raise
    return open(path, "rb")  # uncompressed capture


def _open_writer(path: Path, codec: str, level: int | None):
    if codec == CODEC_GZIP:
        return gzip.open(path, "wb", compresslevel=_LEVELS[CODEC_GZIP] if level is None else level)
    if codec == CODEC_ZSTD:
        import zstandard

        fh = open(path, "wb")
        try:
            compressor = zstandard.ZstdCompressor(level=_LEVELS[CODEC_ZSTD] if level is None else level)
            return compressor.stream_writer(fh, closefd=True)
        except Exception:
            fh.close()
            raise
        raise ValueError(f"cannot write capture codec {codec!r}")


def archive_capture(path: str | Path, *, codec: str = _DEFAULT_CODEC, level: int | None = None,
                    remove_original: bool = True) -> Path:
    """Compress a raw capture to ``<name>.<codec-suffix>``, returning the archive path.
    
    Writes to a temp file and ``os.replace``s it into place, so an interrupted archive never
    leaves a half-written file that looks complete. The original is removed only after that
    succeeds. An already-archived path is returned untouched (idempotent).
    """
    source = Path(path)
    if is_compressed_capture(source):
        return source
    if not source.exists():
        raise FileNotFoundError(source)
    
    destination = compressed_capture_path(source, codec=codec)
    if destination.exists():
        raise FileExistsError(f"{destination} already exists; refusing to overwrite and archive")
    
    temp = destination.with_name(f"{destination.name}.tmp")
    try:
        with open(source, "rb") as src, _open_writer(temp, codec, level) as dst:
            shutil.copyfileobj(src, dst)
        os.replace(temp, destination)
        if remove_original:
            source.unlink()
    except Exception:
        if temp.exists():
            temp.unlink()
        raise
    return destination


class HashingReader:
    """A read-only proxy that hashes and counts every byte pulled through it.
    
    Wraps the object from ``open_capture`` so a capture's content hash and payload size come
    free from the ingest read pass - no second decompression of a multi-hundred-MB archive.
    Only ``read``is proxied, which is all ``recording.read_capture`` / ``read_packet`` use. 
    """

    def __init__(self, fh: BinaryIO):
        self._fh = fh
        self._digest = hashlib.sha256()
        self.payload_size = 0
    
    def read(self, size: int = -1) -> bytes:
        data = self._fh.read(size)
        self._digest.update(data)
        self.payload_size += len(data)
        return data
    
    @property
    def content_hash(self) -> str:
        """sha256 of everything read so far; final once the capture is streamed to EOF."""
        return self._digest.hexdigest()


def hash_capture(path: str | Path, *, chunk_size: int = 1 << 20) -> str:
    """The content hash of a capture on disk - the same value ingest computes, without ingesting.

    ``ingest_capture`` gets this free by wrapping its read pass in a :class:`HashingReader`;
    this is that pass on its own, so a folder scan can ask *"is this file one I already know?"*
    without parsing a single packet or touching the database.

    It hashes the **decompressed** payload, so the answer is codec-independent: a capture a
    league member archived as gzip and one re-archived as zstd share an identity even though
    they share no bytes on disk. That is what makes the hash usable as the dedupe key for
    imports and as proof of identity for a capture that moved.

    Costs exactly one decompression pass - seconds on a race weekend, but not free. Callers
    pre-filter on facts that cost a ``stat`` (name, size) so only plausible candidates are read.
    """
    with open_capture(path) as fh:
        reader = HashingReader(fh)
        while reader.read(chunk_size):
            pass
    return reader.content_hash
