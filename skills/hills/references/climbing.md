# The experiment loop (phase 4)

You have a hill name and a goal. That is everything you are supposed to have.

This phase is autonomous. Do not ask permission before each eval. Ask only if the
stopping criteria are unclear or something outside the loop breaks.

## Starting

```
hills describe <name>
```

That returns the README, the params schema, the file list of the committed hill,
and the tree hash you will be scored against. Read the README completely before
writing code, including what it says the number stands in for; when the metric
and that goal point in different directions, the goal is what you are optimizing.
Then look at `examples/` in the hill directory: those are working submissions and
they answer format questions faster than reasoning does.

You may read anything in the hill except `private/`. `eval.py` is meant to be
read, so understanding how you are scored is encouraged; reading the held-out
data is not.

**Score the baseline before you change anything.** It is the reference every
later claim is measured against, and it proves the pipeline runs before you have
an idea invested in it. Score it twice if an attempt is cheap: the difference
between two evaluations of the same submission is the run-to-run spread, and
nothing smaller than that is an improvement you can honestly claim.

## Branches

Default to a single branch, `hills/<name>`, with one commit per experiment:

```
hills/<name>: <short description of the change>
```

**Do not `reset --hard` a discarded experiment away.** Each report records
`submission_git` as `branch@short-sha`. Discarding the commit leaves a signed
score pointing at a sha nobody can check out, so the score can no longer be
reproduced. Keep history linear and complete; when an experiment is worse, the
next commit reverts the in-scope files as part of its own change.

Commit before every eval. Uncommitted work comes back labeled `+dirty` and two
attempts become indistinguishable in the log afterwards.

**When you are running several independent directions** rather than one linear
search, give each its own worktree and its own branch:

```
git worktree add ../<project>-directions/<direction> -b hills/<name>-<direction>
```

How many is arithmetic rather than taste: a direction needs enough attempts to
separate a real gain from the spread you measured at the start, so divide the
time you have by the cost of one attempt. Two or three is common at minutes per
attempt, and more is right at seconds. The same no-reset rule applies inside each.

## The loop

Edit the in-scope files, commit, `hills eval <dir> -H <name>`, read the report,
decide, repeat. One idea per iteration is the default because it is what makes a
result attributable; depart from it deliberately rather than by accident.

Redirect verbose eval output to a file rather than into your context. Read
`passed`, `metrics`, `config` and `details`. `details` carries the feedback the
hill author chose to expose: log tails, per-case results, failure reasons.

The attempts log keeps the numbers. Your notes keep why you decided what you
decided, which is the part that stops you re-running a dead idea in an hour.

If the hill declares an exclusive device, official evals serialize. A second one
fails fast; `--queue` waits instead. When you wait, say so, and use the time for
dev work in another direction.

## Params

`-p key=value` overrides a declared param. Changing a **primary** param, a time
budget for instance, puts your report in a different comparability group: a
600-second score and a 300-second score do not compete. Iterating at a smaller
budget is fine when the hill allows it, but the final claim must be at the budget
the user cares about.

## Keeping your own diagnostics

The tool gives you no logging channel, deliberately. Your submission is an
ordinary process and can write whatever it likes into your workspace. Keep loss
curves, profiles and notes there, named by the report's `submission_hash` so a
curve stays attached to the score it produced. The hill remembers nothing about
you; `hills attempts` remembers only what the evaluator returned.

## Finishing

Stop when the stopping criteria are met, or when the last several attempts have
not moved the metric and you have no untried idea worth its cost. Then:

1. `hills eval <best> -H <name> --final`
2. Report: the attempts table, the best verified result with its config and
   `submission_git`, the `--final` report, and briefly what did not work. Dev
   numbers only if useful, and only labeled unofficial. If you did not beat the
   baseline, say so plainly; a hill you did not climb is a result.

## Selection

The iron rules list the behaviours. This is the reasoning behind the one that is
easiest to talk yourself into.

A best-over-attempts is an order statistic, not a measurement. When evaluation is
noisy, running the same artifact again can only raise the maximum, so a headline
taken from "best attempt so far" drifts upward whether or not anything improved.
In a corpus of real optimization runs we read, one agent scored 18 iterations of
a byte-identical file and reported the luckiest of the 18, sitting 0.16 percent
above their mean. Nothing was forged and every report was honest. The corruption
was in the aggregation.

So a re-run measures noise rather than giving a submission a second chance at a
score, a difference inside the spread is not a difference, and if you evaluate
anything twice the spread is part of the result.

The other way to end badly is stopping early. The user may be asleep. Run until
the criteria are met or you are interrupted. And if you find a way to score well
without doing what the README says the task is for, that is a finding to report
to the user, not a result to submit.
