<h1 align="center">hills</h1>

<p align="center"><strong>Let an agent run your optimization loop, without letting it grade its own work</strong></p>

<p align="center">
  <a href="#quickstart">Quickstart</a> ·
  <a href="#what-a-hill-is">What a hill is</a> ·
  <a href="#how-it-stays-honest">How it stays honest</a> ·
  <a href="#reference">Reference</a> ·
  <a href="https://github.com/autolab-ai/hills/blob/main/docs/SPEC.md">Spec</a> ·
  <a href="https://github.com/autolab-ai/hills/blob/main/skills/hills/SKILL.md">Agent skill</a>
</p>

<p align="center">
  <img alt="MIT license" src="https://img.shields.io/badge/license-MIT-7fa846?style=flat-square&labelColor=1c1c1c">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11+-7fa846?style=flat-square&labelColor=1c1c1c">
</p>

> When you use an agent to run an iterative optimization loop, the same model
> writes the code, runs the evaluation, and tells you the score. It grades its
> own homework, so the numbers cannot be trusted. **hills splits those two jobs
> apart.**

<p align="center">
  <img src="https://raw.githubusercontent.com/autolab-ai/hills/main/docs/banner.png"
       alt="hills: agents can climb, evaluators can judge"
       width="900">
</p>

You package the evaluation into a **hill**: a folder holding the task
description, the scoring code, and any data the agent must not see. You freeze
it. From then on the agent can write whatever code it likes, but a score exists
only if `hills eval` produced it, and every score comes back signed and tied to
the exact version of the evaluator that produced it.

A hill is a versioned folder: `hills commit` freezes it, and every score is
pinned to the version that produced it. Change the evaluator and you get a new
version with a fresh history, because a changed evaluator is a different game.

<a id="quickstart"></a>

## 🧑‍💻 Quickstart

Install the skill. It bootstraps the CLI itself on first use, so this is the
only command you run.

```bash
npx skills add autolab-ai/hills
```

Then tell your coding agent what you want, in your own words:

> Please help me create an optimization environment and improve on it using hills

It will look at your project, agree a plan with you (what number to move, what
it may edit, what stays read-only, what is held out, what would count as
cheating), build the evaluation and hand it back for review. You run one command
by hand, `hills commit`, which freezes it. Then it climbs, autonomously, until
your stopping criteria are met.

That one command is deliberate. The agent that wrote the evaluator does not get
to freeze it.

## 🤖 Quickstart

Two minutes, no GPU, no network after install. We will create the hello-world
hill, freeze it, score a submission against it, and then show what happens when
someone edits the score.

**1. Install.**

```bash
uv tool install hills
```

**2. Create a hill.** `circle-packing` ships with the tool: place 26 circles in
the unit square without overlaps, maximize the sum of the radii.

```console
$ mkdir demo && cd demo && git init -q .
$ hills new circle-packing -t circle-packing
hills: created machine state at ~/.autolab/hills
created demo/.autolab/hills/circle-packing
  template   circle-packing
  version control  demo/.autolab/hills/circle-packing/.vc (empty; nothing committed yet)
```

Setup asked you nothing and edited no file of yours. `.autolab/` carries a
`.gitignore` containing `*`, so it hides itself from your project's git the way
`uv` hides `.venv`.

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

**4. Score a submission.** A submission is just a folder. The hill ships one:

```console
$ cp -r .autolab/hills/circle-packing/examples/grid ./my-packing
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

An edited score stops verifying. Nobody has to notice the edit.

**Where to go next.** `hills describe circle-packing` prints the contract your
agent would read. `hills new <name>` scaffolds a blank hill for your own task,
and `hills examples` lists the examples you can start from, such as
`nanogpt-10min`: a timed training run scored on a held-out split the agent
never sees.

## What a hill is

A folder, versioned by its own private git repository:

```
.autolab/hills/circle-packing/
  hill.yaml        settings: the watchdog, typed knobs, large-file rules
  README.md        the task, written for the agent that will read it
  eval.py          the scoring code: def eval(submission: Path, **params) -> dict
  private/         what the agent must not see; never enters git
  examples/        a submission that scores, so the format is unambiguous
  tests/           checks on the hill itself, run by `hills check`
  .vc/             the hill's own git dir, named so it cannot clash with yours
