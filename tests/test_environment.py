"""spec_version 3: a hill may declare the container image its evaluator runs in."""

import os
from pathlib import Path

import pytest

from hills import manifest, runtime
from hills.check import check
from hills.errors import EvaluatorFailed, HillsError, ManifestError
from hills.hill import Hill

BASE = (
    "spec_version: {v}\nname: t\nversion: 0.1.0\n"
    "watchdog_timeout_s: 60\nmetrics: [{{name: score, direction: max}}]\n"
)


# ── manifest ──────────────────────────────────────────────────────────────


def test_spec3_parses_environment_image():
    m = manifest.loads(BASE.format(v=3) + "environment: {image: 'ghcr.io/x/y@sha256:abc'}\n")
    assert m.environment is not None
    assert m.environment.image == "ghcr.io/x/y@sha256:abc"
    assert m.as_json()["environment"] == {"image": "ghcr.io/x/y@sha256:abc"}


def test_spec3_without_environment_is_none():
    m = manifest.loads(BASE.format(v=3))
    assert m.environment is None
    assert "environment" not in m.as_json()


def test_environment_key_is_rejected_below_spec3():
    text = (
        "spec_version: 2\nname: t\nversion: 0.1.0\nwatchdog_timeout_s: 60\n"
        "metrics: [{name: score, direction: max}]\nenvironment: {image: x}\n"
    )
    with pytest.raises(ManifestError, match="unknown keys"):
        manifest.loads(text)


def test_environment_validation():
    with pytest.raises(ManifestError, match="environment must be a mapping"):
        manifest.loads(BASE.format(v=3) + "environment: 'ghcr.io/x'\n")
    with pytest.raises(ManifestError, match="environment.image must be"):
        manifest.loads(BASE.format(v=3) + "environment: {image: ''}\n")
    with pytest.raises(ManifestError, match="unknown keys"):
        manifest.loads(BASE.format(v=3) + "environment: {image: x, runtime: docker}\n")


# ── runtime command construction ──────────────────────────────────────────


def test_build_command_docker_mounts_env_user_and_entrypoint():
    cmd = runtime.build_command(
        "docker",
        "img:tag",
        ["python", "shim"],
        workdir=Path("/w"),
        binds=[(Path("/run"), False), (Path("/hill"), True)],
        env={"K": "V"},
    )
    assert cmd[:4] == ["docker", "run", "--rm", "--init"]
    assert "--user" in cmd
    assert cmd[cmd.index("--entrypoint") + 1] == "python"  # neutralizes image ENTRYPOINT
    assert "-w" in cmd and "/w" in cmd
    assert "/run:/run:rw" in cmd
    assert "/hill:/hill:ro" in cmd
    assert "K=V" in cmd
    assert cmd[-2:] == ["img:tag", "shim"]  # argv[1:] follows the image


def test_build_command_podman_keeps_id_not_user():
    cmd = runtime.build_command(
        "podman", "img", ["p"], workdir=Path("/w"), binds=[(Path("/r"), False)], env={}
    )
    assert cmd[0] == "podman" and cmd[1] == "run"
    assert "--userns=keep-id" in cmd
    assert "--user" not in cmd
    assert "/r:/r:rw" in cmd


def test_build_command_apptainer_uses_docker_transport_and_clean_env():
    cmd = runtime.build_command(
        "apptainer",
        "ghcr.io/x/y",
        ["python"],
        workdir=Path("/w"),
        binds=[(Path("/run"), False), (Path("/hill"), True)],
        env={"K": "V"},
    )
    assert cmd[:2] == ["apptainer", "exec"]
    assert "--cleanenv" in cmd and "--no-eval" in cmd
    assert "--pwd" in cmd and "/w" in cmd
    assert "/run:/run" in cmd  # rw bind has no suffix in apptainer
    assert "/hill:/hill:ro" in cmd
    assert "K=V" in cmd
    assert "docker://ghcr.io/x/y" in cmd


def test_apptainer_keeps_a_sif_or_uri_verbatim():
    for image in ("local.sif", "docker://x", "oras://y/z"):
        cmd = runtime.build_command(
            "apptainer", image, ["p"], workdir=Path("/w"), binds=[], env={}
        )
        assert image in cmd
        assert f"docker://{image}" not in cmd


