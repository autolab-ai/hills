"""Machine state lives under ~/.autolab/hills (override with HILLS_HOME)."""

import os
import sys
from pathlib import Path

from hills.errors import HillsError

PROJECT_DIRNAME = ".autolab"
PROJECT_HILLS = "hills"


def home() -> Path:
    override = os.environ.get("HILLS_HOME")
    return Path(override).expanduser() if override else Path.home() / ".autolab" / "hills"


def ensure_home() -> Path:
    root = home()
    if not root.exists():
        root.mkdir(parents=True, exist_ok=True)
        print(f"hills: created machine state at {root}", file=sys.stderr)
    return root


def key_path() -> Path:
    return home() / "key"


def state_root() -> Path:
    return home() / "state"


def runs_root() -> Path:
    return home() / "runs"


def envs_root() -> Path:
    return home() / "envs"


def locks_root() -> Path:
    return home() / "locks"


def project_root(start: Path) -> Path:
    """Nearest ancestor holding a .git or an existing .autolab, else `start`.

    The machine-state directory is itself named .autolab, so it never counts as
    a project marker; otherwise every directory under $HOME would resolve to
    $HOME and hills would be created inside the tool's own state.
    """
    start = start.resolve()
    state = home().resolve()
    for candidate in [start, *start.parents]:
        if (candidate / ".git").exists():
            return candidate
        marker = candidate / PROJECT_DIRNAME
        if marker.is_dir() and marker.resolve() != state.parent:
            return candidate
    return start


def project_hills(start: Path) -> Path:
    """Where hills live inside a project: <project>/.autolab/hills."""
    root = project_root(start)
    hills = root / PROJECT_DIRNAME / PROJECT_HILLS
    if hills.resolve() == home().resolve():
        raise HillsError(
            f"refusing to create a hill in {root}, because {home()} is where hills "
            "keeps its own state (the signing key, attempt logs, run output).\n"
            "Change to your project directory first, or run `git init` here if this "
            "is the project."
        )
    return hills


def _project_markers(start: Path):
    """Every .autolab/ above `start`, skipping the machine-state one."""
    state = home().resolve()
    for candidate in [start.resolve(), *start.resolve().parents]:
        marker = candidate / PROJECT_DIRNAME
        if marker.is_dir() and marker.resolve() != state.parent:
            yield marker / PROJECT_HILLS


def find_hill(name: str, start: Path) -> Path | None:
    """Walk up from `start` for .autolab/hills/<name>, the way git finds .git."""
    for hills in _project_markers(start):
        candidate = hills / name
        if candidate.is_dir():
            return candidate
    return None


def nearby_hills(start: Path) -> list[Path]:
    """Every hill in the nearest project that has any."""
    for hills in _project_markers(start):
        found = sorted(d for d in hills.iterdir() if (d / "hill.yaml").is_file())
        if found:
            return found
    return []
