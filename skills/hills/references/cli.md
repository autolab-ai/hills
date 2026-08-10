# CLI reference and troubleshooting

Every command addresses a hill by name through the global registry, so it works
from any directory. `hills eval` prints the report as JSON on stdout and a human
summary on stderr, so redirecting stdout gives you the report and leaves the
summary on your terminal.

## Commands

| command | what it does |
|---|---|
| `hills new <name> [-t <template>]` | scaffold `.hills/<name>/`, init `.vc`, register it |
| `hills check <name>` | manifest, evaluator contract, `tests/` |
| `hills status <name>` | changes since the last commit, including lock drift git cannot see |
| `hills commit <name> -m "..."` | check, regenerate locks, commit, print the tree hash |
| `hills log <name>` | version history, with how many evals each version has |
| `hills describe <name>` | README, params, file list, tree hash, as JSON |
| `hills eval <dir> -H <name>` | score a submission directory |
| `hills attempts <name>` | eval history for the current version |
| `hills verify <report.json>` | check a report's signature |
| `hills list` | registered hills |
| `hills setup` | install this skill into detected harnesses |
| `hills home` | where machine state lives |

`hills eval` flags: `-p key=value` (repeatable), `--final`, `--force`,
`--current`, `--queue`, `-v` to stream evaluator output, `-o path` to also write
the report to a file.

## Errors you will actually hit

**`hill <name> has uncommitted changes`**
`hills eval` evaluates the committed version, never the working tree. Either the
hill was edited, or a file under `private/` or a lock-tracked blob changed.
`hills status <name>` shows which. Options: the user commits, `--force` to score
the last committed version anyway, or `--current` to evaluate the working tree
(unofficial: `tree_hash: null`, logged separately). If you are climbing, do not
pick any of these yourself; tell the user the hill is dirty.

**`<path> has changed since the last commit`**
A private file or lock-tracked blob no longer matches `private.lock` or
`blobs.lock` at HEAD. This is a hard error by design: the data the hill was
frozen with is not the data on disk. Restore the file or re-commit the hill.

**`hill <name> has no commits yet`**
The hill was scaffolded but never frozen. A human runs `hills commit`.

**`device gpu:0 is busy with another official eval`**
Another official eval holds the device. Wait, or re-run with `--queue`.

**`watchdog killed the evaluator after Ns`**
The evaluator hung. Its combined output is in the run directory named in the
message. This is a bug in the hill, not in your submission.

**`the evaluator raised: ...`**
A traceback from inside `eval.py`. If it names your submission (missing file,
wrong shape), fix the submission. If it is inside the evaluator's own logic,
report it to the user.

**`signature INVALID`**
The report was edited, or it was produced on a different machine. Signing keys
are per-machine; a report from someone else's laptop will not verify on yours,
which is expected. Re-run the evaluation instead of arguing about the file.

## Where things live

```
.hills/<name>/                              the hill, inside the user's project
~/.autolab/hills/registry.json              name -> path, current tree hash
~/.autolab/hills/key                        per-machine signing key, mode 0600
~/.autolab/hills/state/<name>@<tree>/attempts.jsonl
~/.autolab/hills/runs/<name>/<stamp>-<id>/  materialized hill, submission snapshot, logs, report
```

State is keyed by tree hash. A new hill version starts a fresh attempts history,
because a changed evaluator is a new game.

## Reading a report

```json
{
  "hill": "nanogpt-10min",
  "tree_hash": "…", "commit": "…",
  "submission_hash": "sha256:…", "submission_git": "muon-lr@c41aa2",
  "passed": true,
  "metrics": [{"name": "val_bpb", "value": 1.043, "direction": "min"}],
  "config":  [{"name": "gpu", "value": "rtx4090-24gb", "primary": true}],
  "details": {…},
  "params": {"time_limit_s": 600},
  "final": false, "official": true, "official_reason": null,
  "tool": {"version": "0.1.0", "sha256": "…"},
  "timestamp": "…", "signature": "hmac-sha256:…", "report_version": 1
}
```

Two reports are comparable only if their primary `config` entries match and
`final` matches. Within a group, ranking is lexicographic over `metrics` in the
order the evaluator listed them, honoring each metric's direction. Only
`passed: true` reports rank.
