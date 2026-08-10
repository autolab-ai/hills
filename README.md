<h1 align="center">hills</h1>

<p align="center"><strong>Local verification environments for AI research agents</strong></p>

<p align="center">
  <a href="#quickstart">Quickstart</a> ·
  <a href="#what-a-hill-is">What a hill is</a> ·
  <a href="#how-it-stays-honest">How it stays honest</a> ·
  <a href="#reference">Reference</a> ·
  <a href="https://github.com/autolab-hq/hills/blob/main/docs/SPEC.md">Spec</a> ·
  <a href="https://github.com/autolab-hq/hills/blob/main/skills/hills/SKILL.md">Agent skill</a>
</p>

<p align="center">
  <img alt="MIT license" src="https://img.shields.io/badge/license-MIT-7fa846?style=flat-square&labelColor=1c1c1c">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11+-7fa846?style=flat-square&labelColor=1c1c1c">
</p>

> When an agent runs research experiments autonomously, the same model writes the
> solution, evaluates it, and reports the result. It grades its own homework, so
> its numbers cannot be trusted. **Hills separates the two roles.**

<p align="center">
  <img src="https://raw.githubusercontent.com/autolab-hq/hills/main/docs/banner.png"
       alt="hills: agents can climb, evaluators can judge"
       width="900">
</p>

A **hill** is a packaged evaluation task: a task description, an evaluator, and
data. The agent (the **climber**) develops however it likes, but an official
score comes only from `hills eval`, which runs the hill's evaluator in a separate
process against a frozen, committed version of the hill and returns a signed
report. The agent can query the verifier; it cannot modify it or grade itself.

The mental model is git. A hill is a versioned directory, `hills commit` freezes
it, and every score is tied to the exact version that produced it.

## Quickstart

Two minutes, no GPU, no network after install. We will create the hello-world
hill, freeze it, score a submission against it, and then show what happens when
someone edits the score.

**1. Install.**

```bash
uv tool install hills
```

If you want your coding agent to drive this instead, install the skill and it
bootstraps the CLI itself:

```bash
npx skills add autolab-hq/hills
```

**2. Create a hill.** `circle-packing` ships with the tool: place 26 circles in
the unit square without overlaps, maximize the sum of the radii.

```console
$ mkdir demo && cd demo && git init -q .
$ hills new circle-packing -t circle-packing
hills: created machine state at ~/.autolab/hills
created demo/.hills/circle-packing
  template   circle-packing
  version control  demo/.hills/circle-packing/.vc (empty; nothing committed yet)
```

Nothing was asked of you and no file of yours was edited. `.hills/` carries a
`.gitignore` containing `*`, so it excludes itself from your project's git the
way `uv` excludes `.venv`.

**3. Check it, then freeze it.**

```console
$ hills check circle-packing
  ok    manifest             circle-packing 0.1.0
  ok    layout               eval.py, README.md, pyproject.toml
  ok    dependencies         uv.lock is up to date
  ok    evaluator contract   eval(submission, final, n, tolerance) imports and binds
  ok    tests                7 passed in 1.27s

circle-packing: all checks passed

$ hills commit circle-packing -m "initial"
  private.lock  0 file(s), 0 bytes
  blobs.lock    0 file(s), 0 bytes

committed circle-packing 0.1.0
  tree hash  0a93cd12b4360ba5434b7524897c8d4ce4ba5c68
  commit     20c61d03ca7245791b756238d8a7fa7626b08199

Scores from here on are tied to this tree hash. A new commit starts a fresh history.
```

`commit` runs `check` as a gate, then regenerates the lock files from disk. The
**tree hash** is the hill's identity, and every score from here on is tied to it.

**4. Score a submission.** A submission is just a directory. The hill ships one:

```console
$ cp -r .hills/circle-packing/examples/grid ./my-packing
$ hills eval ./my-packing -H circle-packing -o report.json

circle-packing @ 0a93cd12b436
  submission   ./my-packing
  hash         sha256:b415d43098bf…
  params       n=26  tolerance=1e-09
  PASSED       sum_radii=2.5414 (max)
  config       n=26*  mode=validation*  tolerance=1e-09   (* = primary)
```

