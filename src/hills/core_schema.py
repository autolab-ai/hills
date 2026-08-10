"""The evaluator contract: what eval() is allowed to return.

Kept dependency-free so it can be imported inside a hill's own environment by
the test SDK.
"""

from hills.errors import CoreSchemaError

DIRECTIONS = ("min", "max")
SCALARS = (str, int, float, bool)


def _require_mapping(value, where: str) -> dict:
    if not isinstance(value, dict):
        raise CoreSchemaError(f"{where} must be an object, got {type(value).__name__}")
    return value


def _check_metric(entry, index: int) -> dict:
    entry = _require_mapping(entry, f"metrics[{index}]")
    name = entry.get("name")
    if not isinstance(name, str) or not name:
        raise CoreSchemaError(f"metrics[{index}].name must be a non-empty string")
    value = entry.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CoreSchemaError(f"metrics[{index}].value must be a number, got {value!r}")
    if value != value or value in (float("inf"), float("-inf")):
        raise CoreSchemaError(f"metrics[{index}].value must be finite, got {value!r}")
    direction = entry.get("direction")
    if direction not in DIRECTIONS:
        raise CoreSchemaError(
            f"metrics[{index}].direction must be 'min' or 'max', got {direction!r}"
        )
    return {"name": name, "value": value, "direction": direction}


def _check_config(entry, index: int) -> dict:
    entry = _require_mapping(entry, f"config[{index}]")
    name = entry.get("name")
    if not isinstance(name, str) or not name:
        raise CoreSchemaError(f"config[{index}].name must be a non-empty string")
    value = entry.get("value")
    if value is not None and not isinstance(value, SCALARS):
        raise CoreSchemaError(
            f"config[{index}].value must be a string, number, boolean or null, got {value!r}"
        )
    primary = entry.get("primary", False)
    if not isinstance(primary, bool):
        raise CoreSchemaError(f"config[{index}].primary must be a boolean, got {primary!r}")
    return {"name": name, "value": value, "primary": primary}


def validate_core(result) -> dict:
    """Validate and normalize the dict returned by a hill's eval()."""
    result = _require_mapping(result, "eval() return value")

    unknown = set(result) - {"passed", "metrics", "config", "details"}
    if unknown:
        raise CoreSchemaError(
            "eval() returned unexpected keys: "
            + ", ".join(sorted(unknown))
            + " (allowed: passed, metrics, config, details)"
        )

    passed = result.get("passed")
    if not isinstance(passed, bool):
        raise CoreSchemaError(f"'passed' must be a boolean, got {passed!r}")

    raw_metrics = result.get("metrics", [])
    if not isinstance(raw_metrics, list):
        raise CoreSchemaError("'metrics' must be a list")
    metrics = [_check_metric(entry, i) for i, entry in enumerate(raw_metrics)]
    names = [metric["name"] for metric in metrics]
    if len(set(names)) != len(names):
        raise CoreSchemaError("metric names must be unique")
    if passed and not metrics:
        raise CoreSchemaError("a passing result must report at least one metric")

    raw_config = result.get("config", [])
    if not isinstance(raw_config, list):
        raise CoreSchemaError("'config' must be a list")
    config = [_check_config(entry, i) for i, entry in enumerate(raw_config)]
    config_names = [entry["name"] for entry in config]
    if len(set(config_names)) != len(config_names):
        raise CoreSchemaError("config names must be unique")

    details = result.get("details", {})
    if not isinstance(details, dict):
        raise CoreSchemaError("'details' must be an object")

    return {"passed": passed, "metrics": metrics, "config": config, "details": details}
