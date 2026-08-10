"""Standalone evaluator shim.

Copied into a run directory and executed by `uv run` inside the hill's own
environment. Standard library only: it must import in an environment that knows
nothing about the hills package.

Usage: python _hills_shim.py <invocation.json>
"""

import importlib.util
import json
import os
import sys
import traceback
from pathlib import Path


def jsonable(value):
    """Numpy and torch scalars are ubiquitous in evaluators; everything else must
    already be JSON."""
    item = getattr(value, "item", None)
    if callable(item):
        return item()
    raise TypeError(
        f"eval() returned a {type(value).__name__}, which is not JSON. "
        "Return plain numbers, strings, booleans, lists and dicts."
    )


def main() -> int:
    invocation = json.loads(Path(sys.argv[1]).read_text())
    hill_root = Path(invocation["hill_root"])
    result_path = Path(invocation["result_path"])

    os.chdir(hill_root)
    sys.path.insert(0, str(hill_root))

    try:
        spec = importlib.util.spec_from_file_location("hill_eval", hill_root / "eval.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["hill_eval"] = module
        spec.loader.exec_module(module)

        evaluator = getattr(module, "eval", None)
        if not callable(evaluator):
            raise TypeError("eval.py does not define a callable named 'eval'")

        result = evaluator(
            Path(invocation["submission"]),
            final=invocation["final"],
            **invocation["params"],
        )
        payload = json.dumps({"result": result}, indent=2, default=jsonable)
    except BaseException:
        result_path.write_text(
            json.dumps({"error": {"traceback": traceback.format_exc()}}, indent=2)
        )
        return 1

    result_path.write_text(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