The full report goes to stdout as JSON; the summary above is stderr, so
`hills eval ... > report.json` does what you expect.

<details>
<summary>The report</summary>

```json
{
  "hill": "circle-packing",
  "tree_hash": "0a93cd12b4360ba5434b7524897c8d4ce4ba5c68",
  "commit": "20c61d03ca7245791b756238d8a7fa7626b08199",
  "submission_hash": "sha256:b415d43098bf9d11f8a0b910760d28ba13f68ca0ee54ba2288a085758ecebf08",
  "submission_git": null,
  "passed": true,
  "config": [
    {"name": "n",         "value": 26,           "primary": true},
    {"name": "mode",      "value": "validation", "primary": true},
    {"name": "tolerance", "value": 1e-09,        "primary": false}
  ],
  "metrics": [
    {"name": "sum_radii", "value": 2.5414, "direction": "max"}
  ],
  "details": {"min_radius": 0.0414, "max_radius": 0.1},
  "params": {"n": 26, "tolerance": 1e-09},
  "final": false,
  "official": true,
  "official_reason": null,
  "tool": {"version": "0.1.0", "sha256": "463ea637f2f79fb9…"},
  "timestamp": "2026-08-10T02:11:05Z",
  "report_version": 1,
  "signature": "hmac-sha256:97553de336afdd8a3088b27392cfec0c5fee9d28c134f315294fe48599f5f3d2"
}
```

Had `./my-packing` been a git checkout, `submission_git` would read
`branch@short-sha`, tying the score to the code that produced it.

</details>

**5. Now try to improve the score by editing it.**

```console
$ hills verify report.json
signature valid: circle-packing @ 0a93cd12b436
  PASSED  sum_radii=2.5414 (max)
  signed 2026-08-10T02:11:05Z by hills 0.1.0

$ sed -i '' 's/2.5414/2.9/' report.json
$ hills verify report.json
signature INVALID: this report was edited, or it was signed on another machine.
```

That is the whole point of the tool, in one command.

**Where to go next.** `hills describe circle-packing` prints the contract your
agent would read. `hills new <name>` scaffolds a blank hill for your own task,
and `hills new <name> -t nanogpt-10min` starts from the flagship example: a
timed training run scored on a held-out split the climber never sees.

## What a hill is

A directory, versioned by its own embedded git repository:

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

`private/` is the only special directory. Everything else is climber-readable by
design, **including `eval.py`**: transparency about how you are judged is a
feature. The consequence is that anything answer-revealing has to live in
`private/`, not inline in the evaluator.

### The evaluator contract

One fixed function, at the hill root:

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
the hill's own uv environment, so per-hill dependencies stay isolated, a watchdog
can kill a hung evaluation, and an evaluator crash cannot take down the tool. For
timed tasks the evaluator launches the submitted code itself and enforces the
deadline, so the climber's code never runs the official clock.

`config` entries describe the conditions of the measurement. Primary entries
define comparability: two reports are comparable only if their primary config
tuples match. Metrics are an ordered list with per-metric direction, and ranking
is lexicographic in that order. Any set of reports therefore sorts into ranked
groups with no configuration beyond the reports themselves.

## How it stays honest

### Identity is content, not history

A hill's identity is its **git tree hash**, not its commit hash. Tree hashes are
a pure function of content, so the same files give the same identity on any
machine. All state is keyed by tree hash: a new hill version starts a fresh
attempts history, because a changed evaluator is a new game.

### Locks bind what git must not hold

Two lock files, regenerated from disk at every commit:

| lock | covers | why it is not in git |
|---|---|---|
| `private.lock` | every file under `private/` | git has no per-path access control and its history is permanent, so anything ever committed is distributable forever, and leaked held-out data ends up in future training corpora |
| `blobs.lock` | large assets outside `private/` | anything matching a `track` pattern or over the size threshold |

The tree hash *commits to* private content through the lock without *containing*
it. There is no blob store, no symlink farm, no content-addressed cache: the lock
file is the tracking, and integrity is enforced at the two moments it matters, at
`commit` (locks regenerated from disk) and at `eval` (disk verified against the
locks at HEAD; a mismatch is a hard error naming the file).

