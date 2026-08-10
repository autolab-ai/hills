# Hills — Design Specification v0

This document specifies **hills**, a local, open-source Python tool for creating and running verification environments ("hills") for AI research agents. It is an implementation brief: build exactly what is specified here.

## 1. The idea

When an AI agent runs research experiments autonomously, the same model writes the solution, evaluates it, and reports the result — it grades its own homework, so its reported numbers cannot be trusted. Hills fixes this by separating the two roles. A **hill** is a packaged evaluation task: a task description, an evaluator, and data. The agent (the **climber**) can develop however it likes, but an official score comes only from running `hills eval`, which executes the hill's evaluator in a separate process against a frozen, committed version of the hill, and returns a signed report. The agent can query the verifier; it cannot modify it or grade itself.

The mental model is git: a hill is a versioned directory, `hills commit` freezes it, and every score is tied to the exact version that produced it.

Design principles:
- **The hill defines the game; runtime state records the playing; version control tracks only the game.**
- **Agents do the work; humans perform the trust transitions.** An AI agent scaffolds and fills in a hill, but a human reviews and runs `hills commit`. An AI agent climbs, but the frozen evaluator scores.
- **Convention over configuration.** Every concept maps to something an ML engineer already knows: git commits, one Python function as the entrypoint, argparse-style typed parameters, self-ignoring directories like uv's `.venv`.
- **Zero-decision setup.** Installation and scaffolding must never ask the user to make configuration choices.

## 2. Anatomy of a hill

A hill is a directory, versioned by its own embedded git repository:

```
.autolab/hills/<name>/
  hill.yaml        # minimal manifest
  README.md        # the contract: task, submission format, metric — written for the climbing agent
  eval.py          # THE entrypoint — fixed name, at hill root
  private/         # evaluator-only content; never enters git (see §5)
  examples/        # one or more minimal demonstration submissions (freeform structure)
  tests/           # executable checks on the hill itself; run by `hills check`
  ...              # anything else (data/, src/, helpers) — the author's business
  .vc/             # the hill's git dir (named .vc, not .git, so it never collides with the user's project repo)
```

- **`private/` is the only special directory.** It holds anything the evaluator needs but climbers must not see: held-out test splits, hidden tolerances or test cases, reference solutions. It may contain data or code; `eval.py` may import from it.
- Everything else in the hill is climber-readable by design — including `eval.py`. Transparency about how you're judged is a feature. Consequence: any answer-revealing constants in evaluator code (hidden test shapes, expected outputs) must live in `private/`, not inline in `eval.py`.
- Hills live inside the user's project in `.autolab/hills/`. The `.autolab/` directory is created with its own `.gitignore` containing `*`, so it excludes itself from the project's git automatically (the same trick uv uses for `.venv`) — no edits to any user file, no prompts. A user who wants hills tracked in their project repo can edit that gitignore themselves; `.vc/` and `private/` must always remain excluded.
- A global registry (§7) maps hill names to paths, so all commands address hills by name from anywhere.

## 3. Manifest (`hill.yaml`)

The manifest contains only what the tool needs to run the evaluator. Everything semantic — the task, the metric's meaning, hardware notes — lives in `README.md` and `eval.py`.

```yaml
name: nanogpt-10min
version: 0.1.0
watchdog_timeout_s: 1200        # hard kill for a hung evaluator; NOT a semantic time limit
params:                         # optional; typed knobs, validated by the tool
  time_limit_s: {type: int, default: 600, min: 60, max: 1200}
blobs:                          # optional; large-file handling, see §5
  threshold: 10MB
  track: ["data/**"]
```

Semantic limits (e.g. "training gets 10 minutes") are enforced inside `eval.py`, which owns the official clock. `watchdog_timeout_s` is a generous last-resort bound so a hung evaluator cannot wedge an agent loop.

## 4. The evaluator contract

One fixed function in `eval.py` at the hill root:

```python
from pathlib import Path

def eval(submission: Path, **params) -> dict:
    ...
    return {
        "passed": True,
        "metrics": [{"name": "val_bpb", "value": 1.043, "direction": "min"}],
        "config":  [{"name": "time_limit_s", "value": 600, "primary": True},
                    {"name": "gpu", "value": "rtx4090-24gb", "primary": True},
                    {"name": "torch", "value": "2.9.1", "primary": False}],
        "details": {},           # optional freeform diagnostics/feedback
    }
```

