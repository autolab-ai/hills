"""A hill on disk: its manifest, its version control, and its committed identity."""

from dataclasses import dataclass
from pathlib import Path

from hills import locks, manifest as manifest_mod, paths
from hills.errors import HillNotFound, HillsError
from hills.vc import VC

EVAL_ENTRYPOINT = "eval.py"
MANIFEST_NAME = "hill.yaml"
README_NAME = "README.md"
PYPROJECT_NAME = "pyproject.toml"


@dataclass
class Hill:
    name: str
    root: Path
    manifest: manifest_mod.Manifest
    vc: VC

    @classmethod
    def at(cls, root: Path) -> "Hill":
        root = Path(root).resolve()
        loaded = manifest_mod.load(root / MANIFEST_NAME)
        if loaded.name != root.name:
            raise HillsError(
                f"{root / MANIFEST_NAME} declares name {loaded.name!r} "
                f"but lives in a directory named {root.name!r}"
            )
        return cls(name=loaded.name, root=root, manifest=loaded, vc=VC(root))

    @classmethod
    def resolve(cls, name: str) -> "Hill":
        """A name is looked up in .autolab/hills above the cwd; a path is used as given."""
        given = Path(name)
        if (given / MANIFEST_NAME).is_file():
            return cls.at(given)

        found = paths.find_hill(name, Path.cwd())
        if found is not None:
            return cls.at(found)

        nearby = [d.name for d in paths.nearby_hills(Path.cwd())]
        known = ", ".join(nearby) if nearby else "(none in this project)"
        raise HillNotFound(
            f"no hill named {name} in .autolab/hills above {Path.cwd()}. Here: {known}"
        )

    # -- paths ------------------------------------------------------------

    @property
    def entrypoint(self) -> Path:
        return self.root / EVAL_ENTRYPOINT

    @property
    def private_dir(self) -> Path:
        return self.root / locks.PRIVATE_DIR

    # -- version control --------------------------------------------------

    def refresh_exclude(self) -> None:
        """Keep git's view in step with what the manifest says is lock-tracked.

        Legacy (.vc) hills only: spec-4 hills use git-LFS and .gitattributes, and a
        modern .git repo is treated as read-only during eval, so it is never touched.
        """
        if self.vc.initialized and self.vc.legacy:
            self.vc.write_exclude(locks.blob_paths(self.root, self.manifest))

    def require_vc(self) -> None:
        if not self.vc.initialized:
            raise HillsError(
                f"{self.root} has no version control (.git or .vc), so it is not a "
                "versioned hill. Hills are created by `hills new`."
            )

    def is_lfs(self) -> bool:
        return self.manifest.spec_version >= manifest_mod.LFS_SPEC_VERSION

    def verify_staged_lfs_pointers(self) -> list[tuple[str, int]]:
        """Before a spec-4 commit: every nonempty ``filter=lfs`` staged file must be a
        canonical git-LFS pointer. Otherwise the raw bytes would be committed into git
        (LFS filters were not active when the file was added), silently defeating the
        whole point. Returns (path, size) per LFS object, for reporting.
        """
        from hills import lfs

        staged = self.vc.staged_files()
        filters = self.vc.working_attr_filter(staged)
        objects: list[tuple[str, int]] = []
        raw: list[str] = []
        for path in staged:
            if filters.get(path) != "lfs":
                continue
            blob = self.vc.staged_blob_bytes(path)
            if not blob:
                continue  # an empty file is fine as-is
            pointer = lfs.parse_pointer(blob)
            if pointer is None:
                raw.append(path)
            else:
                objects.append((path, pointer.size))
        if raw:
            listed = "\n".join(f"  {p}" for p in raw)
            raise HillsError(
                "these files are marked filter=lfs but were committed as raw bytes, not "
                f"git-LFS pointers:\n{listed}\n\n"
                "git-LFS was not active when they were staged. Fix with:\n"
                "  git lfs install --local\n"
                "  git rm --cached <path> && git add <path>\n"
                "then commit again."
            )
        return objects

    def require_commits(self) -> None:
        self.require_vc()
        if not self.vc.has_commits:
            raise HillsError(
                f"hill {self.name} has no commits yet. "
                f"Review it, then run: hills commit {self.name} -m \"initial\""
            )

    def head_locks(self) -> tuple[locks.Lock, locks.Lock]:
        return (
            locks.parse(
                self.vc.show(f"HEAD:{locks.PRIVATE_LOCK}"), "private", f"{self.name}@HEAD private.lock"
            ),
            locks.parse(
                self.vc.show(f"HEAD:{locks.BLOBS_LOCK}"), "blobs", f"{self.name}@HEAD blobs.lock"
            ),
        )

    def lock_drift(self) -> list[str]:
        """Lock-tracked content that changed without a commit. Git cannot see this."""
        if self.is_lfs():
            return []  # spec-4 has no locks; git (incl. LFS pointers) sees everything
        if not self.vc.has_commits:
            return []
        head_private, head_blobs = self.head_locks()
        disk_private, disk_blobs = locks.build(self.root, self.manifest)
        drift = []
        for head, disk, label in (
            (head_private, disk_private, locks.PRIVATE_LOCK),
            (head_blobs, disk_blobs, locks.BLOBS_LOCK),
        ):
            head_map = {entry["path"]: entry for entry in head.entries}
            disk_map = {entry["path"]: entry for entry in disk.entries}
            for path in sorted(set(head_map) - set(disk_map)):
                drift.append(f"D  {path}  ({label})")
            for path in sorted(set(disk_map) - set(head_map)):
                drift.append(f"A  {path}  ({label})")
            for path in sorted(set(head_map) & set(disk_map)):
                if head_map[path]["sha256"] != disk_map[path]["sha256"]:
                    drift.append(f"M  {path}  ({label})")
        return drift

    # -- materialization --------------------------------------------------

    def materialize(self, dest: Path) -> Path:
        """Lay out the committed version at HEAD in dest.

        The materializer is chosen by the manifest's spec version, not by which git
        dir or attributes are present: spec 4 hills store big files as git-LFS
        objects, everything before that used the blob/private lock mechanism.
        """
        self.require_commits()
        if self.manifest.spec_version >= manifest_mod.LFS_SPEC_VERSION:
            from hills.materialize import materialize_lfs

            commit = self.vc.resolve_commit("HEAD")
            return materialize_lfs(self, commit, dest)
        return self._materialize_legacy_locks(dest)

    def _materialize_legacy_locks(self, dest: Path) -> Path:
        """Spec 1-3: extract the git tree and symlink lock-verified private/blob files,
        so an evaluation never copies gigabytes and never sees uncommitted content."""
        head_private, head_blobs = self.head_locks()
        locks.verify(self.root, head_private, locks.private_paths(self.root))
        locks.verify(self.root, head_blobs, locks.blob_paths(self.root, self.manifest))

        self.vc.archive_to(dest)

        if self.private_dir.is_dir():
            (dest / locks.PRIVATE_DIR).symlink_to(self.private_dir, target_is_directory=True)
        for entry in head_blobs.entries:
            link = dest / entry["path"]
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(self.root / entry["path"])
        return dest
