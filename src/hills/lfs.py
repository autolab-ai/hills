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
_VERSION_LINE = f"version {POINTER_VERSION}"
# The spec requires a pointer to be strictly less than 1024 bytes.
MAX_POINTER_BYTES = 1024
_OID_RE = re.compile(r"^sha256:([0-9a-f]{64})$")
_SIZE_RE = re.compile(r"^(0|[1-9][0-9]*)$")  # canonical decimal, no sign, no leading zero
_READ_CHUNK = 1 << 20


@dataclass(frozen=True)
class LfsPointer:
    oid: str  # sha256 hex (64 chars)
    size: int


def parse_pointer(data: bytes) -> LfsPointer | None:
    """Parse a blob as a git-LFS pointer, accepting ONLY the unique canonical
    serialization (the spec's normalized form git-lfs itself writes).

    Returns the pointer, or ``None`` for any blob that is not a canonical basic
    pointer -- so this is safe to call on arbitrary blobs (README, code) to *detect*
    a pointer. It raises :class:`LfsError` only for a canonical-looking pointer that
    uses an unsupported extension (``ext-*``), whose oid may not equal the smudged
    bytes and so must never be silently treated as data.

    Canonical form (spec): total < 1024 bytes, one entry per line, ``key value`` with a
    single space, LF line endings incl. a trailing LF, first line ``version``, the
    remaining keys sorted alphabetically, each key once. Basic pointers carry exactly
    ``version``/``oid``/``size``; ``oid`` is ``sha256:<64 hex>``; ``size`` is a
    canonical decimal integer.
    """
    if not data or len(data) >= MAX_POINTER_BYTES:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    # Must be a pointer (version-first) AND LF-terminated to be canonical.
    if not text.startswith(_VERSION_LINE + "\n") or not text.endswith("\n"):
        return None

    kv: list[tuple[str, str]] = []
    for line in text[:-1].split("\n"):
        key, sep, val = line.partition(" ")
        if not sep or not key or "  " in line or val == "":
            return None  # not "key value" with a single separating space
        kv.append((key, val))

    keys = [k for k, _ in kv]
    if any(k.startswith("ext-") for k in keys):
        raise LfsError("git-LFS extension pointers (ext-*) are not supported")
    if keys[0] != "version" or keys[1:] != sorted(keys[1:]):
        return None  # version must be first; the rest alphabetically sorted
    mapping = dict(kv)
    if len(mapping) != len(kv) or set(mapping) != {"version", "oid", "size"}:
        return None  # duplicate keys, or not exactly the basic-pointer key set

    oid_match = _OID_RE.match(mapping["oid"])
    if not oid_match or not _SIZE_RE.match(mapping["size"]):
        return None
    return LfsPointer(oid=oid_match.group(1), size=int(mapping["size"]))


def looks_like_pointer(data: bytes) -> bool:
    """Cheap check: does the blob declare the LFS pointer version? (Used only to
    flag an ambiguous non-LFS-attributed blob; classification uses gitattributes.)"""
    return data[:MAX_POINTER_BYTES].startswith(_VERSION_LINE.encode())


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
