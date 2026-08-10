"""`hills check`: manifest validation, a dry validation of the evaluator contract,
and the hill's own tests. `hills commit` refuses to commit if check fails.
"""

import json
import tempfile
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

import hills
from hills import uvenv
from hills.hill import EVAL_ENTRYPOINT, PYPROJECT_NAME, README_NAME, Hill

INTROSPECT = textwrap.dedent(
    """
    import importlib.util, inspect, json, sys
    from pathlib import Path

    hill = Path(sys.argv[1])
    declared = json.loads(sys.argv[2])
    sys.path.insert(0, str(hill))

    spec = importlib.util.spec_from_file_location("hill_eval", hill / "eval.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["hill_eval"] = module
    spec.loader.exec_module(module)

    problems = []
    evaluator = getattr(module, "eval", None)
    if not callable(evaluator):
        problems.append("eval.py does not define a callable named 'eval'")
    else:
        signature = inspect.signature(evaluator)
        parameters = list(signature.parameters.values())
        takes_kwargs = any(p.kind is p.VAR_KEYWORD for p in parameters)
        names = [p.name for p in parameters]
        if not names or names[0] != "submission":
            problems.append(
                "eval()'s first parameter must be named 'submission', got " + str(names[:1])
            )
        for needed in ["final"] + declared:
            if needed not in names and not takes_kwargs:
                problems.append(
                    "eval() does not accept '" + needed + "'; add it or accept **params"
                )

    print(json.dumps({"problems": problems}))
    """
).strip()


@dataclass
class CheckResult:
    ok: bool = True
    steps: list[tuple[str, bool, str]] = field(default_factory=list)

    def record(self, name: str, ok: bool, detail: str = "") -> None:
        self.steps.append((name, ok, detail))
        self.ok = self.ok and ok


def _required_files(hill: Hill, result: CheckResult) -> None:
    missing = [
        name
        for name in (EVAL_ENTRYPOINT, README_NAME, PYPROJECT_NAME)
        if not (hill.root / name).is_file()
    ]
    if missing:
        result.record("layout", False, "missing: " + ", ".join(missing))
        return
    readme = (hill.root / README_NAME).read_text().strip()
    if len(readme) < 40:
        result.record(
            "layout",
            False,
            "README.md is the contract the climbing agent reads; it needs real content",
        )
        return
    result.record("layout", True, f"{EVAL_ENTRYPOINT}, {README_NAME}, {PYPROJECT_NAME}")


def _dry_validate(hill: Hill, result: CheckResult, script_dir: Path) -> None:
    script = script_dir / "_introspect.py"
    script.write_text(INTROSPECT + "\n")
    declared = json.dumps(sorted(hill.manifest.params))
    code, output = uvenv.run(
        hill.root,
        hill.name,
        uvenv.WORKING_TREE_ENV,
        ["python", str(script), str(hill.root), declared],
    )
    if code != 0:
        result.record("evaluator contract", False, output.strip())
        return

    payload = json.loads(output.strip().splitlines()[-1])
    problems = payload["problems"]
    if problems:
        result.record("evaluator contract", False, "; ".join(problems))
        return
    signature = ", ".join(["submission", "final", *sorted(hill.manifest.params)])
    result.record("evaluator contract", True, f"eval({signature}) imports and binds")


def _run_tests(hill: Hill, result: CheckResult) -> None:
    tests = hill.root / "tests"
    if not tests.is_dir() or not any(tests.glob("**/*.py")):
        result.record("tests", True, "no tests/ directory (optional, but recommended)")
        return

    tool_src = str(Path(hills.__file__).resolve().parent.parent)
    has_pytest, _ = uvenv.run(
        hill.root,
        hill.name,
        uvenv.WORKING_TREE_ENV,
        ["python", "-c", "import pytest"],
        extra_env={"PYTHONPATH": tool_src},
    )
    if has_pytest == 0:
        runs = [["python", "-m", "pytest", "-q", str(tests)]]
    else:
        runs = [["python", str(script)] for script in sorted(tests.rglob("*.py"))]

    output = ""
    for argv in runs:
        code, output = uvenv.run(
            hill.root,
            hill.name,
            uvenv.WORKING_TREE_ENV,
            argv,
            extra_env={"PYTHONPATH": tool_src},
        )
        if code != 0:
            result.record("tests", False, output.strip())
            return
    summary = output.strip().splitlines()[-1] if output.strip() else "passed"
    result.record("tests", True, summary)


def check(hill: Hill, *, run_tests: bool = True) -> CheckResult:
    result = CheckResult()
    result.record("manifest", True, f"{hill.manifest.name} {hill.manifest.version}")
    _required_files(hill, result)
    if not result.ok:
        return result

    uvenv.lock(hill.root, hill.name)
    result.record("dependencies", True, "uv.lock is up to date")

    with tempfile.TemporaryDirectory(prefix="hills-check-") as scratch:
        _dry_validate(hill, result, Path(scratch))
    if not result.ok:
        return result

    if run_tests:
        _run_tests(hill, result)
    return result
