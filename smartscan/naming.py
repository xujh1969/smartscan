"""Collision-free output naming and idempotent batch detection."""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK = 1024 * 1024


def content_hash(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()[:8]


def next_name(index: int, digest: str) -> str:
    return f"{int(index):03d}_{digest}.png"


def find_existing(metas: list[dict], source: str, digest: str) -> str | None:
    """Only a matching full source path AND content hash counts as done."""
    for meta in metas:
        if meta.get("source") == source and meta.get("digest") == digest:
            return meta.get("path")
    return None


def reserve_name(directory: str | Path, name: str) -> Path:
    """Return a free path. Never overwrite an existing file."""
    folder = Path(directory)
    candidate = folder / name
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    counter = 2
    while True:
        alternative = folder / f"{stem}_{counter}{suffix}"
        if not alternative.exists():
            return alternative
        counter += 1