### Reports are signed, history is chained

The dict your evaluator returns is the report **core**. The tool wraps it in an
envelope: hill name, tree hash, commit, submission hash, submission git lineage,
params, tool version and package hash, timestamp, and an HMAC signature over the
canonicalized report. The key lives at `~/.autolab/hills/key`, mode 0600,
deliberately outside any project directory an agent works in.

Every eval appends to an attempts log whose entries are HMAC-chained to the one
before, so a deleted or edited line is detectable. `hills attempts` prints the
break rather than hiding it.

### Trust posture

This tool defends against **self-deception**: an agent loop accidentally or
opportunistically grading its own work, editing its own scores, or drifting its
own evaluation criteria.

It does not defend against a malicious human operator. Private files are ordinary
files, protected by convention and by the tool only handing their location to the
evaluator process. Signed reports are tamper-evident, not tamper-proof.

The honest claim: **your agent cannot fake a hills report; you could, but then
you're only lying to yourself.** Disputed results are re-runnable, because hills
are inspectable and submissions are hashed, so verification is ultimately by
replay, not by trust in any single machine.

## Working with a coding agent

The [agent skill](https://github.com/autolab-hq/hills/blob/main/skills/hills/SKILL.md) ships in this repo, version-locked to
the CLI, and installs with `npx skills add autolab-hq/hills` or `hills setup`. It
has two halves, kept deliberately apart.

**Authoring.** The agent interviews you briefly in plain ML language, extracts
and freezes your evaluation logic into the hill, sorts content across the private
boundary, and writes the README-as-contract, an example submission, and tests. It
then red-teams its own draft and presents a decision brief: what the hill
measures, which gaming vectors it closed, and which remain open as your design
decision. **You** run `hills commit`. The agent that wrote the evaluator does not
get to freeze it.

**Climbing.** A fresh subagent starts from `hills describe` and nothing else,
keeps research directions as git worktrees, and loops: edit, dev-run, `hills
eval`, decide. Its delegation prompt carries only the hill name and your goal,
because the authoring context has seen the evaluator's internals and the climbing
context must not inherit them.

Total human surface for the whole journey: one install, one commit, one "proceed"
with stopping criteria.

## Reference

### Commands

| command | what it does |
|---|---|
| `hills new <name> [-t template]` | scaffold a hill, init `.vc`, register it |
| `hills check <name>` | manifest, evaluator contract, `tests/` |
| `hills status <name>` | changes since the last commit, including lock drift git cannot see |
| `hills commit <name> -m "..."` | check, regenerate locks, commit, print the tree hash |
| `hills log <name>` | version history, with eval counts per version |
| `hills describe <name>` | README, params, submission contract, as JSON |
| `hills eval <dir> -H <name>` | score a submission directory |
| `hills attempts <name>` | eval history for this version; flags a broken chain |
| `hills verify <report.json>` | check a report's signature |
| `hills list` | registered hills |
| `hills setup` | install the agent skill into detected harnesses |
| `hills home` | where machine state lives |

`hills eval` flags: `-p key=value` (repeatable), `--final` for test mode,
`--force`, `--current`, `--queue`, `-v` to stream evaluator output, `-o` to also
write the report to a file.

It evaluates **HEAD, never the working tree**. A dirty hill is an error: commit
it, `--force` to score the last committed version anyway, or `--current` to test
a draft evaluator against a real submission (unofficial, `tree_hash: null`,
logged separately).

### Machine state

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

### Repository layout

```
src/hills/          the library and CLI
skills/hills/       the agent skill, version-locked to the CLI
examples/           the example hills, also usable as `hills new -t <name>`
docs/SPEC.md        the design specification this implements
tests/              tests for the tool
```

The two shipped hills: **circle-packing**, the hello-world used above, exact
arithmetic and no private data; and **nanogpt-10min**, a timed training run whose
evaluator owns the clock, keeps its splits in `private/`, and reports a
normalized GPU profile as primary config.

## License

MIT. See [LICENSE](https://github.com/autolab-hq/hills/blob/main/LICENSE).
