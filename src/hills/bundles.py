"""`hills bundle` and `hills unbundle`: one file that carries a committed hill.

A hill cannot be moved with git alone, because `private/` and lock-tracked
blobs are kept out of git on purpose. A bundle is an uncompressed POSIX tar
holding the manifest, a `git bundle` of the history reachable from HEAD, and
every locked file. Unpacking it elsewhere gives a hill that evaluates with the
same tree hash. The format is a contract between machines, so it is versioned
and everything in it is verifiable against the locks.
"""

import io
import json
import shutil
import sys
import tarfile
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from hills import locks, manifest as manifest_mod, paths
from hills.canonical import dumps
from hills.errors import BundleError, DirtyHill
from hills.hashing import sha256_file, tool_hash
from hills.hill import MANIFEST_NAME, Hill
from hills.vc import VC

FORMAT_VERSION = 1
SUFFIX = ".hill.tar"

MANIFEST_ENTRY = "bundle.json"
GIT_ENTRY = "git.bundle"
LOCKED_PREFIX = "locked/"

KIND_PRIVATE = "private"
KIND_BLOB = "blob"


# -- manifest -----------------------------------------------------------------


@dataclass(frozen=True)
class BundleFile:
    path: str
    sha256: str
    size: int
    kind: str

    @property
    def member(self) -> str:
        return LOCKED_PREFIX + self.path

    def as_json(self) -> dict:
        return {"path": self.path, "sha256": self.sha256, "size": self.size, "kind": self.kind}

    @classmethod
    def from_json(cls, raw: dict) -> "BundleFile":
        try:
            return cls(
                path=str(raw["path"]),
                sha256=str(raw["sha256"]),
                size=int(raw["size"]),
                kind=str(raw["kind"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise BundleError(f"{MANIFEST_ENTRY}: malformed files entry {raw!r}") from error


@dataclass(frozen=True)
class BundleManifest:
    hill: str
    version: str
    tree_hash: str
    commit: str
    tool: dict
    created: str
    private_included: bool
    files: tuple[BundleFile, ...] = field(default_factory=tuple)
    format_version: int = FORMAT_VERSION

    @property
    def total_size(self) -> int:
        return sum(entry.size for entry in self.files)

    def by_member(self) -> dict[str, BundleFile]:
        return {entry.member: entry for entry in self.files}

    def as_json(self) -> dict:
        return {
            "format_version": self.format_version,
            "hill": self.hill,
            "version": self.version,
            "tree_hash": self.tree_hash,
            "commit": self.commit,
            "tool": dict(self.tool),
            "created": self.created,
            "private_included": self.private_included,
            "files": [entry.as_json() for entry in self.files],
        }

    def text(self) -> str:
        return dumps(self.as_json()) + "\n"

    @classmethod
    def from_json(cls, raw) -> "BundleManifest":
        if not isinstance(raw, dict):
            raise BundleError(f"{MANIFEST_ENTRY} is not a JSON object")
        version = raw.get("format_version")
        if version != FORMAT_VERSION:
            raise BundleError(
                f"this bundle uses format version {version!r}; this hills reads version "
                f"{FORMAT_VERSION}. "
                + (
                    "Upgrade hills to unbundle it."
                    if isinstance(version, int) and version > FORMAT_VERSION
                    else "Re-create the bundle with a current hills."
                )
            )
        try:
            files = tuple(BundleFile.from_json(entry) for entry in raw["files"])
            manifest = cls(
                hill=str(raw["hill"]),
                version=str(raw["version"]),
                tree_hash=str(raw["tree_hash"]),
                commit=str(raw["commit"]),
                tool=dict(raw["tool"]),
                created=str(raw["created"]),
                private_included=bool(raw["private_included"]),
                files=files,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise BundleError(f"{MANIFEST_ENTRY} is missing or malformed: {error}") from error
        _require_safe_name(manifest.hill)
        for entry in manifest.files:
            _require_safe_member(entry.member)
        if [entry.path for entry in files] != sorted(entry.path for entry in files):
            raise BundleError(f"{MANIFEST_ENTRY}: files must be sorted by path")
        return manifest


def _require_safe_name(name: str) -> None:
    if not name or name in (".", "..") or "/" in name or "\\" in name or name.startswith("."):
        raise BundleError(f"{MANIFEST_ENTRY}: {name!r} is not a valid hill name")


def _require_safe_member(member: str) -> None:
    """A tar member under locked/ must be a relative path that stays inside the hill."""
    pure = PurePosixPath(member)
    if (
        pure.is_absolute()
        or "\\" in member
        or any(part in ("", ".", "..") for part in pure.parts)
        or not member.startswith(LOCKED_PREFIX)
        or len(pure.parts) < 2
    ):
        raise BundleError(f"unsafe path in bundle: {member!r}")


# -- bundle -------------------------------------------------------------------


def default_output(hill: Hill) -> Path:
    return Path.cwd() / f"{hill.name}-{hill.vc.tree_hash()[:12]}{SUFFIX}"


def _require_clean(hill: Hill, *, force: bool) -> None:
    """Same gate and wording as `hills eval` (`runner._prepare_hill`)."""
    dirty = hill.vc.status_porcelain()
    drift = hill.lock_drift()
    if not (dirty or drift):
        return
    if not force:
        details = "\n".join(f"  {line}" for line in [*dirty, *drift])
        raise DirtyHill(
            f"hill {hill.name} has uncommitted changes:\n{details}\n"
            f"Commit them (hills commit {hill.name} -m \"...\"), "
            "or use --force to bundle the last committed version."
        )
    print(
        f"hills: warning: {hill.name} has uncommitted changes; "
        "bundling the last committed version anyway (--force)",
        file=sys.stderr,
    )


def _files_from_locks(
    head_locks: tuple[locks.Lock, locks.Lock], *, include_private: bool
) -> tuple[BundleFile, ...]:
    """The file list is derived from the locks at HEAD, never rehashed."""
    private_lock, blobs_lock = head_locks
    entries = [
        BundleFile(e["path"], e["sha256"], e["size"], KIND_BLOB) for e in blobs_lock.entries
    ]
    if include_private:
        entries += [
            BundleFile(e["path"], e["sha256"], e["size"], KIND_PRIVATE)
            for e in private_lock.entries
        ]
    return tuple(sorted(entries, key=lambda entry: entry.path))


def _require_regular(hill: Hill, entry: BundleFile) -> Path:
    path = hill.root / entry.path
    if path.is_symlink() or not path.is_file():
        raise BundleError(
            f"{entry.path} in {hill.name} is not a regular file; "
            "bundles carry regular files only."
        )
    return path


def bundle(
    hill: Hill, *, output: Path | None = None, include_private: bool = True, force: bool = False
) -> tuple[BundleManifest, Path]:
    """Write the hill at HEAD, with its locked content, to one `.hill.tar`."""
    hill.require_commits()
    hill.refresh_exclude()
    _require_clean(hill, force=force)

    head_locks = hill.head_locks()
    locks.verify_against_head(hill.root, hill.manifest, head_locks)

    from hills import __version__

    head_manifest = manifest_mod.loads(
        hill.vc.show(f"HEAD:{MANIFEST_NAME}"), f"{hill.name}@HEAD {MANIFEST_NAME}"
    )
    manifest = BundleManifest(
        hill=hill.name,
        version=head_manifest.version,
        tree_hash=hill.vc.tree_hash(),
        commit=hill.vc.commit_hash(),
        tool={"version": __version__, "sha256": tool_hash()},
        created=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        private_included=include_private,
        files=_files_from_locks(head_locks, include_private=include_private),
    )
    sources = {entry.member: _require_regular(hill, entry) for entry in manifest.files}

    output = Path(output) if output else default_output(hill)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hills-bundle-") as scratch:
        git_bundle = Path(scratch) / GIT_ENTRY
        hill.vc.bundle_to(git_bundle)
        partial = output.with_name(output.name + ".part")
        try:
            with tarfile.open(partial, "w", format=tarfile.PAX_FORMAT) as tar:
                _add_bytes(tar, MANIFEST_ENTRY, manifest.text().encode())
                tar.add(git_bundle, arcname=GIT_ENTRY, recursive=False)
                for member, source in sources.items():
                    tar.add(source, arcname=member, recursive=False)
            partial.replace(output)
        finally:
            partial.unlink(missing_ok=True)
    return manifest, output


def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o644
    info.mtime = int(datetime.now(timezone.utc).timestamp())
    tar.addfile(info, io.BytesIO(data))


# -- unbundle -----------------------------------------------------------------


def read_manifest(archive: Path) -> BundleManifest:
    """Read and validate `bundle.json`, which must be the first entry."""
    archive = Path(archive)
    if not archive.is_file():
        raise BundleError(f"{archive} is not a file")
    try:
        with tarfile.open(archive, "r:") as tar:
            first = tar.next()
            if first is None or first.name != MANIFEST_ENTRY or not first.isfile():
                raise BundleError(f"{archive} is not a hill bundle: {MANIFEST_ENTRY} must come first")
            raw = tar.extractfile(first).read()
    except tarfile.TarError as error:
        raise BundleError(f"{archive} is not a readable tar: {error}") from error
    try:
        parsed = json.loads(raw)
    except ValueError as error:
        raise BundleError(f"{archive}: {MANIFEST_ENTRY} is not valid JSON: {error}") from error
    return BundleManifest.from_json(parsed)


def default_destination(manifest: BundleManifest) -> Path:
    return paths.project_hills(Path.cwd()) / manifest.hill


def unbundle(
    archive: Path, *, into: Path | None = None, force: bool = False
) -> tuple[BundleManifest, Path]:
    """Unpack a bundle into a working hill and verify it end to end."""
    archive = Path(archive)
    manifest = read_manifest(archive)
    dest = (Path(into) / manifest.hill) if into else default_destination(manifest)

    if dest.exists():
        if not force:
            raise BundleError(f"{dest} already exists; use --force to replace it")
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        _extract(archive, manifest, dest)
        _verify(manifest, dest)
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return manifest, dest


def _extract(archive: Path, manifest: BundleManifest, dest: Path) -> None:
    expected = manifest.by_member()
    seen: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="hills-unbundle-") as scratch:
        git_bundle = Path(scratch) / GIT_ENTRY
        with tarfile.open(archive, "r:") as tar:
            for info in tar:
                if info.name == MANIFEST_ENTRY and not seen:
                    seen.add(info.name)
                    continue
                if info.name == GIT_ENTRY and info.name not in seen:
                    _extract_regular(tar, info, git_bundle)
                    seen.add(info.name)
                    continue
                if info.name in seen:
                    raise BundleError(f"duplicate entry in bundle: {info.name}")
                _require_safe_member(info.name)
                entry = expected.get(info.name)
                if entry is None:
                    raise BundleError(
                        f"{info.name} is in the bundle but not listed in {MANIFEST_ENTRY}"
                    )
                _extract_regular(tar, info, dest / entry.path)
                seen.add(info.name)
        if GIT_ENTRY not in seen:
            raise BundleError(f"bundle has no {GIT_ENTRY}")
        missing = sorted(set(expected) - seen)
        if missing:
            raise BundleError(f"{MANIFEST_ENTRY} lists {missing[0]}, which is not in the bundle")

        vc = VC(dest)
        vc.init()
        vc.restore_from_bundle(git_bundle)

    hill = Hill.at(dest)
    hill.refresh_exclude()


def _extract_regular(tar: tarfile.TarFile, info: tarfile.TarInfo, target: Path) -> None:
    if not info.isfile():
        raise BundleError(f"{info.name} in the bundle is not a regular file")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tar.extractfile(info) as source, open(target, "wb") as sink:
        shutil.copyfileobj(source, sink)


def _verify(manifest: BundleManifest, dest: Path) -> None:
    """Nothing about the unpacked hill is trusted until it matches the manifest and the locks."""
    for entry in manifest.files:
        path = dest / entry.path
        if path.stat().st_size != entry.size or sha256_file(path) != entry.sha256:
            raise BundleError(
                f"{entry.path} does not match its {MANIFEST_ENTRY} entry "
                f"(expected sha256 {entry.sha256[:12]}…, size {entry.size}); "
                "the bundle is corrupt or was tampered with"
            )

    hill = Hill.at(dest)
    if hill.name != manifest.hill:
        raise BundleError(f"{MANIFEST_ENTRY} names {manifest.hill} but hill.yaml says {hill.name}")
    hill.require_commits()
    changes = hill.vc.status_porcelain()
    if changes:
        raise BundleError("the unpacked working tree is not clean:\n" + "\n".join(changes))

    head_private, head_blobs = hill.head_locks()
    if manifest.private_included:
        locks.verify(dest, head_private, locks.private_paths(dest))
    locks.verify(dest, head_blobs, locks.blob_paths(dest, hill.manifest))

    actual = hill.vc.tree_hash()
    if actual != manifest.tree_hash:
        raise BundleError(
            f"tree hash mismatch: {MANIFEST_ENTRY} says {manifest.tree_hash} "
            f"but the unpacked hill is {actual}"
        )
    if hill.vc.commit_hash() != manifest.commit:
        raise BundleError(
            f"commit mismatch: {MANIFEST_ENTRY} says {manifest.commit} "
            f"but the unpacked hill is at {hill.vc.commit_hash()}"
        )