def test_detect_and_require(monkeypatch):
    monkeypatch.setattr(runtime, "_usable", lambda n: True)
    monkeypatch.setattr(runtime.shutil, "which", lambda n: f"/usr/bin/{n}" if n == "podman" else None)
    assert runtime.detect() == "podman"
    monkeypatch.setattr(runtime.shutil, "which", lambda n: None)
    assert runtime.detect() is None
    with pytest.raises(HillsError, match="container runtime"):
        runtime.require()


def test_singularity_is_a_recognized_runtime(monkeypatch):
    # singularity is apptainer's sibling: daemonless, same exec CLI.
    assert "singularity" in runtime.RUNTIMES
    monkeypatch.setattr(runtime.shutil, "which", lambda n: f"/usr/bin/{n}" if n == "singularity" else None)
    monkeypatch.setattr(runtime, "_usable", lambda n: True)
    assert runtime.detect() == "singularity"
    cmd = runtime.build_command(
        "singularity", "img", ["python", "shim"], workdir=Path("/w"), binds=[(Path("/r"), False)], env={"K": "V"}
    )
    assert cmd[:2] == ["singularity", "exec"]
    assert "--cleanenv" in cmd and "--no-eval" in cmd
    assert "docker://img" in cmd  # converts an OCI ref on the fly, like apptainer


def test_runtime_override_forces_a_choice(monkeypatch):
    # Everything is usable; the override / HILLS_RUNTIME picks one regardless of order.
    monkeypatch.setattr(runtime.shutil, "which", lambda n: f"/usr/bin/{n}")
    monkeypatch.setattr(runtime, "_usable", lambda n: True)
    assert runtime.detect() == "docker"  # default order
    assert runtime.detect("apptainer") == "apptainer"
    monkeypatch.setenv("HILLS_RUNTIME", "podman")
    assert runtime.detect() == "podman"  # env honored
    monkeypatch.delenv("HILLS_RUNTIME", raising=False)


def test_require_errors_clearly_on_a_forced_but_unusable_runtime(monkeypatch):
    monkeypatch.setattr(runtime.shutil, "which", lambda n: None)  # nothing on PATH
    monkeypatch.setattr(runtime, "_usable", lambda n: False)
    with pytest.raises(HillsError, match="requested container runtime 'apptainer'"):
        runtime.require("apptainer")
    with pytest.raises(HillsError, match="unknown container runtime"):
        runtime.require("nope")


def test_detect_skips_a_runtime_whose_daemon_is_down(monkeypatch):
    # docker's client exists but its daemon is unreachable; a working podman wins.
    monkeypatch.setattr(runtime.shutil, "which", lambda n: f"/usr/bin/{n}" if n in ("docker", "podman") else None)
    monkeypatch.setattr(runtime, "_usable", lambda n: n == "podman")
    assert runtime.detect() == "podman"


def test_ensure_image_skips_pull_when_present(monkeypatch):
    calls = []

    class Done:
        returncode = 0

    def fake_run(argv, **kw):
        calls.append(argv)
        return Done()

    monkeypatch.setattr(runtime.subprocess, "run", fake_run)
    code, _ = runtime.ensure_image("docker", "img:tag")
    assert code == 0
    assert calls and calls[0][:3] == ["docker", "image", "inspect"]
    assert not any("pull" in c for c in calls)  # present -> no pull


# ── end to end: no runtime available ──────────────────────────────────────

IMAGE_YAML = (
    "spec_version: 3\nname: demo\nversion: 0.1.0\nwatchdog_timeout_s: 60\n"
    "metrics: [{name: score, direction: max}]\nenvironment: {image: 'python:3.12-slim'}\n"
)


def _image_hill(project, cli):
    cli("new", "demo")
    hill = project / ".autolab" / "hills" / "demo"
    (hill / "hill.yaml").write_text(IMAGE_YAML)
    return hill


def test_eval_without_a_runtime_reports_clearly(project, cli, monkeypatch):
    monkeypatch.setattr("hills.runtime.detect", lambda *a, **k: None)
    _image_hill(project, cli)
    sub = project / "attempt"
    sub.mkdir()
    (sub / "solution.json").write_text('{"value": 3}')
    with pytest.raises(EvaluatorFailed, match="container runtime"):
        cli("eval", str(sub), "-H", "demo", "--current")


