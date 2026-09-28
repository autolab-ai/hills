"""Evaluator for __NAME__.

The climber can read this file. That is deliberate: transparency about how you
are judged is a feature. The consequence is that anything which would reveal the
answer -- held-out data, hidden test cases, expected outputs -- must live under
private/, never inline here.

This hill ships a dataset under data/ (stored with git-LFS). The evaluator reads
it from HILL/data; the tool guarantees the real bytes are present and verified
before eval() is called, so you can open the files directly.
"""

import json
from pathlib import Path

HILL = Path(__file__).resolve().parent
DATA = HILL / "data"


def eval(submission: Path, *, final: bool = False, tolerance: float = 1e-6) -> dict:
    solution_path = submission / "solution.json"
    if not solution_path.is_file():
        return {
            "passed": False,
            "metrics": [],
            "config": [],
            "details": {"error": "submission must contain solution.json"},
        }

    # The dataset is guaranteed present and verified. Read it however you like;
    # this default just scores against the reference values shipped in the hill.
    reference = json.loads((DATA / "dataset.json").read_text())["targets"]

    solution = json.loads(solution_path.read_text())
    predictions = solution.get("predictions")
    if not isinstance(predictions, list) or len(predictions) != len(reference):
        return {
            "passed": False,
            "metrics": [],
            "config": [],
            "details": {"error": f"solution.json 'predictions' must be a list of {len(reference)} numbers"},
        }

    # Fraction correct within tolerance. Replace with the real scoring; in test
    # mode read the held-out split from private/ instead of the shipped data.
    hits = sum(1 for p, t in zip(predictions, reference) if abs(float(p) - float(t)) <= tolerance)
    score = hits / len(reference)

    return {
        "passed": True,
        "metrics": [{"name": "score", "value": score, "direction": "max"}],
        "config": [
            {"name": "mode", "value": "test" if final else "validation", "primary": True},
            {"name": "tolerance", "value": tolerance, "primary": False},
        ],
        "details": {"n": len(reference)},
    }
