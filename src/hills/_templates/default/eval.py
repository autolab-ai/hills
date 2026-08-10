"""Evaluator for __NAME__.

The climber can read this file. That is deliberate: transparency about how you
are judged is a feature. The consequence is that anything which would reveal the
answer -- held-out data, hidden test cases, expected outputs -- must live under
private/, never inline here.
"""

import json
from pathlib import Path

HILL = Path(__file__).resolve().parent


def eval(submission: Path, *, final: bool = False, tolerance: float = 1e-6) -> dict:
    solution_path = submission / "solution.json"
    if not solution_path.is_file():
        return {
            "passed": False,
            "metrics": [],
            "config": [],
            "details": {"error": "submission must contain solution.json"},
        }

    solution = json.loads(solution_path.read_text())
    value = solution.get("value")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return {
            "passed": False,
            "metrics": [],
            "config": [],
            "details": {"error": f"solution.json 'value' must be a number, got {value!r}"},
        }

    # Replace this with the real scoring. In test mode read the held-out split
    # from private/ instead of the validation data.
    score = float(value)

    return {
        "passed": True,
        "metrics": [{"name": "score", "value": score, "direction": "max"}],
        "config": [
            {"name": "mode", "value": "test" if final else "validation", "primary": True},
            {"name": "tolerance", "value": tolerance, "primary": False},
        ],
        "details": {},
    }
