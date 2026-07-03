from __future__ import annotations

import gzip
import os
import shutil
from pathlib import Path
from typing import BinaryIO


def is_compressed_capture(path: str | Path) -> bool:
    return str(path).endswith(".f1cap.gz")


def compressed_capture_path(path: str | Path) -> Path:
    source = Path(path)
    if is_compressed_capture(source):
        return source
    return source.with_name(f"{source.name}.f1cap.gz")


def open_capture(path: str | Path,) -> BinaryIO:
    if is_compressed_capture(path):
        return gzip.open(path, "rb")
    return open(path, "rb")


def archive_capture(path: str | Path, *, compresslevel: int = 6, remove_original: bool = True) -> Path:
    source = Path(path)
    if is_compressed_capture(source):
        return source
    if not source.exists():
        raise FileNotFoundError(source)
    
    destination = compressed_capture_path(source)
    if destination.exists():
        raise FileExistsError(f"{destination} already exists; refusing to overwrite and archive")
    
    tmp = destination.with_name(f"{destination.name}.tmp")
    try:
        with open(source, "rb") as src, gzip.open(tmp, "wb", compresslevel=compresslevel) as dst:
            shutil.copyfileobj(src, dst)
        os.replace(tmp, destination)
        if remove_original:
            source.unlink()
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
    return destination