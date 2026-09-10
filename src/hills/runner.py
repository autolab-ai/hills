"""`hills eval`: run a frozen hill's evaluator against a submission directory."""

import json
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from hills import devlock, locks, paths, proc, report as report_mod, runtime, state, uvenv
from hills.canonical import dumps
from hills.core_schema import metrics_prefix_violation, validate_core
from hills.errors import DirtyHill, EvaluatorFailed, HillsError
from hills.hashing import SKIP_DIRS, SKIP_FILES, SKIP_SUFFIXES, hash_tree
from hills.hill import Hill

SHIM_NAME = "_hills_shim.py"
KEEP_RUNS = 20


@dataclass
class EvalOutcome:
    report: dict
    run_dir: Path
    report_path: Path
    attempt: dict


def _ignore_noise(directory, names):
    return {
        name
        for name in names
        if name in SKIP_DIRS or name in SKIP_FILES or name.endswith(SKIP_SUFFIXES)
    }


def snapshot_submission(source: Path, dest: Path) -> None:
    """Copy the submission so the climber cannot change it mid-evaluation."""
    if not source.is_dir():
        raise HillsError(f"submission {source} is not a directory. A submission is a directory.")
    shutil.copytree(source, dest, ignore=_ignore_noise, symlinks=True)


def new_run_dir(hill_name: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = paths.runs_root() / hill_name
    root.mkdir(parents=True, exist_ok=True)
    run_dir = root / f"{stamp}-{uuid.uuid4().hex[:8]}"
    run_dir.mkdir()
    _prune_runs(root)
    return run_dir


def _prune_runs(root: Path) -> None:
    runs = sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.name)
    for stale in runs[:-KEEP_RUNS]:
        shutil.rmtree(stale, ignore_errors=True)


def evaluate(
    hill: Hill,
    submission: Path,
    *,
    param_overrides: dict,
    final: bool = False,
    force: bool = False,
    current: bool = False,
    queue: bool = False,
    stream: bool = False,
) -> EvalOutcome:
    submission = Path(submission).resolve()
    if not submission.is_dir():
        raise HillsError(f"submission {submission} is not a directory. A submission is a directory.")
    params = hill.manifest.resolve_params(param_overrides)
    hill.require_vc()
    hill.refresh_exclude()

    run_dir = new_run_dir(hill.name)
    hill_root, tree_hash, commit, official, official_reason, env_key = _prepare_hill(
        hill, run_dir, force=force, current=current
    )

    snapshot = run_dir / "submission"
    snapshot_submission(submission, snapshot)
    submission_hash = hash_tree(snapshot)
    git_label = report_mod.submission_git(submission)

    device = devlock.resolve_device(hill.manifest.exclusive) if hill.manifest.exclusive else None
    with devlock.hold(device, queue):
        core, error = _run_evaluator(
            hill, hill_root, run_dir, snapshot, params, final, env_key, stream
        )

    report = None
    if core:
        report = report_mod.build(
            hill_name=hill.name,
            tree_hash=tree_hash,
            commit=commit,
            submission_hash=submission_hash,
            submission_git_label=git_label,
            core=core,
            params=params,
            final=final,
            official=official,
            official_reason=official_reason,
            hill_spec_version=hill.manifest.spec_version,
            tool_version=_tool_version(),
        )

    attempt = _log_attempt(
        hill, tree_hash, submission_hash, git_label, params, final, official,
        official_reason, report, error, run_dir,
    )

    if error:
        raise EvaluatorFailed(error)

    report_path = run_dir / "report.json"
    report_path.write_text(dumps(report) + "\n")
    return EvalOutcome(report=report, run_dir=run_dir, report_path=report_path, attempt=attempt)


def _tool_version() -> str:
    from hills import __version__

    return __version__


