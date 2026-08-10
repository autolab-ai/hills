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


def registry_path() -> Path:
    return home() / "registry.json"


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
            "keeps its own state (the registry, the signing key, run logs).\n"
            "Change to your project directory first, or run `git init` here if this "
            "is the project."
        )
    return hills
