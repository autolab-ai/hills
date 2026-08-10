import pytest

from hills import manifest as manifest_mod
from hills.errors import ManifestError

MINIMAL = """
name: demo
version: 0.1.0
watchdog_timeout_s: 60
"""


def test_minimal_manifest():
    parsed = manifest_mod.loads(MINIMAL)
    assert parsed.name == "demo"
    assert parsed.params == {}
    assert parsed.blobs.threshold == 1024 * 1024
    assert parsed.exclusive is None


@pytest.mark.parametrize(
    "text, message",
    [
        ("name: Demo\nversion: 0.1.0\nwatchdog_timeout_s: 1", "name must be lowercase"),
        ("name: demo\nversion: 1\nwatchdog_timeout_s: 1", "version must look like"),
        ("name: demo\nversion: 0.1.0\nwatchdog_timeout_s: 0", "positive integer"),
        ("name: demo\nversion: 0.1.0\nwatchdog_timeout_s: 1\nnope: 1", "unknown keys"),
    ],
)
def test_rejects_bad_manifests(text, message):
    with pytest.raises(ManifestError, match=message):
        manifest_mod.loads(text)


def test_params_are_typed_and_bounded():
    parsed = manifest_mod.loads(
        MINIMAL + "params:\n  steps: {type: int, default: 10, min: 1, max: 100}\n"
    )
    assert parsed.resolve_params({}) == {"steps": 10}
    assert parsed.resolve_params({"steps": "42"}) == {"steps": 42}
    with pytest.raises(ManifestError, match="above max"):
        parsed.resolve_params({"steps": "1000"})
    with pytest.raises(ManifestError, match="expected int"):
        parsed.resolve_params({"steps": "nine"})
    with pytest.raises(ManifestError, match="unknown param"):
        parsed.resolve_params({"nope": "1"})


def test_reserved_param_names_are_refused():
    with pytest.raises(ManifestError, match="reserved"):
        manifest_mod.loads(MINIMAL + "params:\n  final: {type: bool, default: false}\n")


def test_declared_default_is_validated():
    with pytest.raises(ManifestError, match="below min"):
        manifest_mod.loads(MINIMAL + "params:\n  n: {type: int, default: 0, min: 1}\n")


def test_choices_and_bools():
    parsed = manifest_mod.loads(
        MINIMAL
        + "params:\n"
        + "  mode: {type: str, default: fast, choices: [fast, slow]}\n"
        + "  strict: {type: bool, default: false}\n"
    )
    assert parsed.resolve_params({"mode": "slow", "strict": "yes"}) == {
        "mode": "slow",
        "strict": True,
    }
    with pytest.raises(ManifestError, match="not one of"):
        parsed.resolve_params({"mode": "medium"})


@pytest.mark.parametrize(
    "value, expected", [("10MB", 10 * 1024**2), ("512KB", 512 * 1024), (2048, 2048)]
)
def test_size_parsing(value, expected):
    assert manifest_mod.parse_size(value) == expected
