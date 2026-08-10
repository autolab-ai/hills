"""The whole cycle, through the CLI, on the circle-packing example."""

import json
import subprocess
from pathlib import Path

import pytest

from hills import registry, state
from hills.errors import DirtyHill, HillsError, HillNotFound
from hills.hill import Hill

pytestmark = pytest.mark.usefixtures("project")


@pytest.fixture
def packing(project, cli):
    cli("new", "circle-packing", "-t", "circle-packing")
    return project / ".autolab" / "hills" / "circle-packing"


@pytest.fixture
def submission(project, packing):
    directory = project / "attempt"
    directory.mkdir()
    (directory / "solution.json").write_text(
        (packing / "examples" / "grid" / "solution.json").read_text()
    )
    return directory


def read_report(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


# -- scaffolding -------------------------------------------------------------


def test_new_hill_is_self_ignoring(project, packing):
    assert (project / ".autolab" / ".gitignore").read_text().splitlines()[-1] == "*"
    assert subprocess.run(
        ["git", "status", "--porcelain"], cwd=project, capture_output=True, text=True
    ).stdout.strip() == ""


def test_new_hill_is_registered_and_versioned(packing):
    assert (packing / ".vc").is_dir()
    assert not (packing / ".git").exists()
    assert registry.resolve("circle-packing") == packing


def test_new_refuses_to_overwrite(cli, packing):
    with pytest.raises(HillsError, match="already exists"):
        cli("new", "circle-packing", "-t", "circle-packing")


def test_unknown_hill_names_the_alternatives(packing):
    with pytest.raises(HillNotFound, match="Registered hills: circle-packing"):
        Hill.resolve("nope")


# -- check and commit --------------------------------------------------------


def test_check_passes_on_the_example(cli, packing):
    assert cli("check", "circle-packing") == 0


def test_eval_before_commit_is_refused(cli, packing, submission):
    with pytest.raises(HillsError, match="no commits yet"):
        cli("eval", str(submission), "-H", "circle-packing")


def test_commit_gate_refuses_a_broken_evaluator(cli, packing):
    (packing / "eval.py").write_text("def eval(wrong_name):\n    return {}\n")
    with pytest.raises(HillsError, match="check failed"):
        cli("commit", "circle-packing", "-m", "broken")
    assert Hill.resolve("circle-packing").vc.has_commits is False


def test_commit_records_the_tree_hash(cli, packing):
    assert cli("commit", "circle-packing", "-m", "initial") == 0
    hill = Hill.resolve("circle-packing")
    assert registry.entries()["circle-packing"]["tree_hash"] == hill.vc.tree_hash()
    assert (packing / "private.lock").is_file()
    assert (packing / "blobs.lock").is_file()


def test_committing_twice_without_changes_is_refused(cli, packing):
    cli("commit", "circle-packing", "-m", "initial")
    with pytest.raises(HillsError, match="nothing to commit"):
        cli("commit", "circle-packing", "-m", "again")


# -- eval --------------------------------------------------------------------


@pytest.fixture
def committed(cli, packing):
    cli("commit", "circle-packing", "-m", "initial")
    return packing


def test_eval_produces_a_signed_report(cli, committed, submission, capsys):
    assert cli("eval", str(submission), "-H", "circle-packing") == 0
    report = read_report(capsys)
    assert report["passed"]
    assert report["metrics"][0]["value"] == pytest.approx(2.5414)
    assert report["tree_hash"] == Hill.resolve("circle-packing").vc.tree_hash()
    assert report["official"] is True
    assert report["tool"]["version"] and report["tool"]["sha256"]

    from hills import report as report_mod

    assert report_mod.verify(report)


def test_params_reach_the_evaluator(cli, committed, submission, capsys):
    cli("eval", str(submission), "-H", "circle-packing", "-p", "n=26")
    assert read_report(capsys)["params"]["n"] == 26

    with pytest.raises(HillsError, match="unknown param"):
        cli("eval", str(submission), "-H", "circle-packing", "-p", "nope=1")


def test_wrong_count_fails_the_submission_without_erroring(cli, committed, submission, capsys):
    (submission / "solution.json").write_text('{"circles": []}')
    assert cli("eval", str(submission), "-H", "circle-packing") == 0
    report = read_report(capsys)
    assert report["passed"] is False
    assert "expected exactly 26" in report["details"]["violations"][0]


def test_final_mode_is_recorded(cli, committed, submission, capsys):
    cli("eval", str(submission), "-H", "circle-packing", "--final")
    report = read_report(capsys)
    assert report["final"] is True
    assert {"name": "mode", "value": "test", "primary": True} in report["config"]


def test_dirty_hill_blocks_eval(cli, committed, submission):
    (committed / "README.md").write_text("changed" * 20)
    with pytest.raises(DirtyHill, match="uncommitted changes"):
        cli("eval", str(submission), "-H", "circle-packing")


def test_force_evaluates_head(cli, committed, submission, capsys):
    head = Hill.resolve("circle-packing").vc.tree_hash()
    (committed / "README.md").write_text("changed" * 20)
    cli("eval", str(submission), "-H", "circle-packing", "--force")
    report = read_report(capsys)
    assert report["tree_hash"] == head
    assert report["official"] is True


def test_current_is_unofficial_and_logged_apart(cli, committed, submission, capsys):
    (committed / "README.md").write_text("changed" * 20)
    cli("eval", str(submission), "-H", "circle-packing", "--current")
    report = read_report(capsys)
    assert report["tree_hash"] is None
    assert report["official"] is False
    assert report["official_reason"] == "dirty-tree"

    head = Hill.resolve("circle-packing").vc.tree_hash()
    assert state.read("circle-packing", head) == []
    assert len(state.read("circle-packing", None)) == 1


def test_the_working_tree_is_never_evaluated_by_default(cli, committed, submission, capsys):
    (committed / "eval.py").write_text(
        "def eval(submission, *, final=False, n=26, tolerance=1e-9):\n"
        "    return {'passed': True, 'metrics': "
        "[{'name': 'sum_radii', 'value': 999.0, 'direction': 'max'}]}\n"
    )
    cli("eval", str(submission), "-H", "circle-packing", "--force")
    assert read_report(capsys)["metrics"][0]["value"] == pytest.approx(2.5414)


def test_submission_is_snapshotted_not_referenced(cli, committed, submission, capsys):
    cli("eval", str(submission), "-H", "circle-packing")
    report = read_report(capsys)
    run_dir = state.read("circle-packing", report["tree_hash"])[0]["run_dir"]
    assert (Path(run_dir) / "submission" / "solution.json").is_file()


# -- history -----------------------------------------------------------------


def test_attempts_are_recorded_per_version(cli, committed, submission, capsys):
    cli("eval", str(submission), "-H", "circle-packing")
    cli("eval", str(submission), "-H", "circle-packing")
    head = Hill.resolve("circle-packing").vc.tree_hash()
    assert len(state.read("circle-packing", head)) == 2

    (committed / "README.md").write_text("a new game" * 20)
    cli("commit", "circle-packing", "-m", "second")
    new_head = Hill.resolve("circle-packing").vc.tree_hash()
    assert new_head != head
    assert state.read("circle-packing", new_head) == []
    assert len(state.read("circle-packing", head)) == 2


def test_attempts_json_reports_chain_health(cli, committed, submission, capsys):
    cli("eval", str(submission), "-H", "circle-packing")
    capsys.readouterr()
    cli("attempts", "circle-packing", "--json")
    payload = json.loads(capsys.readouterr().out)
    assert payload["attempts"][0]["_chain_ok"] is True


def test_describe_is_json_with_the_readme_and_params(cli, committed, capsys):
    cli("describe", "circle-packing")
    described = json.loads(capsys.readouterr().out)
    assert described["hill"] == "circle-packing"
    assert "sum_radii" in described["readme"]
    assert described["params"]["n"]["default"] == 26
    assert "eval.py" in described["files"]
    assert described["tree_hash"] == Hill.resolve("circle-packing").vc.tree_hash()


def test_verify_command_exit_codes(cli, committed, submission, tmp_path, capsys):
    out = tmp_path / "report.json"
    cli("eval", str(submission), "-H", "circle-packing", "-o", str(out))
    capsys.readouterr()
    assert cli("verify", str(out)) == 0

    report = json.loads(out.read_text())
    report["passed"] = False
    out.write_text(json.dumps(report))
    assert cli("verify", str(out)) == 1


def test_list_shows_the_registry(cli, committed, capsys):
    cli("list", "--json")
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["name"] == "circle-packing"
    assert rows[0]["present"] is True


def test_examples_are_listed_with_summaries(cli, capsys):
    cli("examples", "--json")
    listed = {row["name"]: row["summary"] for row in json.loads(capsys.readouterr().out)}
    assert {"default", "circle-packing", "nanogpt-10min"} <= set(listed)
    assert all(summary for summary in listed.values()), "every example needs a summary"
    assert "hello-world" in listed["circle-packing"]


def test_new_from_a_named_example(cli, project):
    cli("new", "my-packing", "-t", "circle-packing")
    hill = Hill.resolve("my-packing")
    assert hill.manifest.name == "my-packing", "the manifest is renamed to the new hill"
    assert (hill.root / "examples" / "grid" / "solution.json").is_file()
    assert 'name = "my-packing"' in (hill.root / "pyproject.toml").read_text()


def test_home_directory_is_never_a_project(monkeypatch, tmp_path):
    """~/.autolab is the machine-state dir, so it must not read as a project marker."""
    from hills import paths
    from hills.errors import HillsError

    fake_home = tmp_path / "home"
    (fake_home / ".autolab" / "hills").mkdir(parents=True)
    monkeypatch.setenv("HILLS_HOME", str(fake_home / ".autolab" / "hills"))
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    with pytest.raises(HillsError, match="keeps its own state"):
        paths.project_hills(fake_home)

    # a plain directory under it still gets its own hills folder
    nested = fake_home / "work"
    nested.mkdir()
    assert paths.project_hills(nested) == nested / ".autolab" / "hills"


def test_forget_drops_a_registry_entry_without_touching_the_hill(cli, packing, capsys):
    assert "circle-packing" in registry.entries()
    cli("forget", "circle-packing")
    capsys.readouterr()
    assert "circle-packing" not in registry.entries()
    assert packing.is_dir(), "forget must not delete the hill"


def test_forget_refuses_an_unknown_name(cli, packing):
    with pytest.raises(HillsError, match="no hill named nope is registered"):
        cli("forget", "nope")
