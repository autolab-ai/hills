"""A hill on disk: its manifest, its version control, and its committed identity."""

from dataclasses import dataclass
from pathlib import Path

from hills import locks, manifest as manifest_mod, registry
from hills.errors import HillsError
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
        return cls.at(registry.resolve(name))

    # -- paths ------------------------------------------------------------

    @property
    def entrypoint(self) -> Path:
        return self.root / EVAL_ENTRYPOINT

    @property
    def private_dir(self) -> Path:
        return self.root / locks.PRIVATE_DIR

    # -- version control --------------------------------------------------

    def refresh_exclude(self) -> None:
        """Keep git's view in step with what the manifest says is lock-tracked."""
        if self.vc.initialized:
            self.vc.write_exclude(locks.blob_paths(self.root, self.manifest))

    def require_vc(self) -> None:
        if not self.vc.initialized:
            raise HillsError(
                f"{self.root} has no .vc, so it is not a versioned hill. "
                "Hills are created by `hills new`."
            )

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
        """Lay out the committed version at HEAD in dest, with locked content linked in.

        Everything in git is extracted. Private files and lock-tracked blobs are
        symlinked from the live hill after being verified against the locks, so
        an evaluation never copies gigabytes and never sees uncommitted content.
        """
        self.require_commits()
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
