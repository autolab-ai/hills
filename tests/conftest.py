import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Every test gets its own ~/.autolab/hills."""
    home = tmp_path / "machine"
    monkeypatch.setenv("HILLS_HOME", str(home))
    monkeypatch.setattr("hills.hashing._tool_hash", None, raising=False)
    return home


@pytest.fixture
def project(tmp_path, monkeypatch):
    """An empty git project to create hills inside, with cwd set to it."""
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    monkeypatch.chdir(root)
    return root


@pytest.fixture
def cli():
    """Run a command and return its exit code, letting HillsError propagate so
    tests can assert on the message the user would see."""
    from hills.cli import build_parser

    def run(*argv: str) -> int:
        args = build_parser().parse_args(list(argv))
        return args.func(args)

    return run


@pytest.fixture
def hills_env():
    """Environment for invoking the hills CLI as a subprocess."""
    return {**os.environ, "PYTHONPATH": str(REPO / "src")}