- **A submission is a directory.** That is the entire input contract — a full codebase, model weights, or a single JSON file are all just files in a directory. The README describes the expected contents in prose; `eval.py` validates on entry.
- Manifest params arrive as keyword arguments with validated types, so the function signature documents the knobs. The tool passes CLI-provided values (`-p time_limit_s=300`) or defaults.
- **The tool never imports `eval.py` in-process.** It runs a small shim as a subprocess in the hill's own uv environment (each hill has its own `pyproject.toml`; the shim runs via `uv run` from the hill root, so the hill's dependencies are isolated from the tool's and from the user's project). The shim imports `eval.py`, calls `eval()`, writes the returned dict as JSON to a result file, and exits. This keeps per-hill dependencies clean, lets the watchdog kill a hung evaluation, and means an evaluator crash cannot take down the tool.
- For timed tasks, the evaluator launches the submitted code itself as a subprocess and enforces the time limit — the climber's code never runs the official clock.
- `config` entries describe the conditions of the measurement. Some come from params, some are detected by the evaluator (e.g. GPU model, normalized to a coarse profile string). Each is marked `primary` or not: primary entries define comparability — two reports are comparable only if their primary config tuples match. Non-primary entries are informational. The hill author decides what matters (e.g. GPU profile primary; driver version not).
- **Feedback richness is the author's choice**, made in `eval.py` via `details` and error messages. Authors are encouraged to expose as much useful feedback as possible (error traces, per-case results), while keeping information that reveals hidden test content out of it.
- Climbers instrument their own submissions for diagnostics (loss curves, profiling): submitted code is an ordinary process and can write logs anywhere in the climber's workspace. The tool provides no logging channel; the recommended convention is logging to the workspace keyed by the report's submission hash so scores and curves stay linked.

## 5. Versioning, identity, and locks

- Each hill is a git repo with git dir `.vc/`. The CLI wraps all git operations (`git --git-dir=.vc --work-tree=.` internally); users and agents never run git against a hill directly.
- **Hill identity is the git tree hash** (`HEAD^{tree}`), not the commit hash. Tree hashes are pure functions of content: the same files produce the same identity on any machine regardless of commit history. The commit hash is recorded in reports as provenance only. All state is keyed by tree hash.
- **Lock files** bind out-of-git content into that identity. They are generated deterministically by the tool at commit time — never written by hand or by an LLM; regeneration from disk overwrites any manual edit. Each entry is `{path, sha256, size}`, sorted by path.
  - `private.lock` — hashes of every file under `private/`. The files themselves **never enter git**: the tree hash *commits to* private content via the lock without *containing* it. Reasons this is strict: git has no per-path access control and history is permanent, so anything ever committed is distributable forever; and leaked held-out data ends up in future model training corpora, silently and permanently invalidating the hill.
  - `blobs.lock` — large assets outside `private/`. Rule: files matching a `track` pattern, or exceeding the threshold (default 1 MB), are lock-tracked; smaller files are committed to git normally. Pattern-level declaration (`track: ["data/**"]`) is the preferred mechanism; the size threshold is a safety net.
  - Lock-tracked files simply sit in the hill directory as ordinary files. There is no blob store, no symlinking, no content-addressed cache — the lock file *is* the tracking, and integrity is enforced at the two moments it matters: `commit` (locks regenerated from disk) and `eval` (disk verified against the locks at HEAD; mismatch is a hard error).

## 6. Reports

The evaluator's returned dict is the report **core**. The tool wraps it in the **envelope** — identity, hashes, signature — and prints the whole report as JSON. Hill authors never produce envelope fields.

```json
{
  "hill": "nanogpt-10min",
  "tree_hash": "a7f3e921…",
  "commit": "4b19c0d…",
  "submission_hash": "sha256:9f3e…",
  "submission_git": "muon-lr@c41aa2",
  "passed": true,
  "config":  [ ... ],
  "metrics": [ ... ],
  "details": { ... },
  "params": {"time_limit_s": 600},
  "tool": {"version": "0.1.0", "sha256": "…"},
  "timestamp": "2026-08-09T21:14:03Z",
  "signature": "hmac-sha256:…",
  "report_version": 1
}
```

- `submission_git` is recorded when the submission directory is a git checkout (branch@short-sha), giving free lineage from score to code version.
- `tool` records the version and package hash of the hills installation that produced the report, so every report states which build of the tool signed it.
- The signature is an HMAC over the canonicalized report using a per-machine key stored at `~/.autolab/hills/key` (created lazily on first use, mode 0600 — deliberately outside any project directory an agent works in). This makes reports tamper-evident: an agent cannot edit a score in a report file without invalidating the signature. `hills verify <report.json>` checks it.
- Metrics are an **ordered list** with per-metric direction; when comparing reports, ranking is lexicographic in that order, and only `passed: true` reports rank. Combined with primary-config comparability (§4), any set of reports sorts into ranked groups automatically, with no configuration beyond the reports themselves.

