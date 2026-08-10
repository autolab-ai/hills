"""Helpers for a hill's own tests/ directory.

These run in-process inside the hill's environment, which is fine: a hill's
tests are the author's own code checking their own evaluator. The trust
boundary is `hills eval`, which never imports eval.py in-process.
"""

import importlib.util
import sys
from pathlib import Path

from hills.core_schema import validate_core
from hills.errors import HillsError

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
    return validate_core(result)
