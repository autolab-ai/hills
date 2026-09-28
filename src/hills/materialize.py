"""Authoritative materialization of a pinned hill version for evaluation (0.12).

Lay out the *exact committed tree* in a fresh run directory, so the evaluator sees
neither uncommitted changes nor byte drift, and never the raw text of an LFS pointer.

- Non-LFS files: written from the raw committed blob (via cat-file), so
  ``export-ignore``/``export-subst`` cannot alter evaluator bytes (unlike git archive).
- LFS files: classified from the committed ``filter`` attribute, verified against the
  working-tree smudged file (size + sha256 == the pointer's), then copied in
  (reflink/CoW when possible) — stable bytes, no live symlink into a mutable checkout.

Spec 1-3 hills keep the pre-0.12 lock/archive path (see :meth:`Hill._materialize_legacy`).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from hills import lfs
from hills.errors import HillsError


def _copy_verified(src: Path, dst: Path) -> None:
    """Copy real bytes into the run dir; try reflink (CoW, instant) then fall back."""
    try:
        subprocess.run(
            ["cp", "--reflink=auto", "--preserve=mode", str(src), str(dst)],
            check=True,
            capture_output=True,
        )
    except Exception:
        shutil.copyfile(src, dst)


def materialize_lfs(hill, commit: str, dest: Path) -> Path:
    """Lay out ``commit``'s tree in ``dest`` for a spec-4 (git-LFS) hill."""
    vc = hill.vc
    dest.mkdir(parents=True, exist_ok=True)
    entries = vc.tree_entries(commit)
    blob_paths = [e.path for e in entries if e.otype == "blob"]
    filters = vc.attr_filter(commit, blob_paths)

    for e in entries:
        target = dest / e.path
        if ".." in Path(e.path).parts or Path(e.path).is_absolute():
            raise HillsError(f"unsafe path in tree: {e.path!r}")
        target.parent.mkdir(parents=True, exist_ok=True)

        if e.otype != "blob":  # gitlink / submodule
            raise HillsError(f"{e.path}: submodules are not supported in a hill")

        if e.mode == "120000":  # symlink: the blob content is the link target
            link = vc.blob_bytes(e.oid).decode("utf-8")
            if link.startswith("/") or ".." in Path(link).parts:
                raise HillsError(f"{e.path}: unsafe symlink target {link!r}")
            target.symlink_to(link)
            continue

        raw = vc.blob_bytes(e.oid)
        is_lfs = filters.get(e.path) == "lfs"
        pointer = lfs.parse_pointer(raw)

        if is_lfs:
            if len(raw) == 0:
                target.write_bytes(b"")  # an empty file legitimately smudges to empty
            elif pointer is not None:
                src = hill.root / e.path
                lfs.verify_object(src, pointer)  # working-tree bytes must match the pointer
                _copy_verified(src, target)
            else:
                raise HillsError(
                    f"{e.path}: filter=lfs but the committed blob is not a valid LFS pointer "
                    "(was git-lfs active when it was committed?)"
                )
        else:
            if pointer is not None or lfs.looks_like_pointer(raw):
                raise HillsError(
                    f"{e.path}: content looks like an LFS pointer but the path is not "
                    "filter=lfs; refusing to score ambiguous storage"
                )
            target.write_bytes(raw)

        if e.mode == "100755":
            target.chmod(target.stat().st_mode | 0o111)

    return dest
