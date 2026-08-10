import json

import pytest

from hills import report as report_mod
from hills.errors import HillsError


def make(metrics, config=(), final=False, passed=True):
    return {
        "passed": passed,
        "metrics": [
            {"name": name, "value": value, "direction": direction}
            for name, value, direction in metrics
        ],
        "config": [
            {"name": name, "value": value, "primary": primary}
            for name, value, primary in config
        ],
        "final": final,
    }


def build(**overrides):
    payload = {
        "hill_name": "demo",
        "tree_hash": "a" * 40,
        "commit": "b" * 40,
        "submission_hash": "sha256:" + "c" * 64,
        "submission_git_label": "main@abc1234",
        "core": {
            "passed": True,
            "metrics": [{"name": "loss", "value": 1.5, "direction": "min"}],
            "config": [],
            "details": {},
        },
        "params": {"steps": 10},
        "final": False,
        "official": True,
        "official_reason": None,
        "tool_version": "0.1.0",
    }
    payload.update(overrides)
    return report_mod.build(**payload)


def test_signature_round_trips():
    report = build()
    assert report_mod.verify(report)


def test_editing_any_field_invalidates_the_signature():
    report = build()
    report["metrics"][0]["value"] = 0.1
    assert not report_mod.verify(report)


def test_unsigned_report_is_invalid():
    report = build()
    del report["signature"]
    assert not report_mod.verify(report)


def test_key_is_created_private():
    from hills import paths

    report_mod.machine_key()
    assert paths.key_path().stat().st_mode & 0o777 == 0o600


def test_ranking_is_lexicographic_in_metric_order():
    reports = [
        make([("a", 2.0, "min"), ("b", 9.0, "max")]),
        make([("a", 1.0, "min"), ("b", 0.0, "max")]),
        make([("a", 1.0, "min"), ("b", 5.0, "max")]),
    ]
    ranked = report_mod.rank(reports)
    assert len(ranked) == 1
    best = next(iter(ranked.values()))
    assert [r["metrics"][0]["value"] for r in best] == [1.0, 1.0, 2.0]
    assert best[0]["metrics"][1]["value"] == 5.0


def test_only_matching_primary_config_ranks_together():
    reports = [
        make([("bpb", 1.0, "min")], config=[("gpu", "h100", True), ("torch", "2.9", False)]),
        make([("bpb", 0.5, "min")], config=[("gpu", "a100", True)]),
    ]
    assert len(report_mod.rank(reports)) == 2


def test_test_mode_never_ranks_against_validation():
    reports = [make([("bpb", 1.0, "min")]), make([("bpb", 0.9, "min")], final=True)]
    assert len(report_mod.rank(reports)) == 2


def test_failed_reports_do_not_rank():
    assert report_mod.rank([make([("bpb", 0.1, "min")], passed=False)]) == {}


def test_missing_report_file(tmp_path):
    with pytest.raises(HillsError, match="no report at"):
        report_mod.read(tmp_path / "nope.json")


def test_submission_git_label(project):
    (project / "a.txt").write_text("x")
    import subprocess

    subprocess.run(["git", "add", "-A"], cwd=project, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "one"],
        cwd=project,
        check=True,
    )
    label = report_mod.submission_git(project)
    assert label and "@" in label and not label.endswith("+dirty")

    (project / "a.txt").write_text("y")
    assert report_mod.submission_git(project).endswith("+dirty")


def test_no_git_means_no_label(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert report_mod.submission_git(plain) is None


def test_canonical_form_is_stable():
    from hills.canonical import canonical_bytes

    assert canonical_bytes({"b": 1, "a": [2, 3]}) == b'{"a":[2,3],"b":1}'
    assert json.loads(canonical_bytes({"a": 1})) == {"a": 1}
