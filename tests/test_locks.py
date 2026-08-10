import pytest

from hills import locks, manifest as manifest_mod
from hills.errors import LockMismatch

MANIFEST = """
name: demo
version: 0.1.0
watchdog_timeout_s: 60
blobs:
  threshold: 100
  track: ["data/**"]
"""


@pytest.fixture
def hill_dir(tmp_path):
    root = tmp_path / "demo"
    (root / "private" / "data").mkdir(parents=True)
    (root / "data" / "nested").mkdir(parents=True)
    (root / "private" / "data" / "val.bin").write_bytes(b"held out")
    (root / "data" / "train.bin").write_bytes(b"t" * 500)
    (root / "data" / "nested" / "small.txt").write_text("tiny but tracked by pattern")
    (root / "eval.py").write_text("x = 1\n")
    (root / "big.bin").write_bytes(b"b" * 500)
    return root


@pytest.fixture
def manifest():
    return manifest_mod.loads(MANIFEST)


def test_pattern_and_threshold_both_select_blobs(hill_dir, manifest):
    tracked = set(locks.blob_paths(hill_dir, manifest))
    assert tracked == {"data/train.bin", "data/nested/small.txt", "big.bin"}
    assert "eval.py" not in tracked


def test_private_files_are_listed_separately(hill_dir, manifest):
    assert locks.private_paths(hill_dir) == ["private/data/val.bin"]
    assert not any(
        entry["path"].startswith("private/")
        for entry in locks.build(hill_dir, manifest)[1].entries
    )


def test_locks_are_sorted_and_hashed(hill_dir, manifest):
    private_lock, blobs_lock = locks.write(hill_dir, manifest)
    assert [entry["path"] for entry in blobs_lock.entries] == sorted(blobs_lock.paths)
    assert private_lock.entries[0]["size"] == 8
    assert len(private_lock.entries[0]["sha256"]) == 64
    assert (hill_dir / "private.lock").is_file()
    assert (hill_dir / "blobs.lock").is_file()


def test_regeneration_overwrites_hand_edits(hill_dir, manifest):
    locks.write(hill_dir, manifest)
    (hill_dir / "private.lock").write_text('{"lock_version": 1, "kind": "private", "entries": []}')
    private_lock, _ = locks.write(hill_dir, manifest)
    assert len(private_lock.entries) == 1


def test_verify_detects_modification(hill_dir, manifest):
    private_lock, _ = locks.write(hill_dir, manifest)
    (hill_dir / "private" / "data" / "val.bin").write_bytes(b"held in!")
    with pytest.raises(LockMismatch, match="val.bin has changed"):
        locks.verify(hill_dir, private_lock, locks.private_paths(hill_dir))


def test_verify_detects_deletion(hill_dir, manifest):
    private_lock, _ = locks.write(hill_dir, manifest)
    (hill_dir / "private" / "data" / "val.bin").unlink()
    with pytest.raises(LockMismatch, match="missing from"):
        locks.verify(hill_dir, private_lock, locks.private_paths(hill_dir))


def test_verify_detects_addition(hill_dir, manifest):
    private_lock, _ = locks.write(hill_dir, manifest)
    (hill_dir / "private" / "extra.bin").write_bytes(b"new")
    with pytest.raises(LockMismatch, match="not in private.lock"):
        locks.verify(hill_dir, private_lock, locks.private_paths(hill_dir))


@pytest.mark.parametrize(
    "pattern, path, matches",
    [
        ("data/**", "data/train.bin", True),
        ("data/**", "data/a/b/c.bin", True),
        ("data/**", "other/train.bin", False),
        ("*.bin", "train.bin", True),
        ("*.bin", "data/train.bin", False),
        ("data/*.bin", "data/train.bin", True),
        ("data/*.bin", "data/sub/train.bin", False),
    ],
)
def test_glob_semantics(pattern, path, matches):
    assert bool(locks.glob_to_regex(pattern).match(path)) is matches