## 7. CLI

Unitary, git-style commands. The tool is fully local and offline.

```
hills new <name>               scaffold a hill in .autolab/hills/<name>/, init .vc, register it
hills check <name>             validate manifest + evaluator return schema; run tests/ if present
hills status <name>            working-tree changes vs last commit (wraps git status)
hills commit <name> -m "..."   run check → regenerate locks → git commit; print tree hash
hills log <name>               hill version history (wraps git log)
hills describe <name>          README + params schema + submission contract, as JSON
hills eval <dir> -H <name> [-p key=value ...] [--final] [--force | --current]
hills attempts <name>          history of evals from local state; flags any chain break
hills verify <report.json>     check a report's signature
hills setup                    install the agent skill into detected harnesses
```

`hills eval` semantics, precisely:
1. Resolve the hill by name by walking up from the current directory for `.autolab/hills/<name>`, the way git finds `.git`. A path may be given instead, for a hill in another project.
2. **Evaluate HEAD, never the working tree.** Materialize the hill from `.vc` HEAD via `git archive` into a temp dir; verify `private/` files and lock-tracked blobs on disk against the locks at HEAD (mismatch → hard error naming the file).
3. If the hill's working tree is dirty → **error**: "hill has uncommitted changes; commit them, or use --force to evaluate the last committed version." `--force` proceeds against HEAD with a warning. `--current` evaluates the working tree instead — for authors testing evaluator changes against a real submission before committing; its report carries `tree_hash: null` and `official: false` with reason `dirty-tree`, and is logged flagged as dirty.
4. `--final` requests test mode: by convention the evaluator scores against its held-out test split (e.g. `private/data/test.bin`) instead of the validation split. The mode is passed to the evaluator; the report's config records it.
5. Run: snapshot and hash the submission directory → spawn the shim subprocess in the hill's uv environment with the materialized hill root, the submission path, and resolved params → arm the watchdog → collect the result JSON → validate the core schema → wrap, stamp, sign → append to the attempts log → print the report.
6. Concurrency: evals of different submissions may run in parallel. For hills whose metric is a physical measurement on shared hardware (e.g. wall-clock training on a GPU), concurrent official runs corrupt the measurement, so the tool takes a per-device lock during such an eval; a second eval on the same device fails fast with a clear message, or waits if `--queue` is passed. Appends to the attempts log are mutex-protected.

Machine state lives under `~/.autolab/hills/`:
- `key` — the per-machine signing key.
- `state/<name>@<tree_hash>/attempts.jsonl` — append-only eval history, each entry HMAC-chained to the previous so gaps or edits are detectable. `hills attempts` reads it and flags a broken chain rather than hiding it. State is keyed by tree hash: a new hill version starts a fresh history, because a changed evaluator is a new game.

**Hills are stateless**: a hill emits signed reports and remembers nothing. Eval history is tool state under `~/.autolab`; the climbing agent keeps its own working notes.

`hills check` = manifest validation + a dry validation of the evaluator contract + running `tests/` if present. Tests are ordinary pytest files or scripts; the Python SDK provides helpers (e.g. `run_evaluator(hill_path, submission_path, **params) -> dict`) so a test is a few lines: run the evaluator on an example submission, assert on the result. Typical tests assert that `examples/` submissions score as expected and that a broken variant fails. `hills commit` refuses to commit if check fails.

## 8. Distribution and the agent skill

The repository is a monorepo: the Python library + CLI, this spec, example hills, and an **agent skill** — instructions that let coding agents (Claude Code and similar) create and climb hills conversationally. The skill is a first-class deliverable, version-locked to the CLI in the same repo.

Primary installation path is the skill itself: `npx skills add autolab-ai/hills` installs the skill into the user's agent harness; the skill then bootstraps the CLI on first use (`hills --version`; if missing, `uv tool install hills`). The reverse door also exists: `uv tool install hills && hills setup`, where `setup` detects installed harnesses and installs the skill files.

The skill has a router and two halves:

**Router.** On `/hills` or any hills-related request: ensure the CLI is installed → orient (`hills list`; inspect the current project) → one short clarifying exchange (create a hill from this project / climb an existing hill / other) → branch.

