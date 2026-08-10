"""Machine state lives under ~/.autolab/hills (override with HILLS_HOME)."""

import os
import sys
from pathlib import Path

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
    """Nearest ancestor holding a .git or an existing .autolab, else `start`."""
    start = start.resolve()
    for candidate in [start, *start.parents]:
        if (candidate / ".git").exists() or (candidate / PROJECT_DIRNAME).is_dir():
            return candidate
    return start


def project_hills(start: Path) -> Path:
    """Where hills live inside a project: <project>/.autolab/hills."""
    return project_root(start) / PROJECT_DIRNAME / PROJECT_HILLS