def test_check_without_a_runtime_records_a_dependency_failure(project, cli, monkeypatch):
    monkeypatch.setattr("hills.runtime.detect", lambda *a, **k: None)
    _image_hill(project, cli)
    result = check(Hill.resolve("demo"))
    assert not result.ok
    assert any(not ok and "container runtime" in detail for _, ok, detail in result.steps)


# ── end to end: a real container (opt in with HILLS_TEST_CONTAINERS=1) ─────

_RUN_CONTAINERS = os.environ.get("HILLS_TEST_CONTAINERS") == "1" and runtime.detect() is not None

REAL_EVAL = (
    "import json, sys\n"
    "def eval(submission, *, final=False, **params):\n"
    "    value = json.loads((submission / 'solution.json').read_text())['value']\n"
    "    return {'passed': True, 'metrics': [{'name': 'score', 'value': float(value), "
    "'direction': 'max'}]}\n"
)


@pytest.mark.skipif(not _RUN_CONTAINERS, reason="set HILLS_TEST_CONTAINERS=1 with a runtime")
def test_real_image_scores_end_to_end(project, cli, capsys):
    import json

    hill = _image_hill(project, cli)
    (hill / "eval.py").write_text(REAL_EVAL)
    sub = project / "attempt"
    sub.mkdir()
    (sub / "solution.json").write_text('{"value": 7}')
    assert cli("eval", str(sub), "-H", "demo", "--current") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["metrics"][0]["value"] == 7.0


@pytest.mark.skipif(not _RUN_CONTAINERS, reason="set HILLS_TEST_CONTAINERS=1 with a runtime")
def test_real_image_official_run_uses_the_materialized_hill(project, cli, capsys):
    import json

    hill = _image_hill(project, cli)
    (hill / "eval.py").write_text(REAL_EVAL)
    assert cli("commit", "demo", "-m", "image hill", "--no-tests") == 0
    sub = project / "attempt"
    sub.mkdir()
    (sub / "solution.json").write_text('{"value": 5}')
    assert cli("eval", str(sub), "-H", "demo") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["official"] is True
    assert report["metrics"][0]["value"] == 5.0


# ── runtime=host: run the evaluator directly, no container ─────────────────
# The "pod = image" path: when the environment already IS the hill's image,
# HILLS_RUNTIME=host runs the evaluator natively (no nesting), so it needs no
# container runtime and works in plain CI.


def test_host_runtime_runs_the_evaluator_without_a_container(project, cli, monkeypatch, capsys):
    import json

    monkeypatch.setenv("HILLS_RUNTIME", "host")
    # No container runtime available — host mode must not need one.
    monkeypatch.setattr("hills.runtime.detect", lambda *a, **k: None)
    hill = _image_hill(project, cli)
    (hill / "eval.py").write_text(REAL_EVAL)
    sub = project / "attempt"
    sub.mkdir()
    (sub / "solution.json").write_text('{"value": 11}')
    assert cli("eval", str(sub), "-H", "demo", "--current") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["metrics"][0]["value"] == 11.0


def test_host_python_skips_the_launcher_venv(monkeypatch, tmp_path):
    # The image's python must win over the ephemeral one a launcher (uv tool
    # run) prepends to PATH.
    from hills import runner

    img_bin = tmp_path / "usr" / "bin"
    img_bin.mkdir(parents=True)
    img_py = img_bin / "python3"
    img_py.write_text("#!/bin/sh\n")
    img_py.chmod(0o755)
    uv_bin = tmp_path / ".cache" / "uv" / "env" / "bin"
    uv_bin.mkdir(parents=True)
    (uv_bin / "python3").write_text("#!/bin/sh\n")
    (uv_bin / "python3").chmod(0o755)
    monkeypatch.delenv("HILLS_HOST_PYTHON", raising=False)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setenv("PATH", f"{uv_bin}:{img_bin}")
    assert runner._host_python() == str(img_py)
    # Explicit override wins.
    monkeypatch.setenv("HILLS_HOST_PYTHON", "/opt/py/bin/python")
    assert runner._host_python() == "/opt/py/bin/python"