```

`private/` is the only special folder: it holds what the agent must not see.
Everything else it may read, **including `eval.py`**. That is deliberate -
knowing how you are scored is fine, knowing the answers is not - so anything
that gives away an answer belongs in `private/`, never inline in the evaluator.

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

A submission is a folder. That is the whole input contract: a codebase, model
weights, or a single JSON file are all just files in a folder.

The evaluator always runs in its own process, in the hill's own uv environment.
So each hill keeps its own dependencies, a hung evaluation can be killed, and an
evaluator that crashes cannot take the tool down with it. When the task is timed,
the evaluator starts the agent's code and stops it at the deadline, so the agent
never holds the stopwatch.

`config` records the conditions the number was measured under. Entries marked
`primary` decide what may be compared with what: a score on an H100 and a score
on an A100 never rank against each other. Metrics are a list in priority order,
each with its own direction, so ties break down the list. Given any pile of
reports, that is enough to sort them into ranked groups on its own.

## How it stays honest

### A hill is identified by its contents

A hill is identified by its **git tree hash**, not its commit hash. A tree hash
is computed purely from the files, so the same hill has the same identity on
every machine, however it got there. Everything is filed under it, which is why
editing the evaluator starts a fresh history rather than mixing old and new
scores together.

### Held-out data is hashed, never committed

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

### Scores are signed, and the log is tamper-evident

Your evaluator returns the metrics. Around them the tool wraps everything needed
to check the score later: which hill and which version, a hash of the submission
and the branch and commit it came from, the settings used, the tool version, a
timestamp, and a signature over all of it. The signing key sits at
`~/.autolab/hills/key`, mode 0600, deliberately outside any folder an agent
works in - if the agent could read it, it could forge scores.

Every eval appends a line to a log, and each line is cryptographically chained to
the one before it, so a deleted or edited entry shows up. `hills attempts` prints
the break rather than quietly hiding it.

### Trust posture

This tool defends against **fooling yourself**: an agent loop that grades its own
work, edits its own scores, or lets the definition of the metric drift while it
optimizes - usually by accident, which is what makes it hard to catch.

It does not stop a determined human. Files under `private/` are ordinary files;
nothing but convention keeps you out of them. Signed scores show tampering, they
do not prevent it.

The honest claim: **your agent cannot fake a hills report; you could, but then
you're only lying to yourself.** Disputed results are re-runnable, because hills
are inspectable and submissions are hashed, so verification is ultimately by
replay, not by trust in any single machine.

## Working with a coding agent

The [agent skill](https://github.com/autolab-ai/hills/blob/main/skills/hills/SKILL.md) ships in this repo, version-locked to
the CLI, and installs with `npx skills add autolab-ai/hills` or `hills setup`.
You do not have to know what a hill is to use it: it triggers on any request to
improve a number by iterating, and builds the hill as part of the job.

It runs in four phases.

1. **Confirm the project.** A minute, no more. What is this, and is it what you
   want to optimize?
2. **Agree on a plan.** What the number stands in for, goal and direction, files
   in scope, files that are read-only, what is held out, the constraint that
   makes runs comparable, the ways the number could move without the work being
   done, the run command, and when to stop. You confirm or edit it before
   anything is built.
3. **Build and freeze the hill.** The plan becomes a hill: read-only files are
   frozen into it, held-out data moves into `private/`, and the scoring code is
   copied rather than imported so it cannot drift with your project. The agent
   then tries to beat its own draft, and presents a brief: the leaks it closed,
   and any gap it measured between the metric and what you actually want, with
   options from a sentence in the README up to changing the task. Which one you
   take is your call. **You** run `hills commit`. The agent that wrote the
   evaluator does not get to freeze it.
4. **The experiment loop.** A fresh subagent starts from `hills describe` and
   nothing else, then loops: edit, commit, dev-run, `hills eval`, decide. It does
   not stop to ask permission, and it runs until your stopping criteria are met.

The third phase is the one a self-graded loop skips, and it is the reason the
numbers at the end mean something. Total human surface: one install, one commit,
one "proceed" with stopping criteria.

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
| `hills list` | the hills in this project |
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

MIT. See [LICENSE](https://github.com/autolab-ai/hills/blob/main/LICENSE).