def _prepare_hill(hill: Hill, run_dir: Path, *, force: bool, current: bool):
    """Decide which version of the hill is being evaluated and lay it out."""
    if current:
        return hill.root, None, None, False, "dirty-tree", uvenv.WORKING_TREE_ENV

    hill.require_commits()
    dirty = hill.vc.status_porcelain()
    drift = hill.lock_drift()
    if (dirty or drift) and not force:
        details = "\n".join(f"  {line}" for line in [*dirty, *drift])
        raise DirtyHill(
            f"hill {hill.name} has uncommitted changes:\n{details}\n"
            f"Commit them (hills commit {hill.name} -m \"...\"), "
            "use --force to evaluate the last committed version, "
            "or --current to evaluate the working tree unofficially."
        )
    if dirty or drift:
        print(
            f"hills: warning: {hill.name} has uncommitted changes; "
            "evaluating the last committed version anyway (--force)",
            file=sys.stderr,
        )

    materialized = hill.materialize(run_dir / "hill")
    tree_hash = hill.vc.tree_hash()
    return materialized, tree_hash, hill.vc.commit_hash(), True, None, tree_hash


def _host_python() -> str:
    """The interpreter for an in-image (runtime=host) evaluation.

    The evaluator must run under the IMAGE's Python — the one that has the
    hill's dependencies — not the ephemeral interpreter a launcher like
    ``uv tool run`` created just to start hills (which prepends its own venv to
    PATH, so a bare ``python`` would resolve there and miss image packages).
    Honor ``HILLS_HOST_PYTHON`` if the caller set it; otherwise find python on
    PATH with the active venv / uv tool dirs removed; last resort ``python3``.
    """
    explicit = os.environ.get("HILLS_HOST_PYTHON")
    if explicit:
        return explicit
    venv_bin = ""
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        venv_bin = str(Path(venv) / "bin")
    parts = [
        p
        for p in os.environ.get("PATH", "").split(os.pathsep)
        if p and p != venv_bin and "/uv/" not in p and "/.cache/uv/" not in p
    ]
    for name in ("python3", "python"):
        found = shutil.which(name, path=os.pathsep.join(parts))
        if found:
            return found
    return "python3"


