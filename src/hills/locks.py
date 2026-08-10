"""private.lock and blobs.lock.

The lock files are the whole of the tracking mechanism: content that stays out
of git is bound into the hill's identity by its hash. They are regenerated from
disk at every commit, so hand edits do not survive.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from hills.errors import LockMismatch
from hills.hashing import iter_files, sha256_file
from hills.manifest import Manifest

PRIVATE_LOCK = "private.lock"
BLOBS_LOCK = "blobs.lock"
LOCK_FILES = (PRIVATE_LOCK, BLOBS_LOCK)
PRIVATE_DIR = "private"
LOCK_VERSION = 1


def glob_to_regex(pattern: str) -> re.Pattern:
    """`data/**` matches everything under data/; `*` stops at a path separator."""
    out = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == "*":
            if pattern[i : i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(char))
        i += 1
    return re.compile("^" + "".join(out) + "$")


@dataclass(frozen=True)
class Lock:
    kind: str
    entries: tuple[dict, ...]

    def as_json(self) -> dict:
        return {
            "lock_version": LOCK_VERSION,
            "kind": self.kind,
            "entries": [dict(entry) for entry in self.entries],
        }

    def text(self) -> str:
        return json.dumps(self.as_json(), indent=2, sort_keys=False) + "\n"

    @property
    def paths(self) -> set[str]:
        return {entry["path"] for entry in self.entries}

    @property
    def total_size(self) -> int:
        return sum(entry["size"] for entry in self.entries)


def _entries_for(root: Path, relative_paths) -> tuple[dict, ...]:
    return tuple(
        {
            "path": rel,
            "sha256": sha256_file(root / rel),
            "size": (root / rel).stat().st_size,
        }
        for rel in sorted(relative_paths)
    )


def private_paths(root: Path) -> list[str]:
    private = root / PRIVATE_DIR
    if not private.is_dir():
        return []
    return [f"{PRIVATE_DIR}/{rel}" for rel, _ in iter_files(private)]


def blob_paths(root: Path, manifest: Manifest) -> list[str]:
    """Files outside private/ that are tracked by lock instead of by git."""
    patterns = [glob_to_regex(p) for p in manifest.blobs.track]
    threshold = manifest.blobs.threshold
    tracked = []
    for rel, path in iter_files(root):
        if rel.startswith(f"{PRIVATE_DIR}/") or rel in LOCK_FILES:
            continue
        if any(pattern.match(rel) for pattern in patterns) or path.stat().st_size > threshold:
            tracked.append(rel)
    return tracked


def build(root: Path, manifest: Manifest) -> tuple[Lock, Lock]:
    root = Path(root)
    return (
        Lock("private", _entries_for(root, private_paths(root))),
        Lock("blobs", _entries_for(root, blob_paths(root, manifest))),
    )


def write(root: Path, manifest: Manifest) -> tuple[Lock, Lock]:
    private_lock, blobs_lock = build(root, manifest)
    (root / PRIVATE_LOCK).write_text(private_lock.text())
    (root / BLOBS_LOCK).write_text(blobs_lock.text())
    return private_lock, blobs_lock


def parse(text: str, kind: str, source: str) -> Lock:
    data = json.loads(text)
    if data.get("kind") != kind or data.get("lock_version") != LOCK_VERSION:
        raise LockMismatch(f"{source} is not a version {LOCK_VERSION} {kind} lock")
    return Lock(kind, tuple(data.get("entries", ())))


def verify(root: Path, lock: Lock, expected_paths: list[str]) -> None:
    """Check every locked file against disk. Any drift is a hard error."""
    on_disk = set(expected_paths)
    locked = lock.paths

    for missing in sorted(locked - on_disk):
        raise LockMismatch(
            f"{lock.kind}.lock lists {missing}, which is missing from {root}. "
            "Restore the file, or re-commit the hill."
        )
    for extra in sorted(on_disk - locked):
        raise LockMismatch(
            f"{extra} is present in {root} but not in {lock.kind}.lock. "
            "It was added after the last commit; commit the hill again."
        )
    for entry in lock.entries:
        path = root / entry["path"]
        actual_size = path.stat().st_size
        if actual_size != entry["size"] or sha256_file(path) != entry["sha256"]:
            raise LockMismatch(
                f"{entry['path']} has changed since the last commit "
                f"({lock.kind}.lock expects sha256 {entry['sha256'][:12]}…, size {entry['size']}). "
                "Commit the hill again, or restore the file."
            )


def verify_against_head(root: Path, manifest: Manifest, head_locks: tuple[Lock, Lock]) -> None:
    private_lock, blobs_lock = head_locks
    verify(root, private_lock, private_paths(root))
    verify(root, blobs_lock, blob_paths(root, manifest))
