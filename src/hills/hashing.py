"""Content hashing for submissions, lock entries, and the tool itself."""

import hashlib
import os
from pathlib import Path

# Directories and files that are never part of a submission's or hill's content
# identity: caches, virtualenvs, and version-control metadata.
SKIP_DIRS = frozenset(
    {
        ".git",
        ".vc",
        ".hills",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".ipynb_checkpoints",
        "node_modules",
    }
)
SKIP_FILES = frozenset({".DS_Store"})
SKIP_SUFFIXES = (".pyc", ".pyo")


def _skip(name: str) -> bool:
    return name in SKIP_FILES or name.endswith(SKIP_SUFFIXES)


def iter_files(root: Path):
    """Yield (posix relative path, absolute path) for every content file, sorted."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        here = Path(dirpath)
        for name in sorted(filenames):
            if _skip(name):
                continue
            path = here / name
            yield path.relative_to(root).as_posix(), path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_tree(root: Path) -> str:
    """A single digest over a directory's paths, modes, and contents."""
    digest = hashlib.sha256()
    for rel, path in iter_files(root):
        if path.is_symlink():
            digest.update(b"L\0" + rel.encode() + b"\0" + os.readlink(path).encode() + b"\0")
            continue
        stat = path.stat()
        executable = b"x" if stat.st_mode & 0o111 else b"-"
        digest.update(
            b"F\0"
            + rel.encode()
            + b"\0"
            + str(stat.st_size).encode()
            + b"\0"
            + executable
            + b"\0"
            + sha256_file(path).encode()
            + b"\0"
        )
    return "sha256:" + digest.hexdigest()


_tool_hash: str | None = None


def tool_hash() -> str:
    """Digest of the installed hills package, recorded in every report."""
    global _tool_hash
    if _tool_hash is None:
        package_root = Path(__file__).resolve().parent
        digest = hashlib.sha256()
        for rel, path in iter_files(package_root):
            if not rel.endswith(".py") or rel.startswith("_templates/"):
                continue
            digest.update(rel.encode() + b"\0" + sha256_file(path).encode() + b"\0")
        _tool_hash = digest.hexdigest()
    return _tool_hash
