# circle-packing

The hello-world hill. It runs in under a second on any machine, has no private
data, and no dependencies beyond the standard library.

## Task

Place `n` circles inside the unit square `[0, 1] × [0, 1]` so that no two
circles overlap and every circle lies entirely inside the square. Maximize the
sum of the radii.

For `n = 26` the best packing currently known has a sum of radii of about
2.6358. The example submission shipped with this hill reaches 2.5414, so there
is real room to improve.

## Submission format

A submission is a **directory** containing one file:

```
solution.json
```

```json
{
  "circles": [
    {"x": 0.1, "y": 0.1, "r": 0.1},
    {"x": 0.3, "y": 0.1, "r": 0.1}
  ]
}
```

Exactly `n` circles. Coordinates are read as exact decimals, not floats, so
writing `0.1` means one tenth and not the nearest double. Write as many digits
as you need.

## Metric

| metric      | direction | meaning                      |
|-------------|-----------|------------------------------|
| `sum_radii` | max       | sum of all `r` in the packing |

A submission passes only if every constraint holds:

- `r > 0` for every circle
- containment: `r ≤ x ≤ 1 - r` and `r ≤ y ≤ 1 - r`
- non-overlap: `(xi - xj)² + (yi - yj)² ≥ (ri + rj)²` for every pair

All three are checked with exact rational arithmetic, allowing a slack of
`tolerance` (default `1e-9`) so that a solution produced by a floating-point
optimizer is not rejected for rounding. Touching circles are legal: equality
holds exactly.

Failed submissions get the first five violations back in `details.violations`,
with the pair indices and the size of the overlap.

## Parameters

| param       | default | meaning                                          |
|-------------|---------|--------------------------------------------------|
| `n`         | 26      | number of circles required; primary config entry |
| `tolerance` | 1e-9    | slack on the constraints                         |

```
hills eval ./my-packing -H circle-packing
hills eval ./my-packing -H circle-packing -p n=32
```

`n` is a **primary** config entry, so packings for different `n` rank in
separate groups and are never compared to each other.

## Test mode

`--final` sets `mode=test` in the config. This task has no hidden data, so the
score is identical; the flag exists here only to show where a hill with a
held-out split would use it.

## What the evaluator will not do

- It will not read a `sum_radii` your code computed. It sums the radii itself.
- It will not accept a packing that overlaps by less than the tolerance and
  calls it a rounding error: the tolerance is fixed and stated above.
- It will not score anything outside `hills eval`, and an edited report file
  fails `hills verify`.
