"""End-to-end spec-4 (git-LFS) authoring: scaffold -> commit -> materialize, using
the real git-lfs binary. Skipped where git-lfs is not installed."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hills import scaffold
from hills.errors import BundleError
from hills.hill import Hill

pytestmark = pytest.mark.skipif(shutil.which("git-lfs") is None, reason="git-lfs not installed")


def _make_dataset_hill(tmp_path: Path, monkeypatch) -> Hill:
    monkeypatch.setenv("HILLS_HOME", str(tmp_path / ".hillshome"))
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True, capture_output=True)
    monkeypatch.chdir(project)
    return scaffold.new("dataspec", template="dataset")


def test_dataset_hill_commits_pointers_and_materializes(tmp_path, monkeypatch):
    hill = _make_dataset_hill(tmp_path, monkeypatch)
    assert hill.is_lfs()
    assert (hill.root / ".git").is_dir() and not (hill.root / ".vc").exists()

    # A real, larger dataset shard.
    big = {"rows": [[i, i * 2] for i in range(2000)]}
    (hill.root / "data" / "big.json").write_text(json.dumps(big))

    # Commit through the same path the CLI uses.
    hill.vc.ensure_identity()
    hill.vc.run("add", "-A")
    objects = hill.verify_staged_lfs_pointers()
    assert {p for p, _ in objects} >= {"data/big.json", "data/dataset.json"}
    hill.vc.commit("initial", [])

    # The committed blob is a POINTER, not the raw bytes.
    committed = hill.vc.blob_bytes(hill.vc.out("rev-parse", "HEAD:data/big.json"))
    assert committed.startswith(b"version https://git-lfs.github.com/spec/v1")

    # Materialize lays out the REAL bytes (verified), not the pointer.
    dest = tmp_path / "run"
    hill.materialize(dest)
    out = dest / "data" / "big.json"
    assert out.is_file() and not out.is_symlink()
    assert json.loads(out.read_text())["rows"][1999] == [1999, 3998]
    assert (dest / "eval.py").is_file()


def test_bundle_refused_on_spec4(tmp_path, monkeypatch):
    hill = _make_dataset_hill(tmp_path, monkeypatch)
    (hill.root / "data" / "d.json").write_text('{"a":1}')
    hill.vc.ensure_identity()
    hill.vc.run("add", "-A")
    hill.verify_staged_lfs_pointers()
    hill.vc.commit("initial", [])
    from hills import bundles

    with pytest.raises(BundleError, match="git-LFS"):
        bundles.bundle(hill)
