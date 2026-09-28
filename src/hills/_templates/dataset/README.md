# __NAME__

A hill with a dataset. The dataset lives under `data/` and is stored with
git-LFS: only small pointer files are committed to git, and the real bytes live
in AutoLab's object storage. When a climb runs, the tool downloads and verifies
the dataset before calling the evaluator, so `eval.py` can read `data/` directly.

## The task
Submit a `solution.json` with a `predictions` list. The evaluator scores the
fraction of predictions that match the dataset's targets within `tolerance`.

## Layout
- `eval.py` — the evaluator (climbers can read this).
- `data/` — the dataset (git-LFS).
- `private/` — held-out data the climber is asked not to read (git-LFS).
- `examples/baseline/` — a reference submission.

## Adding your own data
Drop files under `data/` (or add patterns to `.gitattributes`); anything matched
by an LFS pattern is uploaded to object storage on push, not committed to git.
