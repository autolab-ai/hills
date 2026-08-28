"""`hills bundle` / `hills unbundle`: a committed hill moves between machines intact."""

import io
import json
import shutil
import tarfile
from pathlib import Path

import pytest

from hills import bundles
from hills.errors import BundleError, DirtyHill, HillsError, LockMismatch
from hills.hill import Hill

pytestmark = pytest.mark.usefixtures("project")

BLOB_THRESHOLD = 16 * 1024  # larger than any template file, so only train.bin is a blob


@pytest.fixture
def hill(project, cli):
    """circle-packing plus a private file and a blob over a tiny threshold."""
    cli("new", "circle-packing", "-t", "circle-packing")
    root = project / ".autolab" / "hills" / "circle-packing"
    (root / "private" / "data").mkdir(parents=True)
    (root / "private" / "data" / "val.bin").write_bytes(b"held-out" * 4)
    (root / "data").mkdir()
    (root / "data" / "train.bin").write_bytes(b"\x01" * (BLOB_THRESHOLD + 1))
    manifest = root / "hill.yaml"
    manifest.write_text(manifest.read_text() + f"\nblobs:\n  threshold: {BLOB_THRESHOLD}\n")
    assert cli("commit", "circle-packing", "-m", "initial", "--no-tests") == 0
    return Hill.at(root)


@pytest.fixture
def archive(hill, cli, tmp_path):
    path = tmp_path / "out" / "packing.hill.tar"
    assert cli("bundle", "circle-packing", "-o", str(path)) == 0
    return path


@pytest.fixture
def elsewhere(tmp_path):
    """A second project to unbundle into, as another machine would."""
    other = tmp_path / "elsewhere"
    other.mkdir()
    return other


def submission_for(hill: Hill, where: Path) -> Path:
    directory = where / "attempt"
    directory.mkdir()
    shutil.copy(hill.root / "examples" / "grid" / "solution.json", directory)
    return directory


def read_manifest(archive: Path) -> dict:
    with tarfile.open(archive) as tar:
        return json.load(tar.extractfile(tar.getmembers()[0]))


def rewrite(archive: Path, edit) -> None:
    """Copy the tar entry by entry, letting `edit(info, data)` change any of them."""
    source = archive.with_suffix(".orig")
    archive.rename(source)
    with tarfile.open(source) as src, tarfile.open(archive, "w") as dst:
        for info in src:
            data = src.extractfile(info).read() if info.isfile() else b""
            info, data = edit(info, data)
            if info is None:
                continue
            info.size = len(data)
            dst.addfile(info, io.BytesIO(data))


def add_member(archive: Path, name: str, data: bytes) -> None:
    with tarfile.open(archive, "a") as tar:
        info = tarfile.TarInfo(name)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))


# -- round trip --------------------------------------------------------------


def test_bundle_layout_and_manifest(hill, archive):
    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert names == [
        "bundle.json",
        "git.bundle",
        "locked/data/train.bin",
        "locked/private/data/val.bin",
    ]
    manifest = read_manifest(archive)
    assert manifest["format_version"] == 1
    assert manifest["hill"] == "circle-packing"
    assert manifest["tree_hash"] == hill.vc.tree_hash()
    assert manifest["commit"] == hill.vc.commit_hash()
    assert manifest["private_included"] is True
    assert [f["kind"] for f in manifest["files"]] == ["blob", "private"]
    private_lock, blobs_lock = hill.head_locks()
    assert manifest["files"][1]["sha256"] == private_lock.entries[0]["sha256"]
    assert manifest["files"][0]["sha256"] == blobs_lock.entries[0]["sha256"]


def test_default_output_name(hill, cli, capsys):
    assert cli("bundle", "circle-packing") == 0
    expected = Path.cwd() / f"circle-packing-{hill.vc.tree_hash()[:12]}.hill.tar"
    assert expected.is_file()


def test_round_trip_reproduces_the_tree_hash(hill, archive, elsewhere, cli):
    assert cli("unbundle", str(archive), "--into", str(elsewhere)) == 0
    copy = Hill.at(elsewhere / "circle-packing")
    assert copy.vc.status_porcelain() == []
    assert copy.lock_drift() == []
    assert copy.vc.tree_hash() == hill.vc.tree_hash() == read_manifest(archive)["tree_hash"]
    assert copy.vc.log(5)[0]["commit"] == hill.vc.commit_hash()
    assert not (copy.root / ".git").exists()


