"""Helpers for a hill's own tests/ directory.

These run in-process inside the hill's environment, which is fine: a hill's
tests are the author's own code checking their own evaluator. The trust
boundary is `hills eval`, which never imports eval.py in-process.
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

from hills.core_schema import metrics_prefix_violation, validate_core
from hills.errors import CoreSchemaError, HillsError

DECLARED_METRICS_ENV = "HILLS_DECLARED_METRICS"

__all__ = ["load_evaluator", "run_evaluator", "validate_core"]


def load_evaluator(hill_path):
    """Import a hill's eval.py and return its eval function."""
    hill_path = Path(hill_path).resolve()
    entrypoint = hill_path / "eval.py"
    if not entrypoint.is_file():
        raise HillsError(f"no eval.py at {hill_path}")

    spec = importlib.util.spec_from_file_location("hill_eval", entrypoint)
    module = importlib.util.module_from_spec(spec)
    if str(hill_path) not in sys.path:
        sys.path.insert(0, str(hill_path))
    sys.modules["hill_eval"] = module
    spec.loader.exec_module(module)

    evaluator = getattr(module, "eval", None)
    if not callable(evaluator):
        raise HillsError(f"{entrypoint} does not define a callable named 'eval'")
    return evaluator


def run_evaluator(hill_path, submission_path, *, final: bool = False, **params) -> dict:
    """Run a hill's evaluator against a submission and return the validated core dict."""
    evaluator = load_evaluator(hill_path)
    result = evaluator(Path(submission_path).resolve(), final=final, **params)
    core = validate_core(result)
    # `hills check` exports the hill.yaml metrics declaration when it runs the
    # hill's tests, so a report that drifts from it fails here, in the author's
    # own test run, with the same rule `hills eval` enforces.
    declared = os.environ.get(DECLARED_METRICS_ENV)
    if declared and core["passed"]:
        violation = metrics_prefix_violation(json.loads(declared), core["metrics"])
        if violation:
            raise CoreSchemaError(
                "the report does not match the metrics declared in hill.yaml: " + violation
            )
    return core
