"""Sound LFS materialization: exact committed non-LFS bytes + verified LFS copies.

These build a git repo by hand (committing pointer *text* as the blob and placing the
real bytes in the working tree, exactly as `git lfs pull` would), so no git-lfs binary
is needed to exercise the materializer's correctness.
"""

import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from hills import lfs, materialize
from hills.errors import HillsError, LfsError
from hills.vc import VC


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _pointer(oid: str, size: int) -> bytes:
    return f"version https://git-lfs.github.com/spec/v1\noid sha256:{oid}\nsize {size}\n".encode()


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "myhill"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    # These tests commit pointer TEXT by hand to simulate the post-clean state, so
    # git-LFS filters must be off (they would otherwise rewrite blobs on `git add`
    # wherever git-lfs is installed globally). This keeps the tests hermetic.
    _git(root, "config", "filter.lfs.clean", "cat")
    _git(root, "config", "filter.lfs.smudge", "cat")
    _git(root, "config", "filter.lfs.process", "")
    _git(root, "config", "filter.lfs.required", "false")
    return root


def _commit(root: Path) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "c")
    return VC(root).resolve_commit()


def _hill(root: Path):
    return SimpleNamespace(vc=VC(root), root=root)


def test_exact_code_and_verified_data(tmp_path):
    root = _repo(tmp_path)
    (root / ".gitattributes").write_text("data/* filter=lfs -text\n")
    (root / "eval.py").write_text("def eval(s):\n    return {}\n")
    data = b"the big dataset bytes" * 10
    oid = hashlib.sha256(data).hexdigest()
    (root / "data").mkdir()
    (root / "data" / "x.bin").write_bytes(_pointer(oid, len(data)))  # committed pointer text
    commit = _commit(root)
    (root / "data" / "x.bin").write_bytes(data)  # working tree = real bytes (post lfs pull)

    dest = tmp_path / "run"
    materialize.materialize_lfs(_hill(root), commit, dest)
    assert (dest / "eval.py").read_text() == "def eval(s):\n    return {}\n"
    assert (dest / "data" / "x.bin").read_bytes() == data
    assert not (dest / "data" / "x.bin").is_symlink()


def test_rejects_unresolved_pointer(tmp_path):
    root = _repo(tmp_path)
    (root / ".gitattributes").write_text("data/* filter=lfs -text\n")
    (root / "eval.py").write_text("x")
    data = b"real"
    oid = hashlib.sha256(data).hexdigest()
    (root / "data").mkdir()
    (root / "data" / "x").write_bytes(_pointer(oid, len(data)))
    commit = _commit(root)
    # working tree still holds the pointer (git lfs pull NOT run) -> hard fail
    with pytest.raises(LfsError):
        materialize.materialize_lfs(_hill(root), commit, tmp_path / "run")


def test_rejects_pointer_looking_blob_without_attr(tmp_path):
    root = _repo(tmp_path)
    (root / "eval.py").write_text("x")
    (root / "sneaky").write_bytes(_pointer("a" * 64, 10))  # pointer-looking, not filter=lfs
    commit = _commit(root)
    with pytest.raises(HillsError, match="looks like an LFS pointer"):
        materialize.materialize_lfs(_hill(root), commit, tmp_path / "run")


def test_rejects_lfs_attr_with_raw_committed_bytes(tmp_path):
    root = _repo(tmp_path)
    (root / ".gitattributes").write_text("data/* filter=lfs -text\n")
    (root / "eval.py").write_text("x")
    (root / "data").mkdir()
    (root / "data" / "x").write_bytes(b"raw bytes, not a pointer")  # git-lfs was off at commit
    commit = _commit(root)
    with pytest.raises(HillsError, match="not a valid LFS pointer"):
        materialize.materialize_lfs(_hill(root), commit, tmp_path / "run")
