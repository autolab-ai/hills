"""What happens when the evaluator misbehaves. None of it may take down the tool."""

import json

import pytest

from hills import state
from hills.errors import CoreSchemaError, EvaluatorFailed
from hills.hill import Hill

pytestmark = pytest.mark.usefixtures("project")

HEADER = "from pathlib import Path\n\n\ndef eval(submission, *, final=False, **params):\n"


@pytest.fixture
def hill(project, cli):
    cli("new", "demo")
    return project / ".autolab" / "hills" / "demo"


@pytest.fixture
def submission(project):
    directory = project / "attempt"
    directory.mkdir()
    (directory / "solution.json").write_text('{"value": 3}')
    return directory


def freeze(cli, hill, body: str, *, watchdog: int | None = None) -> None:
    (hill / "eval.py").write_text(HEADER + body)
    if watchdog is not None:
        manifest = (hill / "hill.yaml").read_text()
        (hill / "hill.yaml").write_text(
            manifest.replace("watchdog_timeout_s: 600", f"watchdog_timeout_s: {watchdog}")
        )
    cli("commit", "demo", "-m", "test", "--no-tests")


def head(name: str = "demo") -> str:
    return Hill.resolve(name).vc.tree_hash()


def test_evaluator_exception_surfaces_the_traceback(cli, hill, submission):
    freeze(cli, hill, "    raise ZeroDivisionError('bad math in the evaluator')\n")
    with pytest.raises(EvaluatorFailed, match="ZeroDivisionError: bad math in the evaluator"):
        cli("eval", str(submission), "-H", "demo")


def test_evaluator_failure_is_recorded_as_an_attempt(cli, hill, submission):
    freeze(cli, hill, "    raise RuntimeError('nope')\n")
    with pytest.raises(EvaluatorFailed):
        cli("eval", str(submission), "-H", "demo")
    attempts = state.read("demo", head())
    assert len(attempts) == 1
    assert attempts[0]["passed"] is False
    assert "RuntimeError" in attempts[0]["error"]
    assert attempts[0]["signature"] is None


def test_a_return_value_off_contract_is_rejected(cli, hill, submission):
    freeze(cli, hill, "    return {'passed': True, 'metrics': []}\n")
    with pytest.raises(CoreSchemaError, match="at least one metric"):
        cli("eval", str(submission), "-H", "demo")


def test_a_non_dict_return_is_rejected(cli, hill, submission):
    freeze(cli, hill, "    return 0.5\n")
    with pytest.raises(CoreSchemaError, match="must be an object"):
        cli("eval", str(submission), "-H", "demo")


def test_exit_without_returning_is_reported(cli, hill, submission):
    freeze(cli, hill, "    import os\n    os._exit(3)\n")
    with pytest.raises(EvaluatorFailed, match="exited with code 3 without writing a result"):
        cli("eval", str(submission), "-H", "demo")


def test_watchdog_kills_a_hung_evaluator(cli, hill, submission):
    freeze(cli, hill, "    import time\n    time.sleep(600)\n", watchdog=5)
    with pytest.raises(EvaluatorFailed, match="watchdog killed the evaluator after 5s"):
        cli("eval", str(submission), "-H", "demo")


def test_watchdog_kills_the_whole_process_group(cli, hill, submission):
    """A child the evaluator spawned must not outlive the kill."""
    freeze(
        cli,
        hill,
        "    import subprocess, sys, time\n"
        "    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])\n"
        "    Path(params['marker']).write_text(str(child.pid))\n"
        "    time.sleep(600)\n",
        watchdog=5,
    )
    marker = hill.parent / "child.pid"
    (hill / "hill.yaml").write_text(
        (hill / "hill.yaml").read_text().replace(
            "  tolerance:", f"  marker: {{type: str, default: '{marker}'}}\n  tolerance:"
        )
    )
    cli("commit", "demo", "-m", "marker", "--no-tests")

    with pytest.raises(EvaluatorFailed, match="watchdog"):
        cli("eval", str(submission), "-H", "demo")

    import os
    import time

    pid = int(marker.read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    pytest.fail(f"the evaluator's child process {pid} survived the watchdog")


def test_the_evaluator_sees_private_content_that_git_never_stored(cli, hill, submission, capsys):
    (hill / "private").mkdir(exist_ok=True)
    (hill / "private" / "answer.txt").write_text("42")
    freeze(
        cli,
        hill,
        "    secret = (Path(__file__).parent / 'private' / 'answer.txt').read_text()\n"
        "    return {'passed': True, 'metrics': "
        "[{'name': 'answer', 'value': float(secret), 'direction': 'max'}]}\n",
    )
    cli("eval", str(submission), "-H", "demo")
    assert json.loads(capsys.readouterr().out)["metrics"][0]["value"] == 42.0

    tracked = Hill.resolve("demo").vc.ls_tree()
    assert "private/answer.txt" not in tracked
    assert "private.lock" in tracked
    locked = json.loads((hill / "private.lock").read_text())
    assert locked["entries"][0]["path"] == "private/answer.txt"


def test_changing_private_content_changes_the_hill_identity(cli, hill, submission):
    (hill / "private").mkdir(exist_ok=True)
    (hill / "private" / "answer.txt").write_text("42")
    freeze(cli, hill, "    return {'passed': False}\n")
    first = head()

    (hill / "private" / "answer.txt").write_text("43")
    cli("commit", "demo", "-m", "new split", "--no-tests")
    assert head() != first, "the tree hash commits to private content through the lock"
