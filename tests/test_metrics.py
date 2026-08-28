"""Spec v2: hill.yaml declares the metrics, reports must lead with them."""

import json

import pytest

from hills import manifest as manifest_mod, state
from hills.core_schema import metrics_prefix_violation
from hills.errors import EvaluatorFailed, ManifestError
from hills.hill import Hill

pytestmark = pytest.mark.usefixtures("project")

V2 = """
spec_version: 2
name: demo
version: 0.1.0
watchdog_timeout_s: 60
metrics:
  - {name: score, direction: max}
  - {name: runtime_s, direction: min}
"""


# -- manifest ----------------------------------------------------------------


def test_declared_metrics_parse_in_order():
    parsed = manifest_mod.loads(V2)
    assert [(m.name, m.direction) for m in parsed.metrics] == [
        ("score", "max"),
        ("runtime_s", "min"),
    ]
    assert parsed.as_json()["metrics"] == [
        {"name": "score", "direction": "max"},
        {"name": "runtime_s", "direction": "min"},
    ]


def test_v1_manifest_has_no_metrics_key_in_json():
    v1 = V2.replace("spec_version: 2", "spec_version: 1").split("metrics:")[0]
    assert "metrics" not in manifest_mod.loads(v1).as_json()


@pytest.mark.parametrize(
    "text, message",
    [
        (V2.split("metrics:")[0], "requires a metrics key"),
        (V2.replace("- {name: runtime_s, direction: min}", "- {name: score, direction: min}"),
         "unique"),
        (V2.replace("direction: max", "direction: up"), "must be 'max' or 'min'"),
        (V2.replace("name: score, ", ""), "exactly"),
        (V2.replace("spec_version: 2", "spec_version: 1"), "unknown keys"),
    ],
)
def test_rejects_bad_declarations(text, message):
    with pytest.raises(ManifestError, match=message):
        manifest_mod.loads(text)


# -- the shared prefix rule --------------------------------------------------

DECLARED = [{"name": "score", "direction": "max"}, {"name": "runtime_s", "direction": "min"}]


def metric(name, direction="max", value=1.0):
    return {"name": name, "value": value, "direction": direction}


def test_prefix_rule_accepts_extras_after_the_declared_metrics():
    reported = [metric("score"), metric("runtime_s", "min"), metric("loss", "min")]
    assert metrics_prefix_violation(DECLARED, reported) is None


@pytest.mark.parametrize(
    "reported, fragment",
    [
        ([metric("score")], "missing declared metric 'runtime_s'"),
        ([metric("runtime_s", "min"), metric("score")], "declares 'score' in this position"),
        ([metric("score", "min"), metric("runtime_s", "min")], "declares 'max'"),
        ([metric("loss", "min"), metric("score"), metric("runtime_s", "min")],
         "declares 'score' in this position"),
    ],
)
def test_prefix_rule_names_the_first_divergence(reported, fragment):
    assert fragment in metrics_prefix_violation(DECLARED, reported)


# -- enforcement through the CLI ---------------------------------------------


@pytest.fixture
def hill(project, cli):
    """A default-template hill (declares score/max) with a trivial evaluator."""
    cli("new", "demo")
    return project / ".autolab" / "hills" / "demo"


@pytest.fixture
def submission(project):
    directory = project / "attempt"
    directory.mkdir()
    (directory / "solution.json").write_text('{"value": 3}')
    return directory


def freeze_with_metrics(cli, hill, metrics_expr: str) -> None:
    (hill / "eval.py").write_text(
        "def eval(submission, *, final=False, **params):\n"
        f"    return {{'passed': True, 'metrics': {metrics_expr}}}\n"
    )
    cli("commit", "demo", "-m", "test", "--no-tests")


def test_eval_of_a_violating_report_is_a_hard_error_and_writes_no_report(
    cli, hill, submission
):
    freeze_with_metrics(cli, hill, "[{'name': 'accuracy', 'value': 1.0, 'direction': 'max'}]")
    with pytest.raises(EvaluatorFailed, match="declared in hill.yaml.*'accuracy'"):
        cli("eval", str(submission), "-H", "demo")
    attempts = state.read("demo", Hill.resolve("demo").vc.tree_hash())
    assert len(attempts) == 1
    assert attempts[0]["signature"] is None
    assert "declared in hill.yaml" in attempts[0]["error"]


def test_eval_allows_extra_metrics_after_the_declared_ones(cli, hill, submission, capsys):
    freeze_with_metrics(
        cli,
        hill,
        "[{'name': 'score', 'value': 1.0, 'direction': 'max'},"
        " {'name': 'runtime_s', 'value': 2.5, 'direction': 'min'}]",
    )
    assert cli("eval", str(submission), "-H", "demo") == 0
    report = json.loads(capsys.readouterr().out)
    assert [m["name"] for m in report["metrics"]] == ["score", "runtime_s"]


def test_check_fails_when_the_example_report_diverges(cli, hill, capsys):
    """The hill's tests run the example through run_evaluator, which enforces
    the declaration `hills check` exports."""
    manifest = hill / "hill.yaml"
    manifest.write_text(
        manifest.read_text().replace(
            "- {name: score, direction: max}", "- {name: quality, direction: max}"
        )
    )
    assert cli("check", "demo") == 1
    output = capsys.readouterr().err
    assert "declared in hill.yaml" in output
    assert "'quality'" in output


def test_check_fails_on_a_wrong_declared_direction(cli, hill, capsys):
    manifest = hill / "hill.yaml"
    manifest.write_text(
        manifest.read_text().replace(
            "- {name: score, direction: max}", "- {name: score, direction: min}"
        )
    )
    assert cli("check", "demo") == 1
    assert "declares 'min'" in capsys.readouterr().err


def test_check_passes_when_the_report_matches(cli, hill):
    assert cli("check", "demo") == 0
