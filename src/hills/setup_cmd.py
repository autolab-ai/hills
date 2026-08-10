"""`hills setup`: install the agent skill into whichever harnesses are present.

The primary install path is the other direction (`npx skills add autolab-ai/hills`,
which then bootstraps the CLI). This is the reverse door for people who
installed the CLI first.
"""

import shutil
from dataclasses import dataclass
from pathlib import Path

from hills.errors import HillsError

SKILL_NAME = "hills"


@dataclass(frozen=True)
class Harness:
    name: str
    marker: Path
    skills_dir: Path


def skill_source() -> Path:
    packaged = Path(__file__).resolve().parent / "_skill"
    if packaged.is_dir():
        return packaged
    repo = Path(__file__).resolve().parents[2] / "skills" / SKILL_NAME
    if repo.is_dir():
        return repo
    raise HillsError("the packaged agent skill is missing from this hills installation")


def harnesses(home: Path | None = None) -> list[Harness]:
    home = home or Path.home()
    return [
        Harness("claude-code", home / ".claude", home / ".claude" / "skills"),
        Harness("codex", home / ".codex", home / ".codex" / "skills"),
        Harness("cursor", home / ".cursor", home / ".cursor" / "skills"),
    ]


def detected(home: Path | None = None) -> list[Harness]:
    return [harness for harness in harnesses(home) if harness.marker.is_dir()]


def install(targets: list[Harness]) -> list[tuple[str, Path]]:
    source = skill_source()
    installed = []
    for harness in targets:
        destination = harness.skills_dir / SKILL_NAME
        if destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)
        installed.append((harness.name, destination))
    return installed
