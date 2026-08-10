# __NAME__

A blank hill to fill in: the manifest, the evaluator and this contract are
stubbed out and scored end to end, so `hills check` is green before you start.

<!-- This README is the contract. The climbing agent reads it through
     `hills describe __NAME__` and nothing else. Replace every section below. -->

## Task

Describe what the climber has to build, in the terms an ML engineer would use.
State the objective, what is fixed, and what is free to vary.

## Submission format

A submission is a **directory**. This hill expects it to contain:

```
solution.json      {"value": <number>}
```

The evaluator validates this on entry and reports what is wrong if it does not
match.

## Metric

| metric  | direction | meaning                       |
|---------|-----------|-------------------------------|
| `score` | max       | replace with the real metric  |

Reports rank lexicographically in the order the evaluator lists metrics, and
only within a matching set of primary config entries.

## Parameters

| param       | default | meaning                        |
|-------------|---------|--------------------------------|
| `tolerance` | 1e-6    | numeric slack in the checks    |

Pass one with `hills eval <dir> -H __NAME__ -p tolerance=1e-9`.

## Test mode

`hills eval ... --final` asks the evaluator to score against the held-out test
split instead of validation. Use it for the final claim, not for iteration.

## What the evaluator will not do

- It will not score anything except through `hills eval`.
- It will not read a metric your code computed. It computes the metric itself.
- Editing a report file invalidates its signature; `hills verify` catches it.
