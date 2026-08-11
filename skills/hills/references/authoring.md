# Building the hill (phases 2 and 3)

Read this once the phase 2 plan is agreed. The goal is an evaluation that still
measures the user's goal when an agent optimizing the metric goes looking for
shortcuts, which in a few hours is what you will be doing.

## Asking the right questions in phase 2

The plan's questions exist so the hill measures the user's goal rather than
drifting into measuring something adjacent to it. Four carry most of the weight,
so if the user is impatient, ask these:

- **What is this number standing in for?** Ask it first, answer it out loud, and
  check the answer with them. A toy dataset, a proxy metric or a small benchmark
  is nearly always a stand-in for something larger, and what it stands in for
  decides how much the rest of the design has to defend.
- **What is held out, and what may be trained or tuned on?** Confirm the split
  moves into `private/` and never enters git. If the user says "there is no
  held-out set", that is the first thing to fix, not a detail to work around.
- **Who owns the clock, and what is fixed across runs?** If the metric is
  wall-clock, throughput or cost, the evaluator has to launch the process and
  enforce the budget. A submission that reports its own elapsed time is not a
  measurement.
- **How much should a failed run tell the agent?** Generous feedback makes the
  loop productive; anything that echoes hidden test content makes the hill
  worthless. Propose the most generous setting that leaks nothing.

Also confirm out loud that the evaluation logic is being **copied and frozen**
into the hill rather than imported from the project. People are often surprised
by this, and it is what stops old scores from silently changing meaning.

## Filling in the hill

**`hill.yaml`** holds only what the tool needs to run the evaluator: the
watchdog bound, typed params, blob rules, and `exclusive: gpu` when the metric is
a physical measurement on shared hardware. Semantic limits belong in `eval.py`.

**`eval.py`** is one function:

```python
def eval(submission: Path, *, final: bool = False, **params) -> dict:
    return {
        "passed": bool,
        "metrics": [{"name": ..., "value": ..., "direction": "min" | "max"}],
        "config":  [{"name": ..., "value": ..., "primary": bool}],
        "details": {...},
    }
```

Metrics rank lexicographically in the order you list them, so the primary metric
goes first and the rest break ties. Primary config entries define comparability:
two reports rank together only if their primary tuples match. Hardware profile,
time budget and mode belong in primary; library versions and diagnostics do not.

Compute the metric from raw artifacts. If the evaluator reads a number the
submission produced, it is reporting the submission's claim, not measuring it.

**The private boundary.** The agent may read everything in a hill except
`private/`, and that includes `eval.py`. So any constant that reveals an answer,
such as hidden test shapes or expected outputs, lives in `private/` and is read
from there.

**Defensive authoring rule.** Do not open the user's held-out data beyond
sniffing enough bytes to confirm the format, and tell the user that is what you
did. You are writing the evaluator; you should not be carrying around what is in
the test set.

**`README.md` is the contract**, and the only thing the climbing context reads.
Task, what the number stands in for, submission format as a directory listing,
how the metric is computed, params, test mode, and a short "what the evaluator
will not do". The climber optimizes what this file says, so a goal stated here
is the cheapest defense the hill has.

**`examples/`** needs at least one submission that scores; it answers "what does
a submission look like" faster than prose. **`tests/`** are ordinary pytest
files, and `from hills import run_evaluator` gives you `run_evaluator(hill_path,
submission_path, **params) -> dict`. Write at least: the example scores as
expected, a broken variant fails with a useful message, and the primary config is
what you think it is. Turn expensive params down so `hills check` stays fast.

## Attacking your own draft

Before showing the user anything, try to beat the hill you just wrote. What you
find sorts into two piles, and they are handled differently.

**Plumbing leaks** have a right answer, so close them and move on. Each one is
either the evaluator trusting a number the submission produced, or information
travelling outward from `private/`. These six recur, and the pair of principles
is what you check the seventh against:

| leak | what it looks like | how to close it |
|---|---|---|
| metric computed by the submission | evaluator reads a number the submission wrote | compute it from raw artifacts only |
| clock not evaluator-owned | submission self-reports elapsed time, or sleeps past a soft limit | evaluator launches the process and kills it at the deadline |
| leakage through feedback | error messages echo test inputs, counts, or per-case answers | say what failed, not what the answer was |
| leakage through the tree | test data committed "just this once" | it never enters git; `private.lock` binds it by hash |
| stale artifact reuse | evaluator finds a checkpoint from a previous run | fresh working directory per evaluation |
| evaluator drift | evaluator imports the user's project code | freeze a copy inside the hill |

**A gap between the metric and the goal** is the other pile: a way of scoring
well that skips the work the user cares about. A closed form the task was meant
to approximate, a degenerate output the metric does not forbid, scaling up
something the metric does not constrain. Measure it, because "sampling the closed
form scores four times better than a trained model" tells the user far more than
"the metric is gameable".

Then bring it to them. Closing a gap usually means changing their task, which is
theirs to decide and not a defect you fix on their behalf. Give the finding, its
size, and the responses from the SKILL with what each costs, and recommend the
smallest one the goal survives. A toy problem with a known shortcut is often
exactly what the user wants for a first run.

## What the hill can resolve

An honest hill that cannot detect the improvement anyone hopes for is still a bad
hill. Score the example submission twice, three times if it is cheap, and you
have both numbers: the baseline, which is what "improve" is measured against, and
the spread, which is the smallest gain this hill can tell from noise. Report both
in the brief, and if the spread is wider than the gains the user expects, say so
before anything is frozen; the usual fixes are averaging over more cases or seeds
inside the evaluator, or fixing whatever varies between runs. Repeating the
evaluation also runs the loop end to end while the hill is still editable.

## When to propose more than one hill

If the user's goals genuinely decompose into distinct objectives, such as quality
at a fixed time budget *and* raw throughput, do not compress them into one metric
with weights nobody can defend. Propose specific hills, named, with their metrics
stated. Two concrete proposals, not an open-ended menu.

## The brief, and the handoff

The brief goes in your message, not in a file. Open it with the goal in one
sentence and how the hill measures it, so the user can correct your reading
before reading anything else. Give the baseline and the spread, so they know what
"improve" means here and how small a gain this hill can still see. Its last
section is the one that matters: each gap you measured, presented as the user's
decision with concrete options and your recommendation.

Then stop. The human runs `hills commit`. After it lands, ask two things: proceed
to climbing, and what the stopping criteria are. On yes, delegate phase 4 to a
fresh subagent. Its prompt carries the hill name, the user's goal, the stopping
criteria, and an instruction to load the hills skill and follow
`references/climbing.md`. Nothing else: no summary of your authoring work, no
mention of what is in `private/`, no hints about what you think will work. Your
context has seen the evaluator's internals; the climbing context must not inherit
that.
