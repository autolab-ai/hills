"""Checks on the hill itself, run by `hills check`.

Assert that a known-good submission scores as expected and that a broken one is
rejected. These are the tests that stop the evaluator from drifting.
"""

from pathlib import Path

from hills import run_evaluator

HILL = Path(__file__).resolve().parents[1]
EXAMPLES = HILL / "examples"


def test_baseline_scores():
    result = run_evaluator(HILL, EXAMPLES / "baseline")
    assert result["passed"]
    assert result["metrics"][0]["name"] == "score"


def test_missing_solution_is_rejected(tmp_path):
    result = run_evaluator(HILL, tmp_path)
    assert not result["passed"]
    assert "solution.json" in result["details"]["error"]
