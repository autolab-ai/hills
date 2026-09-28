"""git-LFS pointer parsing, classification, and verification (hills 0.12).

Authoritative scoring must never be fooled by a mis-smudged or malformed pointer, so
we parse the canonical pointer format strictly and verify the evaluator-visible bytes
against the pointer's ``oid`` (sha256) and ``size``. Extension pointers (``ext-*``)
are rejected: an extension's ``oid`` can describe transformed *stored* bytes rather
than the final smudged bytes, which would make the sha256 check invalid.

Pointer spec: https://github.com/git-lfs/git-lfs/blob/main/docs/spec.md
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from hills.errors import LfsError

POINTER_VERSION = "https://git-lfs.github.com/spec/v1"
# The canonical pointer is small; anything larger is not a pointer.
MAX_POINTER_BYTES = 1024
_OID_RE = re.compile(r"^sha256:([0-9a-f]{64})$")
_ALLOWED_KEYS = frozenset({"version", "oid", "size"})
_READ_CHUNK = 1 << 20


@dataclass(frozen=True)
class LfsPointer:
    oid: str  # sha256 hex (64 chars)
    size: int


def parse_pointer(data: bytes) -> LfsPointer | None:
    """Strictly parse a git-LFS pointer blob.

    Returns the pointer, or ``None`` if the blob is not a pointer at all. Raises
    :class:`LfsError` if it *is* a pointer (declares the LFS version) but is
    malformed, uses an unsupported extension, or carries unknown keys.
    """
    if not data or len(data) > MAX_POINTER_BYTES:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]  # canonical pointers are LF-terminated
    if not lines:
        return None

    kv: dict[str, str] = {}
    for line in lines:
        key, sep, val = line.partition(" ")
        if not sep or not key:
            # Not "key value": this is not a canonical pointer line.
            return None
        if key in kv:
            raise LfsError("git-LFS pointer has a duplicate key")
        kv[key] = val

    if kv.get("version") != POINTER_VERSION:
        return None  # not a (recognized) pointer
    if any(k.startswith("ext-") for k in kv):
        raise LfsError("git-LFS extension pointers (ext-*) are not supported")
    unknown = set(kv) - _ALLOWED_KEYS
    if unknown:
        raise LfsError(f"git-LFS pointer has unexpected keys: {sorted(unknown)}")

    m = _OID_RE.match(kv.get("oid", ""))
    if not m:
        raise LfsError("git-LFS pointer is missing a valid sha256 oid")
    try:
        size = int(kv["size"])
    except (KeyError, ValueError):
        raise LfsError("git-LFS pointer is missing a valid size") from None
    if size < 0:
        raise LfsError("git-LFS pointer has a negative size")
    return LfsPointer(oid=m.group(1), size=size)


def looks_like_pointer(data: bytes) -> bool:
    """Cheap check: does the blob declare the LFS pointer version? (Used only to
    flag an ambiguous non-LFS-attributed blob; classification uses gitattributes.)"""
    head = data[:MAX_POINTER_BYTES]
    return head.startswith(b"version " + POINTER_VERSION.encode())


def verify_object(path: Path, pointer: LfsPointer) -> None:
    """Hard-fail unless ``path`` holds the real smudged bytes for ``pointer``.

    The size and sha256 are the integrity test — a still-pointer file simply fails
    them. Raises :class:`LfsError` with actionable text on any mismatch.
    """
    if path.is_symlink() or not path.is_file():
        raise LfsError(f"{path}: expected a regular file for LFS object {pointer.oid}")
    actual_size = path.stat().st_size
    if actual_size != pointer.size:
        raise LfsError(
            f"{path}: size {actual_size} != pointer size {pointer.size} "
            f"(unresolved LFS object {pointer.oid}? run `git lfs pull`)"
        )
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_READ_CHUNK), b""):
            h.update(chunk)
    actual = h.hexdigest()
    if actual != pointer.oid:
        raise LfsError(
            f"{path}: sha256 {actual} != pointer oid {pointer.oid} "
            "(unresolved or corrupt LFS object? run `git lfs pull`)"
        )
