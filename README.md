<p align="center">
  <img src="https://raw.githubusercontent.com/QKayV/hills/main/docs/banner.png"
       alt="hills: agents can climb, evaluators can judge"
       width="900">
</p>

<p align="center">Local verification environments for AI research agents.</p>

When an agent runs research experiments autonomously, the same model writes the
solution, evaluates it, and reports the result. It grades its own homework, so
its numbers cannot be trusted. Hills separates the two roles.

A **hill** is a packaged evaluation task: a task description, an evaluator, and
data. The agent (the **climber**) develops however it likes, but an official
score comes only from `hills eval`, which runs the hill's evaluator in a
separate process against a frozen, committed version of the hill and returns a
signed report. The agent can query the verifier; it cannot modify it or grade
itself.

The mental model is git. A hill is a versioned directory, `hills commit` freezes
it, and every score is tied to the exact version that produced it.

## Install

The primary path installs the agent skill, which bootstraps the CLI on first use:

```
npx skills add autolab/hills
```

The reverse door, if you want the CLI first:

```
uv tool install hills
hills setup            # installs the skill into whichever agent harnesses you have
```

## The shape of it

```
hills new circle-packing -t circle-packing   # scaffold from the example
hills check circle-packing                   # manifest + evaluator contract + tests
hills commit circle-packing -m "initial"     # freeze it; prints the tree hash
hills eval ./my-packing -H circle-packing    # signed report on stdout
hills attempts circle-packing                # what has been tried against this version
```

A hill on disk:

```
.hills/circle-packing/
  hill.yaml        minimal manifest: watchdog, typed params, blob rules
  README.md        the contract, written for the climbing agent
  eval.py          THE entrypoint: def eval(submission: Path, **params) -> dict
  private/         evaluator-only content; never enters git
  examples/        minimal demonstration submissions
  tests/           checks on the hill itself, run by `hills check`
  .vc/             the hill's own git dir, named so it cannot collide with yours
```

`.hills/` is created with a `.gitignore` containing `*`, so it excludes itself
from your project's git the way `uv` excludes `.venv`. No file of yours is
edited and nothing is asked of you at setup.

## The evaluator contract

One fixed function, at the hill root, in `eval.py`:

```python
from pathlib import Path

def eval(submission: Path, *, final: bool = False, **params) -> dict:
    return {
        "passed": True,
        "metrics": [{"name": "val_bpb", "value": 1.043, "direction": "min"}],
        "config":  [{"name": "gpu", "value": "rtx4090-24gb", "primary": True},
                    {"name": "torch", "value": "2.9.1", "primary": False}],
        "details": {},
    }
```

A submission is a directory. That is the whole input contract: a codebase, model
weights, or a single JSON file are all just files in a directory.

The tool never imports `eval.py` in-process. It runs a shim as a subprocess in
the hill's own uv environment, so per-hill dependencies stay isolated, a
watchdog can kill a hung evaluation, and an evaluator crash cannot take down the
tool.

`config` entries describe the conditions of the measurement. Primary entries
define comparability: two reports are comparable only if their primary config
tuples match. Metrics are an ordered list with per-metric direction, and ranking
is lexicographic in that order. Any set of reports therefore sorts into ranked
groups with no configuration beyond the reports themselves.

## Identity and locks

A hill's identity is its **git tree hash**, not its commit hash. Tree hashes are
a pure function of content, so the same files give the same identity on any
machine. All state is keyed by tree hash: a new hill version starts a fresh
attempts history, because a changed evaluator is a new game.

Two lock files bind out-of-git content into that identity, and are regenerated
from disk at every commit:

- `private.lock`: every file under `private/`. The files never enter git. The
  tree hash *commits to* private content without *containing* it. Git has no
  per-path access control and its history is permanent, so anything ever
  committed is distributable forever; and leaked held-out data ends up in future
  training corpora, silently invalidating the hill.
- `blobs.lock`: large assets outside `private/`: anything matching a `track`
  pattern or over the size threshold.

There is no blob store, no symlink farm, no content-addressed cache. The lock
file is the tracking, and integrity is enforced at the two moments it matters:
at `commit` (locks regenerated from disk) and at `eval` (disk verified against
the locks at HEAD; a mismatch is a hard error naming the file).

## Reports

The dict your evaluator returns is the report **core**. The tool wraps it in an
envelope: hill name, tree hash, commit, submission hash, submission git lineage,
params, tool version and package hash, timestamp, and an HMAC signature over the
canonicalized report. The key lives at `~/.autolab/hills/key`, mode 0600,
deliberately outside any project directory an agent works in.

```
hills verify report.json
```

## Trust posture

This tool defends against **self-deception**: an agent loop accidentally or
opportunistically grading its own work, editing its own scores, or drifting its
own evaluation criteria.

It does not defend against a malicious human operator. Private files are
ordinary files, protected by convention and by the tool only handing their
location to the evaluator process. Signed reports are tamper-evident, not
tamper-proof.

The honest claim: **your agent cannot fake a hills report; you could, but then
you're only lying to yourself.** Disputed results are re-runnable, because
hills are inspectable and submissions are hashed, so verification is ultimately
by replay, not by trust in any single machine.

## Commands

```
hills new <name> [-t template]     scaffold a hill, init .vc, register it
hills check <name>                 manifest + evaluator contract + tests/
hills status <name>                changes since the last commit, including lock drift
hills commit <name> -m "..."       check, regenerate locks, commit, print the tree hash
hills log <name>                   version history, with eval counts per version
hills describe <name>              README + params + submission contract, as JSON
hills eval <dir> -H <name> [-p k=v] [--final] [--force | --current] [--queue]
hills attempts <name>              eval history for this version; flags a broken chain
hills verify <report.json>         check a report's signature
hills list                         registered hills
hills setup                        install the agent skill into detected harnesses
hills home                         where machine state lives
```

`hills eval` evaluates **HEAD, never the working tree**. A dirty hill is an
error: commit it, or `--force` to score the last committed version anyway, or
`--current` to test a draft evaluator against a real submission (unofficial,
`tree_hash: null`, logged separately).

## Repository layout

```
src/hills/          the library and CLI
skills/hills/       the agent skill, version-locked to the CLI
examples/           the example hills, also usable as `hills new -t <name>`
docs/SPEC.md        the design specification this implements
tests/              tests for the tool
```

## Machine state

```
~/.autolab/hills/
  registry.json                       name -> path, current tree hash
  key                                 the per-machine signing key (0600)
  state/<name>@<tree_hash>/attempts.jsonl   append-only, HMAC-chained
  runs/<name>/<timestamp>-<id>/       materialized hill, submission snapshot, logs, report
  envs/<name>/<tree_hash>/            the uv environment for that hill version
```

Hills are stateless: a hill emits signed reports and remembers nothing. Eval
history is tool state; the climbing agent keeps its own working notes.

## License

MIT. See [LICENSE](LICENSE).
