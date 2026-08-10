# Authoring a hill

Goal: turn what the user already measures into an evaluation that stays honest
when a metric-maximizing agent attacks it.

## 1. Interview

Two or three questions, in plain ML language. Every question exists to make the
hill harder to cheat. Ask them together, with your own proposal for each, so the
user can answer with "yes" or a correction.

- **Metric and direction.** What number decides whether one run beat another,
  and is lower or higher better? If the user names several, see "when to propose
  more than one hill" below.
- **What is held out.** Which split does the climber train on, which does the
  evaluator score on, and is there a separate test split for the final claim?
  Confirm the held-out data moves into `private/` and never enters git.
- **Feedback.** How much should a failed run tell the climber? Full traces and
  per-case results make climbing productive; anything that reveals hidden test
  content makes the hill worthless. Propose the most generous setting that
  leaks nothing.
- **Confirm the freeze.** The evaluation logic gets copied into the hill and
  frozen there, so the hill's judgment cannot drift when the user's project
  changes. Say this out loud; people are often surprised by it.

If the metric is wall-clock, also confirm: the evaluator owns the clock, and the
submitted code runs as a subprocess it kills at the deadline.

## 2. Scaffold

```
hills new <name>
```

Use `-t circle-packing` or `-t nanogpt-10min` when one of them is close to the
shape of the task; both are complete working hills to edit rather than blank
files. `hills new` never asks anything and never edits a file of the user's.

## 3. Fill it in

**`hill.yaml`.** Only what the tool needs to run the evaluator: watchdog,
typed params, blob rules, and `exclusive: gpu` when the metric is a physical
measurement on shared hardware. Semantic limits belong in `eval.py`.

**`eval.py`.** One function, `def eval(submission: Path, *, final: bool = False,
**params) -> dict`. Extract the user's existing evaluation code into it rather
than importing from their project: a hill that imports the project drifts with
the project.

Return:

```python
{
  "passed": bool,
  "metrics": [{"name": ..., "value": ..., "direction": "min" | "max"}],
  "config":  [{"name": ..., "value": ..., "primary": bool}],
  "details": {...},
}
```

Metrics rank lexicographically in the order you list them. Primary config
entries define comparability: two reports rank together only if their primary
tuples match. Put hardware profile, time budget, and mode in primary. Put
library versions and diagnostics in non-primary.

**The private boundary.** Everything in a hill is climber-readable except
`private/`. That includes `eval.py`. So any constant that would reveal an answer
(hidden test shapes, expected outputs, tolerances that give away the test cases)
goes in `private/`, not inline in the evaluator.

**Defensive authoring rule.** Do not open the user's held-out data beyond
sniffing enough bytes to confirm the format, and tell the user you did that and
nothing more. You are about to write the evaluator; you should not be carrying
around what is in the test set.

**`README.md`.** This is the contract, and it is the only thing the climbing
agent will read. Task, submission format (a directory, and what must be in it),
metric and how it is computed, params, test mode, and a short "what the
evaluator will not do" section.

**`examples/`.** At least one minimal submission that scores. It is the fastest
possible answer to "what does a submission look like".

**`tests/`.** Ordinary pytest files. `from hills import run_evaluator` gives you
`run_evaluator(hill_path, submission_path, **params) -> dict`, so a test is
three lines. Write at least: the example submission scores as expected; a broken
variant fails with a useful message; the primary config is what you think it is.
Turn any expensive param down in tests so `hills check` stays fast.

## 4. Red-team your own draft

Before showing anything to the user, attack the hill you just wrote. Enumerate
how an agent optimizing the metric could satisfy its letter while violating its
intent. At minimum, check all of these:

| vector | what it looks like | how to close it |
|---|---|---|
| metric computed by the submission | evaluator reads a number the submission wrote | evaluator computes the metric from raw artifacts only |
| clock not evaluator-owned | submission self-reports elapsed time, or sleeps past a soft limit | evaluator launches the process and kills it at the deadline |
| held-out leakage through feedback | error messages echo test inputs, counts, or per-case answers | say what failed, not what the answer was |
| held-out leakage through the tree | test data committed to git "just this once" | it never enters git; `private.lock` binds it by hash |
| stale artifact reuse | evaluator finds a checkpoint from a previous run | fresh working directory per evaluation |
| degenerate optimum | metric does not constrain size, memory, or precision, so scaling up wins | constrain it, make it primary config, or surface it |
| evaluator drift | evaluator imports the user's project code | freeze a copy inside the hill |

Fix what you can fix in the evaluator. What you cannot fix becomes part of the
brief.

## 5. Check

```
hills check <name>
```

Manifest, evaluator contract, and `tests/`. It must be green before you write
the brief. `hills commit` runs it again as a gate.

## 6. The decision brief

Present in your message, not in a file:

1. **What this hill measures**, in one paragraph, in the user's own terms.
2. **Gaming vectors you closed**, and how. One line each.
3. **Gaming vectors that remain open** because the objective underdetermines
   them. Present each as the user's decision with concrete options: constrain it
   in the evaluator, make it a primary config entry so variants rank separately,
   or accept it and note it in the README. Recommend one.
4. Also state: what you read of the private data (headers only), and the exact
   command they should run.

Then stop. **The human runs `hills commit <name> -m "..."` themselves.** Do not
run it for them, do not offer to run it, and do not treat their "looks good" as
permission to run it. This is the trust transition of the whole system.

## When to propose more than one hill

If the user's goals genuinely decompose into distinct objectives (quality at a
fixed time budget *and* raw throughput; accuracy *and* memory footprint), do not
compress them into one metric with weights nobody can defend. Propose specific
hills, named, with their metrics stated. Two concrete proposals, not an
open-ended menu.

## After the commit

Ask two things:

- Proceed to climbing?
- Stopping criteria: target metric, time box, number of directions?

On yes, delegate to a fresh-context subagent. The delegation prompt contains
**only the hill name and the user's goal**. No summary of the authoring work, no
mention of what is in `private/`, no hints about what you think will work. Your
context has seen the evaluator's internals; the climbing context must not
inherit that.
