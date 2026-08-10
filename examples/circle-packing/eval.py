"""Evaluator for circle-packing.

Every check is exact: coordinates are parsed as fractions, so a solution that
sits exactly on a constraint is accepted and a solution that violates one by
1e-18 is not. `tolerance` is the only slack, and it is applied exactly too.

There is no private/ here. Nothing in this file reveals an answer -- the task is
an open optimization problem, and knowing how it is scored is the point.
"""

import json
from fractions import Fraction
from pathlib import Path

MAX_VIOLATIONS_REPORTED = 5


def _load(submission: Path):
    path = submission / "solution.json"
    if not path.is_file():
        raise ValueError("submission must contain solution.json")
    # Parsing numbers as Fractions keeps every later comparison exact.
    data = json.loads(path.read_text(), parse_float=Fraction, parse_int=Fraction)
    if not isinstance(data, dict) or "circles" not in data:
        raise ValueError('solution.json must be an object with a "circles" list')
    circles = data["circles"]
    if not isinstance(circles, list):
        raise ValueError('"circles" must be a list')

    parsed = []
    for index, circle in enumerate(circles):
        if not isinstance(circle, dict) or not {"x", "y", "r"} <= set(circle):
            raise ValueError(f"circles[{index}] must be an object with x, y and r")
        values = [circle["x"], circle["y"], circle["r"]]
        if not all(isinstance(value, Fraction) for value in values):
            raise ValueError(f"circles[{index}] has a non-numeric coordinate")
        parsed.append(tuple(values))
    return parsed


def _violations(circles, tol: Fraction, n: int):
    problems = []
    if len(circles) != n:
        problems.append(f"expected exactly {n} circles, got {len(circles)}")
        return problems

    one = Fraction(1)
    for index, (x, y, r) in enumerate(circles):
        if r <= 0:
            problems.append(f"circles[{index}] has radius {float(r):.6g}; radii must be positive")
            continue
        for axis, value in (("x", x), ("y", y)):
            if value - r < -tol or value + r > one + tol:
                problems.append(
                    f"circles[{index}] leaves the unit square on {axis}: "
                    f"{axis}={float(value):.6g}, r={float(r):.6g}"
                )

    for i in range(len(circles)):
        xi, yi, ri = circles[i]
        for j in range(i + 1, len(circles)):
            xj, yj, rj = circles[j]
            gap = (xi - xj) ** 2 + (yi - yj) ** 2 - (ri + rj) ** 2
            if gap < -tol:
                overlap = float(ri + rj) - float((xi - xj) ** 2 + (yi - yj) ** 2) ** 0.5
                problems.append(
                    f"circles[{i}] and circles[{j}] overlap by {overlap:.3e}"
                )
    return problems


def eval(submission: Path, *, final: bool = False, n: int = 26, tolerance: float = 1e-9) -> dict:
    tol = Fraction(tolerance).limit_denominator(10**15)

    try:
        circles = _load(submission)
    except (ValueError, json.JSONDecodeError) as error:
        return {
            "passed": False,
            "metrics": [],
            "config": _config(n, tolerance, final),
            "details": {"error": str(error)},
        }

    problems = _violations(circles, tol, n)
    if problems:
        return {
            "passed": False,
            "metrics": [],
            "config": _config(n, tolerance, final),
            "details": {
                "error": f"{len(problems)} constraint violation(s)",
                "violations": problems[:MAX_VIOLATIONS_REPORTED],
            },
        }

    total = sum((circle[2] for circle in circles), Fraction(0))
    return {
        "passed": True,
        "metrics": [{"name": "sum_radii", "value": float(total), "direction": "max"}],
        "config": _config(n, tolerance, final),
        "details": {
            "min_radius": float(min(circle[2] for circle in circles)),
            "max_radius": float(max(circle[2] for circle in circles)),
        },
    }


def _config(n: int, tolerance: float, final: bool) -> list[dict]:
    return [
        {"name": "n", "value": n, "primary": True},
        {"name": "mode", "value": "test" if final else "validation", "primary": True},
        {"name": "tolerance", "value": tolerance, "primary": False},
    ]