def _run_evaluator(hill, hill_root, run_dir, submission, params, final, env_key, stream):
    """Spawn the shim under the watchdog. Returns (core, error message)."""
    shim = run_dir / SHIM_NAME
    shutil.copyfile(Path(__file__).with_name("_shim.py"), shim)

    result_path = run_dir / "result.json"
    invocation = run_dir / "invocation.json"
    invocation.write_text(
        dumps(
            {
                "hill_root": str(hill_root),
                "submission": str(submission),
                "params": params,
                "final": final,
                "result_path": str(result_path),
            }
        )
    )

    log_path = run_dir / "evaluator.log"
    extra_env = {"HILLS_RUN_DIR": str(run_dir), "HILLS_HILL_ROOT": str(hill_root)}
    # For an official run the version being scored is the materialized hill, so
    # its environment and watchdog come from there, not the working tree (which
    # --force may have moved on).
    run_manifest = hill.manifest
    if Path(hill_root).resolve() != Path(hill.root).resolve():
        from hills import manifest as manifest_mod

        run_manifest = manifest_mod.load(Path(hill_root) / "hill.yaml")
    image = run_manifest.environment.image if run_manifest.environment else None
    timeout = run_manifest.watchdog_timeout_s

    if image and (os.environ.get("HILLS_RUNTIME") or "").strip() == "host":
        # The current environment already IS the hill's image (e.g. a rented pod
        # booted from environment.image), so run the evaluator directly — no
        # nested container. The shim is stdlib-only; eval.py's deps and tools
        # come from the ambient image. This is what makes image hills work on
        # hosts where nesting is impossible (unprivileged pods with no userns).
        if stream:
            print("hills: running the evaluator in-image (runtime=host)", flush=True)
        try:
            code, output = proc.stream_run(
                [_host_python(), str(shim), str(invocation)],
                cwd=run_dir,
                env={**os.environ, **extra_env},
                timeout=timeout,
                log_path=log_path,
                stream=stream,
            )
        except subprocess.TimeoutExpired:
            return None, (
                f"watchdog killed the evaluator after {timeout}s. Output: {log_path}"
            )
    elif image:
        # The image is the environment: run the (stdlib-only) shim inside it.
        try:
            runtime_name = runtime.require()
        except HillsError as error:
            return None, str(error)
        if stream:
            # Make the image-prep phase visible in the node's run log instead of
            # a blank pane while a multi-GB image downloads on first use.
            print(f"hills: preparing evaluator image {image} ...", flush=True)
        warm, warm_output = runtime.ensure_image(
            runtime_name, image, log_path=run_dir / "env.log", stream=stream
        )
        if warm != 0:
            return None, f"could not pull the hill's image {image}:\n{warm_output.strip()}"
        if stream:
            print("hills: image ready; starting the evaluator", flush=True)
        # run_dir (rw) holds the shim, invocation, submission, result.json and,
        # for an official run, the materialized hill. Bind whatever else the
        # evaluator needs at its own path so the absolute paths in
        # invocation.json resolve inside the container:
        #   - hill_root when it is the working tree (--current), writable;
        #   - the live hill root read-only, so a materialized private/ symlink
        #     resolves to its target.
        def _under(child: Path, parent: Path) -> bool:
            try:
                Path(child).resolve().relative_to(Path(parent).resolve())
                return True
            except ValueError:
                return False

        binds: list[tuple[Path, bool]] = [(run_dir, False)]
        if not _under(Path(hill_root), run_dir):
            binds.append((Path(hill_root), False))
        if not _under(Path(hill.root), run_dir) and (
            Path(hill.root).resolve() != Path(hill_root).resolve()
        ):
            binds.append((Path(hill.root), True))
        try:
            code, output = runtime.run(
                image,
                ["python", str(shim), str(invocation)],
                workdir=run_dir,
                binds=binds,
                env=extra_env,
                timeout=timeout,
                log_path=log_path,
                stream=stream,
                runtime=runtime_name,
            )
        except subprocess.TimeoutExpired:
            return None, (
                f"watchdog killed the evaluator after {timeout}s. Output: {log_path}"
            )
    else:
        warm, warm_output = uvenv.run(
            hill_root, hill.name, env_key, ["python", "-c", "pass"], log_path=run_dir / "env.log"
        )
        if warm != 0:
            return None, f"could not prepare the hill environment:\n{warm_output.strip()}"

        try:
            code, output = uvenv.run(
                hill_root,
                hill.name,
                env_key,
                ["python", str(shim), str(invocation)],
                timeout=timeout,
                log_path=log_path,
                stream=stream,
                extra_env=extra_env,
            )
        except subprocess.TimeoutExpired:
            return None, (
                f"watchdog killed the evaluator after {timeout}s. Output: {log_path}"
            )

    if not result_path.is_file():
        return None, (
            f"the evaluator exited with code {code} without writing a result.\n"
            + _tail(output)
        )

    payload = json.loads(result_path.read_text())
    if "error" in payload:
        return None, "the evaluator raised:\n" + payload["error"]["traceback"].rstrip()

    core = validate_core(payload["result"])
    if core["passed"] and run_manifest.metrics:
        declared = [metric.as_json() for metric in run_manifest.metrics]
        violation = metrics_prefix_violation(declared, core["metrics"])
        if violation:
            return None, (
                "the evaluator's report does not match the metrics declared in "
                "hill.yaml: " + violation
            )
    return core, None


def _tail(text: str, lines: int = 40) -> str:
    kept = text.strip().splitlines()[-lines:]
    return "\n".join(kept)


def _log_attempt(
    hill, tree_hash, submission_hash, git_label, params, final, official,
    official_reason, report, error, run_dir,
):
    entry = {
        "timestamp": report_mod.now_utc(),
        "submission_hash": submission_hash,
        "submission_git": git_label,
        "params": params,
        "final": final,
        "official": official,
        "official_reason": official_reason,
        "run_dir": str(run_dir),
        "passed": bool(report and report["passed"]),
        "metrics": report["metrics"] if report else [],
        "config": report["config"] if report else [],
        "error": error,
        "signature": report["signature"] if report else None,
    }
    return state.append(hill.name, tree_hash, entry)


def verify_hill_content(hill: Hill) -> None:
    """Standalone integrity check of private/ and lock-tracked blobs against HEAD."""
    hill.require_commits()
    head_private, head_blobs = hill.head_locks()
    locks.verify(hill.root, head_private, locks.private_paths(hill.root))
    locks.verify(hill.root, head_blobs, locks.blob_paths(hill.root, hill.manifest))
