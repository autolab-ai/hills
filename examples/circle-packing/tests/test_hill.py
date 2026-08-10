"""Checks on the hill itself, run by `hills check`."""

import json
from pathlib import Path

import pytest

from hills import run_evaluator

HILL = Path(__file__).resolve().parents[1]
GRID = HILL / "examples" / "grid"


def write(tmp_path: Path, circles: list[dict]) -> Path:
    (tmp_path / "solution.json").write_text(json.dumps({"circles": circles}))
    return tmp_path


def test_grid_example_passes():
    result = run_evaluator(HILL, GRID)
    assert result["passed"]
    assert result["metrics"][0]["name"] == "sum_radii"
    assert result["metrics"][0]["value"] == pytest.approx(2.5414, abs=1e-9)


def test_primary_config_records_n_and_mode():
    primary = {
        entry["name"]: entry["value"]
        for entry in run_evaluator(HILL, GRID)["config"]
        if entry["primary"]
    }
    assert primary == {"n": 26, "mode": "validation"}
    final = {
        entry["name"]: entry["value"]
        for entry in run_evaluator(HILL, GRID, final=True)["config"]
        if entry["primary"]
    }
    assert final["mode"] == "test"


def test_overlap_is_rejected(tmp_path):
    circles = [{"x": 0.5, "y": 0.5, "r": 0.3}, {"x": 0.5, "y": 0.5, "r": 0.3}]
    result = run_evaluator(HILL, write(tmp_path, circles), n=2)
    assert not result["passed"]
    assert "overlap" in result["details"]["violations"][0]


def test_circle_outside_the_square_is_rejected(tmp_path):
    circles = [{"x": 0.95, "y": 0.5, "r": 0.2}]
    result = run_evaluator(HILL, write(tmp_path, circles), n=1)
    assert not result["passed"]
    assert "leaves the unit square" in result["details"]["violations"][0]


def test_touching_circles_are_legal(tmp_path):
    circles = [{"x": 0.25, "y": 0.5, "r": 0.25}, {"x": 0.75, "y": 0.5, "r": 0.25}]
    result = run_evaluator(HILL, write(tmp_path, circles), n=2)
    assert result["passed"]
    assert result["metrics"][0]["value"] == pytest.approx(0.5)


def test_wrong_count_is_rejected(tmp_path):
    result = run_evaluator(HILL, write(tmp_path, [{"x": 0.5, "y": 0.5, "r": 0.5}]))
    assert not result["passed"]
    assert "expected exactly 26" in result["details"]["violations"][0]


def test_missing_file_is_rejected(tmp_path):
    result = run_evaluator(HILL, tmp_path)
    assert not result["passed"]
    assert "solution.json" in result["details"]["error"]
