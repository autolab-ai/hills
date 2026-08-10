"""Checks on the hill itself, run by `hills check`.

These run the real evaluator on a real training subprocess, with the time limit
turned down so the check stays fast.
"""

import textwrap
from pathlib import Path

import pytest

from hills import run_evaluator

HILL = Path(__file__).resolve().parents[1]
BASELINE = HILL / "examples" / "baseline"
TIME_LIMIT = 20

pytestmark = pytest.mark.skipif(
    not (HILL / "private" / "data" / "val.bin").is_file(),
    reason="run `uv run python prepare_data.py` first",
)


def submission(tmp_path: Path, body: str) -> Path:
    (tmp_path / "train.py").write_text(textwrap.dedent(body))
    return tmp_path


def test_baseline_trains_and_beats_uniform():
    result = run_evaluator(HILL, BASELINE, time_limit_s=TIME_LIMIT)
    assert result["passed"], result["details"]
    bpb = result["metrics"][0]
    assert bpb["name"] == "val_bpb" and bpb["direction"] == "min"
    assert 0.0 < bpb["value"] < 8.0, "a trained model must beat a uniform byte distribution"
    assert result["details"]["training"]["killed_at_limit"] is True


def test_primary_config_pins_hardware_budget_and_mode():
    primary = {
        entry["name"]
        for entry in run_evaluator(HILL, BASELINE, time_limit_s=TIME_LIMIT)["config"]
        if entry["primary"]
    }
    assert primary == {"gpu", "time_limit_s", "mode"}


def test_missing_train_py_is_rejected(tmp_path):
    result = run_evaluator(HILL, tmp_path, time_limit_s=TIME_LIMIT)
    assert not result["passed"]
    assert "train.py" in result["details"]["error"]


def test_missing_checkpoint_is_rejected(tmp_path):
    result = run_evaluator(
        HILL, submission(tmp_path, "print('trained, honest')\n"), time_limit_s=TIME_LIMIT
    )
    assert not result["passed"]
    assert "final.pt" in result["details"]["error"]
    assert "trained, honest" in result["details"]["train_log_tail"]


def test_checkpoint_that_is_not_torchscript_is_rejected(tmp_path):
    result = run_evaluator(
        HILL,
        submission(
            tmp_path,
            """
            import argparse
            parser = argparse.ArgumentParser()
            parser.add_argument("--data")
            parser.add_argument("--out")
            args = parser.parse_args()
            open(args.out + "/final.pt", "w").write("not a model")
            """,
        ),
        time_limit_s=TIME_LIMIT,
    )
    assert not result["passed"]
    assert "TorchScript" in result["details"]["error"]
