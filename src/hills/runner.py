"""`hills eval`: run a frozen hill's evaluator against a submission directory."""

import json
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from hills import devlock, locks, paths, report as report_mod, state, uvenv
from hills.canonical import dumps
from hills.core_schema import validate_core
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
            timeout=hill.manifest.watchdog_timeout_s,
            log_path=log_path,
            stream=stream,
            extra_env=extra_env,
        )
    except subprocess.TimeoutExpired:
        return None, (
            f"watchdog killed the evaluator after {hill.manifest.watchdog_timeout_s}s. "
            f"Output: {log_path}"
        )

    if not result_path.is_file():
        return None, (
            f"the evaluator exited with code {code} without writing a result.\n"
            + _tail(output)
        )

    payload = json.loads(result_path.read_text())
    if "error" in payload:
        return None, "the evaluator raised:\n" + payload["error"]["traceback"].rstrip()

    return validate_core(payload["result"]), None


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