def test_unbundled_hill_checks_and_evaluates_with_the_same_tree_hash(
    hill, archive, elsewhere, cli, capsys, monkeypatch
):
    cli("unbundle", str(archive), "--into", str(elsewhere))
    copy = elsewhere / "circle-packing"
    monkeypatch.chdir(elsewhere)
    assert cli("check", str(copy)) == 0
    capsys.readouterr()
    assert cli("eval", str(submission_for(hill, elsewhere)), "-H", str(copy)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["tree_hash"] == hill.vc.tree_hash()
    assert report["official"] is True


def test_unbundle_defaults_to_the_project_hills_directory(archive, cli, tmp_path, monkeypatch):
    other = tmp_path / "other-project"
    other.mkdir()
    monkeypatch.chdir(other)
    assert cli("unbundle", str(archive)) == 0
    assert (other / ".autolab" / "hills" / "circle-packing" / "hill.yaml").is_file()


# -- tampering ---------------------------------------------------------------


def test_tampered_locked_entry_is_rejected(archive, elsewhere, cli):
    def flip(info, data):
        if info.name == "locked/private/data/val.bin":
            data = bytes([data[0] ^ 1]) + data[1:]
        return info, data

    rewrite(archive, flip)
    with pytest.raises(BundleError, match="private/data/val.bin"):
        cli("unbundle", str(archive), "--into", str(elsewhere))
    assert not (elsewhere / "circle-packing").exists()


def test_tampered_tree_hash_is_rejected(archive, elsewhere, cli):
    def edit(info, data):
        if info.name == "bundle.json":
            manifest = json.loads(data)
            manifest["tree_hash"] = "0" * 40
            data = json.dumps(manifest).encode()
        return info, data

    rewrite(archive, edit)
    with pytest.raises(BundleError, match="tree hash mismatch"):
        cli("unbundle", str(archive), "--into", str(elsewhere))
    assert not (elsewhere / "circle-packing").exists()


def test_unlisted_entry_is_rejected(archive, elsewhere, cli):
    add_member(archive, "locked/extra.bin", b"x")
    with pytest.raises(BundleError, match="not listed"):
        cli("unbundle", str(archive), "--into", str(elsewhere))
    assert not (elsewhere / "circle-packing").exists()


def test_escaping_entry_is_rejected(archive, elsewhere, cli):
    add_member(archive, "locked/../escape", b"x")
    with pytest.raises(BundleError, match="unsafe path"):
        cli("unbundle", str(archive), "--into", str(elsewhere))
    assert not (elsewhere / "escape").exists()
    assert not (elsewhere / "circle-packing").exists()


def test_escaping_manifest_entry_is_rejected(archive, elsewhere, cli):
    def edit(info, data):
        if info.name == "bundle.json":
            manifest = json.loads(data)
            manifest["files"][0]["path"] = "../escape"
            data = json.dumps(manifest).encode()
        return info, data

    rewrite(archive, edit)
    with pytest.raises(BundleError, match="unsafe path"):
        cli("unbundle", str(archive), "--into", str(elsewhere))


def test_bundle_from_a_newer_spec_version_is_rejected(archive, elsewhere, cli, monkeypatch):
    """An older hills reading a newer hill fails with the upgrade message, not debris."""
    monkeypatch.setattr("hills.manifest.SUPPORTED_SPEC_VERSION", 0)
    with pytest.raises(HillsError, match="spec version 2.*Upgrade hills"):
        cli("unbundle", str(archive), "--into", str(elsewhere))
    assert not (elsewhere / "circle-packing").exists()


def test_unknown_format_version_is_rejected(archive, elsewhere, cli):
    def edit(info, data):
        if info.name == "bundle.json":
            manifest = json.loads(data)
            manifest["format_version"] = 2
            data = json.dumps(manifest).encode()
        return info, data

    rewrite(archive, edit)
    with pytest.raises(BundleError, match="format version 2.*Upgrade hills"):
        cli("unbundle", str(archive), "--into", str(elsewhere))


# -- --no-private ------------------------------------------------------------


def test_no_private_bundle_unpacks_but_cannot_evaluate(
    hill, cli, tmp_path, elsewhere, capsys, monkeypatch
):
    archive = tmp_path / "public.hill.tar"
    assert cli("bundle", "circle-packing", "-o", str(archive), "--no-private") == 0
    with tarfile.open(archive) as tar:
        assert not any(name.startswith("locked/private/") for name in tar.getnames())
    manifest = read_manifest(archive)
    assert manifest["private_included"] is False
    assert [f["path"] for f in manifest["files"]] == ["data/train.bin"]

    assert cli("unbundle", str(archive), "--into", str(elsewhere)) == 0
    assert "--no-private" in capsys.readouterr().err
    copy = elsewhere / "circle-packing"
    assert Hill.at(copy).vc.tree_hash() == hill.vc.tree_hash()

    # The missing private file shows up as lock drift first; forcing past that
    # gate reaches lock verification, which names the file.
    monkeypatch.chdir(elsewhere)
    submission = submission_for(hill, elsewhere)
    with pytest.raises(DirtyHill, match="D  private/data/val.bin"):
        cli("eval", str(submission), "-H", str(copy))
    with pytest.raises(LockMismatch, match="private/data/val.bin"):
        cli("eval", str(submission), "-H", str(copy), "--force")


# -- gates -------------------------------------------------------------------


def test_uncommitted_hill_is_refused(project, cli):
    cli("new", "fresh", "-t", "circle-packing")
    with pytest.raises(Exception, match="no commits yet"):
        cli("bundle", "fresh")


def test_dirty_hill_is_refused_unless_forced(hill, cli, tmp_path, capsys):
    (hill.root / "README.md").write_text("edited\n")
    archive = tmp_path / "dirty.hill.tar"
    with pytest.raises(DirtyHill, match="uncommitted changes"):
        cli("bundle", "circle-packing", "-o", str(archive))
    assert not archive.exists()

    assert cli("bundle", "circle-packing", "-o", str(archive), "--force") == 0
    assert "warning" in capsys.readouterr().err
    assert read_manifest(archive)["tree_hash"] == hill.vc.tree_hash()


def test_drifted_locks_are_refused(hill, cli, tmp_path):
    (hill.root / "private" / "data" / "val.bin").write_bytes(b"changed")
    with pytest.raises(DirtyHill, match="M  private/data/val.bin"):
        cli("bundle", "circle-packing", "-o", str(tmp_path / "x.hill.tar"))
    with pytest.raises(LockMismatch, match="private/data/val.bin"):
        cli("bundle", "circle-packing", "-o", str(tmp_path / "x.hill.tar"), "--force")


def test_symlinked_locked_file_is_refused(hill, cli, tmp_path):
    target = hill.root / "private" / "data" / "val.bin"
    real = tmp_path / "real.bin"
    real.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(real)
    with pytest.raises(BundleError, match="not a regular file"):
        cli("bundle", "circle-packing", "-o", str(tmp_path / "x.hill.tar"))


def test_existing_destination_is_refused_unless_forced(archive, elsewhere, cli):
    cli("unbundle", str(archive), "--into", str(elsewhere))
    marker = elsewhere / "circle-packing" / "stale.txt"
    marker.write_text("old")
    with pytest.raises(BundleError, match="already exists"):
        cli("unbundle", str(archive), "--into", str(elsewhere))
    assert marker.exists()
    assert cli("unbundle", str(archive), "--into", str(elsewhere), "--force") == 0
    assert not marker.exists()


# -- --json ------------------------------------------------------------------


def test_json_output(hill, cli, tmp_path, elsewhere, capsys):
    archive = tmp_path / "j.hill.tar"
    assert cli("bundle", "circle-packing", "-o", str(archive), "--json") == 0
    bundled = json.loads(capsys.readouterr().out)
    assert bundled == read_manifest(archive)
    assert set(bundled) == {
        "format_version", "hill", "version", "tree_hash", "commit", "tool",
        "created", "private_included", "files",
    }
    assert set(bundled["tool"]) == {"version", "sha256"}
    assert set(bundled["files"][0]) == {"path", "sha256", "size", "kind"}

    assert cli("unbundle", str(archive), "--into", str(elsewhere), "--json") == 0
    unbundled = json.loads(capsys.readouterr().out)
    assert unbundled["path"] == str(elsewhere / "circle-packing")
    assert {k: v for k, v in unbundled.items() if k != "path"} == bundled


def test_public_surface():
    import hills

    assert hills.bundle is not None and hills.unbundle is not None
    assert issubclass(hills.BundleError, Exception)
    assert bundles.FORMAT_VERSION == 1