**Authoring half.** The agent interviews the user briefly in plain ML language — metric and direction, what data is held out, how much feedback the evaluator should expose — where every question exists to make the hill harder to cheat. It then scaffolds with `hills new`, extracts and freezes the evaluation logic from the user's code into the hill (so the hill's judgment cannot drift when the project changes), sorts content across the private boundary, writes the README-as-contract, a minimal `examples/` submission, and `tests/`. It performs a **red-team pass** on its own draft: enumerate how a metric-maximizing agent could satisfy the letter of the metric while violating its intent (metric computed by submitted code instead of the evaluator; hidden-test information leaking through error messages; timing gamed because the clock isn't evaluator-owned; degenerate solutions such as inflating model capacity when the metric doesn't constrain it) and fix each in the evaluator or surface it. Defensive authoring rule: do not open private data files beyond sniffing headers to confirm format, and say so. When the user's goals genuinely decompose into distinct objectives (e.g. quality at a fixed time budget *and* raw throughput), the agent proposes creating multiple hills, concretely — never as an open-ended menu.

**The decision brief and the commit.** Before anything is frozen, the agent presents in its message: (1) what this hill measures, in one paragraph; (2) gaming vectors it closed and how; (3) gaming vectors that remain open because the objective underdetermines them — presented as the user's design decision with concrete options (constrain it in the evaluator / make it a primary config entry so variants rank separately / accept it and note it in the README). Then the **human** runs `hills commit` themselves. This is deliberate: the agent that wrote the evaluator must not be the one to freeze it.

**Handoff.** After commit, the agent asks whether to proceed to climbing and for stopping criteria (target metric, time box, number of directions). On yes, it delegates to a fresh-context subagent. The delegation prompt may contain **only the hill name and the user's goal** — no summary of the authoring work. The subagent's entire knowledge of the hill starts at `hills describe`. This separation exists because the authoring context has seen the evaluator's internals and the private data layout; the climbing context must not inherit that. (Where subagents are unavailable, the skill instructs the user to clear the session before climbing.)

**Climbing half.** An autonomous loop with no per-eval permission asking. The subagent maintains research directions as git worktrees of the user's project, develops freely with informal self-timed runs (always labeled unofficial in its messages), and calls `hills eval` whenever a candidate is ready. Iron rules, stated in the skill: only an evaluator report is a result; self-measured numbers are never reported as results; the final claim is a `--final` (test-mode) report; lack of progress is reported honestly. The loop ends when the stopping criteria are met or progress stalls, and the subagent reports back with the attempts table (`hills attempts`) and the best verified result.

The skill is written defensively — it states plainly what the evaluator will not do (no scoring outside `hills eval`, no credit for edited report files) — because the agent reading it is precisely the agent the system is designed not to trust.

## 9. Initial example hills to ship

1. **circle-packing** (the hello-world): submission is a JSON of circle centers/radii; `eval.py` checks containment and non-overlap with exact arithmetic and computes the packing objective. ~50 lines, no `private/`, runs in seconds on any machine. Used throughout the docs.
2. **nanogpt-10min** (the flagship): submission is a directory with `train.py`; the evaluator executes it with the training data path, kills it at `time_limit_s`, evaluates the produced checkpoint on a held-out split in `private/data/`; detects and reports the GPU profile as primary config. Demonstrates evaluator-owned clocks, private splits, params, and test mode.

## 10. Trust posture (state this plainly in the README)

This tool defends against *self-deception*: an agent loop accidentally or opportunistically grading its own work, editing its own scores, or drifting its own evaluation criteria. It does not defend against a malicious human operator: private files are ordinary files protected by convention and by the tool only handing their location to the evaluator process, and signed reports are tamper-evident, not tamper-proof. The honest claim, and the one the README makes: **your agent cannot fake a hills report; you could, but then you're only lying to yourself.** Disputed results are re-runnable — hills are inspectable and submissions are hashed — so verification is ultimately by replay, not by trust in any single machine.

---

# User journey

Starting state: a user has `my-llm/` containing `train.py` (training and evaluation in one file) and `data/{train,val,test}.bin`. They want their coding agent to improve val loss without grading its own work.

