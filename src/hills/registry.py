"""The global registry maps hill names to paths, so every command works from anywhere."""

import fcntl
import json
from contextlib import contextmanager
from pathlib import Path

from hills import paths
from hills.errors import HillsError, HillNotFound

REGISTRY_VERSION = 1


@contextmanager
def _locked_registry():
    paths.ensure_home()
    lock_file = paths.home() / "registry.lock"
    with open(lock_file, "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def read() -> dict:
    path = paths.registry_path()
    if not path.is_file():
        return {"registry_version": REGISTRY_VERSION, "hills": {}}
    data = json.loads(path.read_text())
    data.setdefault("hills", {})
    return data


def _write(data: dict) -> None:
    paths.ensure_home()
    path = paths.registry_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def register(name: str, root: Path) -> None:
    with _locked_registry():
        data = read()
        existing = data["hills"].get(name)
        if existing and Path(existing["path"]) != root.resolve():
            raise HillsError(
                f"a hill named {name} is already registered at {existing['path']}. "
                "Choose another name, or remove that directory."
            )
        data["hills"][name] = {"path": str(root.resolve()), "tree_hash": None}
        _write(data)


def set_tree_hash(name: str, tree_hash: str) -> None:
    with _locked_registry():
        data = read()
        entry = data["hills"].setdefault(name, {"path": None, "tree_hash": None})
        entry["tree_hash"] = tree_hash
        _write(data)


def forget(name: str) -> None:
    with _locked_registry():
        data = read()
        data["hills"].pop(name, None)
        _write(data)


def entries() -> dict:
    return read()["hills"]


def resolve(name: str) -> Path:
    """Find a hill by name: registry first, then .autolab/hills/<name> under the project."""
    entry = entries().get(name)
    if entry and Path(entry["path"]).is_dir():
        return Path(entry["path"])

    local = paths.project_hills(Path.cwd()) / name
    if local.is_dir():
        register(name, local)
        return local

    known = ", ".join(sorted(entries())) or "(none registered)"
    raise HillNotFound(f"no hill named {name}. Registered hills: {known}")
