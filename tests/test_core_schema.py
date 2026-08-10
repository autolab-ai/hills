import pytest

from hills.core_schema import validate_core
from hills.errors import CoreSchemaError

PASSING = {
    "passed": True,
    "metrics": [{"name": "loss", "value": 1.5, "direction": "min"}],
}


def test_normalizes_optional_keys():
    result = validate_core(dict(PASSING))
    assert result["config"] == []
    assert result["details"] == {}


@pytest.mark.parametrize(
    "core, message",
    [
        ({"metrics": []}, "'passed' must be a boolean"),
        ({"passed": True, "metrics": []}, "at least one metric"),
        (
            {"passed": True, "metrics": [{"name": "a", "value": "x", "direction": "min"}]},
            "must be a number",
        ),
        (
            {"passed": True, "metrics": [{"name": "a", "value": 1, "direction": "down"}]},
            "'min' or 'max'",
        ),
        (
            {
                "passed": True,
                "metrics": [
                    {"name": "a", "value": 1, "direction": "min"},
                    {"name": "a", "value": 2, "direction": "min"},
                ],
            },
            "unique",
        ),
        ({**PASSING, "score": 3}, "unexpected keys"),
        ({**PASSING, "details": []}, "'details' must be an object"),
        (
            {**PASSING, "config": [{"name": "gpu", "value": 1, "primary": "yes"}]},
            "primary must be a boolean",
        ),
        (
            {**PASSING, "config": [{"name": "gpu", "value": {"a": 1}, "primary": True}]},
            "config\\[0\\].value must be",
        ),
    ],
)
def test_rejects(core, message):
    with pytest.raises(CoreSchemaError, match=message):
        validate_core(core)


def test_failing_result_may_have_no_metrics():
    assert validate_core({"passed": False})["metrics"] == []


def test_infinite_metric_is_rejected():
    with pytest.raises(CoreSchemaError, match="finite"):
        validate_core({"passed": True, "metrics": [{"name": "a", "value": float("inf"), "direction": "min"}]})