1. **Install (the only setup command):** `npx skills add autolab-ai/hills`.
2. **Invoke.** The user tells their agent: "Make a hill out of this repo — val bpb after a 10-minute training run, test set hidden — then climb it." The agent checks `hills --version`, installs the CLI via uv if missing (first run lazily creates `~/.autolab/hills/` with a one-line notice), orients, and confirms the plan.
3. **Interview.** Two or three questions: how much feedback should failed runs expose? confirm test stays hidden and the clock is evaluator-owned; confirm the eval logic will be frozen into the hill.
4. **Scaffold and fill.** `hills new nanogpt-10min` creates `.autolab/hills/nanogpt-10min/` with `.vc` and the self-ignoring `.autolab/.gitignore`. The agent writes `hill.yaml` (watchdog, `params: time_limit_s`, `blobs.track: ["data/**"]`), `README.md` (submission contract: a directory with `train.py`, invoked as `python train.py --data <hill>/data/train.bin --out <workdir>/checkpoints/`; checkpoint expected at `checkpoints/final.pt`), and `eval.py` (launches the submitted `train.py`, kills at `time_limit_s`, runs the frozen bpb evaluation from the user's original code against `private/data/val.bin` — or `test.bin` in final mode — and detects the GPU, reporting a normalized profile as primary config). It moves val/test into `private/data/`, leaves training data at `data/`, writes a minimal `examples/` submission and `tests/` asserting the evaluator accepts it and rejects a broken variant. It notes: "I read only the header bytes of val/test to confirm format."
5. **Check.** `hills check nanogpt-10min` — manifest, contract, tests all green.
6. **Decision brief.** The agent presents: what the hill measures; closed vectors (clock evaluator-owned, eval code frozen, splits private); open vectors as the user's call ("model size is unconstrained — a climber can win by scaling up; constrain it, make it a primary config, or accept it?"). The user decides.
7. **Commit (the trust transition).** The user runs `hills commit nanogpt-10min -m "initial"` themselves: check gate → locks written (`private.lock`: 2 files; `blobs.lock`: train.bin) → committed; tree hash printed.
8. **Handoff.** Agent: "Proceed to climbing? Stopping criteria?" User: "Get under 1.0; up to 3 hours." The agent spawns the climbing subagent with exactly that and the hill name — nothing else.
9. **Climbing.** The subagent starts from `hills describe nanogpt-10min`, sets up worktrees (`my-llm-directions/muon-lr/`, `.../fused-kernels/`), and loops: edit → unofficial dev runs → `hills eval ../my-llm-directions/muon-lr -H nanogpt-10min` → read the signed report (metric, config, `submission_git` lineage) → decide → repeat. Official evals on the same GPU serialize via the device lock; the agent narrates the queue. On reaching the target (or stalling), it runs a `--final` test-mode eval and reports back: the attempts table and the best verified result, with dev numbers clearly labeled unofficial.
10. **Later hill edits.** `hills status` shows the diff; `eval` errors on the dirty tree; `--current` lets the author test a draft evaluator against a real submission (unofficial report, no state pollution); `hills commit` produces a new tree hash and a fresh attempts history.

Total human surface: one install command, one commit, one "proceed" with stopping criteria. Everything else is conversation.

---

# Implementation notes

Decisions this implementation made where the specification left room:

- **`final` reaches the evaluator as a keyword argument.** `eval(submission, *, final: bool = False, **params)`. `final` and `submission` are reserved param names in the manifest. The envelope also records `final` directly, so comparability does not depend on the author remembering to add a `mode` config entry (though the shipped examples add one).
- **`exclusive: <device>` in the manifest** declares that the metric is a physical measurement on shared hardware. `exclusive: gpu` resolves to `gpu:<first CUDA_VISIBLE_DEVICES index>` and takes a file lock under `~/.autolab/hills/locks/` for the duration of the eval.
- **Materialization uses symlinks for locked content.** `git archive HEAD` gives the committed tree; `private/` and each lock-tracked blob are verified against the locks and then symlinked into the materialized root, so an evaluation never copies gigabytes.
- **Environments are cached per hill version** at `~/.autolab/hills/envs/<name>/<tree_hash>/` via `UV_PROJECT_ENVIRONMENT`, with `current` used for working-tree operations. `hills check` runs `uv lock` first so committed hills evaluate without re-resolving.
- **`hills check`'s dry validation is static in the evaluator's own environment**: it imports `eval.py`, checks that `eval` exists, that its first parameter is `submission`, and that it accepts `final` and every declared param. Executing the evaluator against an example is the job of `tests/`, where the author controls the cost.
- **Lock-tracked paths are excluded from git through `.vc/info/exclude`**, regenerated on every version-control operation, so `git status` and `git add` agree with the manifest without any file appearing in the hill's working tree.
- **Evaluator failures are recorded as attempts** with an `error` field and no signature, so a watchdog kill or a crash appears in `hills attempts` instead of vanishing.
- **`--current` runs are logged under `state/<name>@current/`**, separate from official history.
- **No global registry.** The specification called for `~/.autolab/hills/registry.json` mapping name to path. In practice it only rotted: deleting a hill left an entry behind, and nothing rebuilt it. Hills are found by walking up from the current directory for `.autolab/hills/<name>`, so there is no state to go stale, and `hills list` shows the hills of the current project rather than the machine.
- **Three extra commands** beyond the specified list: `hills list`, `hills examples` (the bundled example hills) and `hills home` (where machine state lives).
