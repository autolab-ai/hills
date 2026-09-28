"""Smoke test for the __NAME__ evaluator."""

from pathlib import Path

from eval import eval

HILL = Path(__file__).resolve().parent.parent


def test_baseline_scores_perfectly():
    report = eval(HILL / "examples" / "baseline", final=False)
    assert report["passed"]
    assert report["metrics"][0]["value"] == 1.0
