"""Running Python inside a hill's own uv environment.

Each hill carries a pyproject.toml. Its dependencies are resolved into an
environment keyed by the hill version being run, so evaluations never share an
interpreter with the tool or with the user's project.
"""

import os
import shutil
import subprocess
from pathlib import Path

from hills import paths, proc
from hills.errors import HillsError

WORKING_TREE_ENV = "current"


def require_uv() -> str:
    uv = shutil.which("uv")
    if not uv:
        raise HillsError(
            "uv is not on PATH. hills runs each hill in its own uv environment.\n"
            "Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"
        )
    return uv


def env_path(hill_name: str, key: str) -> Path:
    return paths.envs_root() / hill_name / key


def command(project: Path, hill_name: str, env_key: str, argv: list[str]) -> tuple[list[str], dict]:
    """Build the `uv run` invocation and the environment it runs under."""
    if not (project / "pyproject.toml").is_file():
        raise HillsError(
            f"{project} has no pyproject.toml. Every hill declares its own dependencies "
            "so evaluations are isolated; add one (it may have no dependencies at all)."
        )

    uv = require_uv()
    argv_prefix = [uv, "run", "--project", str(project)]
    if (project / "uv.lock").is_file():
        argv_prefix.append("--locked")

    environment = dict(os.environ)
    environment["UV_PROJECT_ENVIRONMENT"] = str(env_path(hill_name, env_key))
    environment["UV_NO_PROGRESS"] = "1"
    environment.pop("VIRTUAL_ENV", None)
    environment.pop("PYTHONHOME", None)
    return argv_prefix + argv, environment


def lock(project: Path, hill_name: str) -> None:
    """Resolve dependencies into uv.lock so committed hills evaluate offline."""
    uv = require_uv()
    result = subprocess.run(
        [uv, "lock", "--project", str(project)],
        cwd=project,
        capture_output=True,
        text=True,
        env={**os.environ, "UV_NO_PROGRESS": "1"},
    )
    if result.returncode != 0:
        raise HillsError(f"uv lock failed for {project}:\n{result.stderr.strip()}")


def run(
    project: Path,
    hill_name: str,
    env_key: str,
    argv: list[str],
    *,
    timeout: float | None = None,
    log_path: Path | None = None,
    stream: bool = False,
    extra_env: dict | None = None,
) -> tuple[int, str]:
    """Run a command in the hill environment, teeing output to a log.

    Returns (exit code, combined output). A timeout kills the whole process
    group and raises TimeoutExpired.
    """
    argv, environment = command(project, hill_name, env_key, argv)
    if extra_env:
        environment.update(extra_env)
    return proc.stream_run(
        argv,
        cwd=project,
        env=environment,
        timeout=timeout,
        log_path=log_path,
        stream=stream,
    )


# Back-compat alias; the implementation now lives in hills.proc.
terminate_group = proc.terminate_group
