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

**The README states which files you may edit and what you may change inside
them.** That boundary was decided when the hill was built and it is not
yours to widen. Anything it does not grant you, you do not have.

**Confirm where the runs happen before the first one.** If it was not settled
when you were handed the task, ask, offering the hosts in `~/.ssh/config` and
local. Hardware is usually a primary config entry, so switching machines partway
splits your results into two groups that do not rank against each other.

**Write `journal.html` before you score anything.** If a hill was handed to you,
this is your first action, ahead of the baseline: the goal, the stopping
criteria, the plan you intend to try, and an empty results table. Then tell the
user where it is, on its own line, with the command to open it:

```
open journal.html
```

Say that it stays current while you work and they can look at any time without
interrupting you. Do this even if the run is about to be short. A page that
appears only once there are results is a page nobody knew to watch.

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

LOOP FOREVER:

1. **Look at where you are.** Current branch and commit, and the status at the
   top of `journal.html`.
2. **Pick one idea and implement it.** Edit only the in-scope files. One idea per
   iteration is the default, because it is what makes a result attributable;
   depart from it deliberately rather than by accident.
3. **Commit.** `hills/<name>: <short description>`. Uncommitted work comes back
   labeled `+dirty` and two attempts become indistinguishable in the log.
4. **Score it**, writing the signed report where the page can link to it, and
   redirecting the rest rather than letting it flood your context:
   ```bash
   hills eval <dir> -H <name> -o reports/<NNN>-<slug>.json > /dev/null 2> eval.log
   ```
5. **Read the result.** `passed`, `metrics`, `config`, `details`. `details` is the
   feedback the hill author chose to expose: log tails, per-case results, failure
   reasons. If there is no report, the run failed; `tail -n 50 eval.log`.
6. **Decide**, against the spread you measured at the start:
   - **Better than the baseline by more than the spread**: keep it. The branch
     advances and the next idea builds on this one.
   - **Inside the spread, or worse**: discard. The next commit reverts the
     in-scope files as part of its own change.
   - **Crashed**: see below.
7. **Update `journal.html` in the same commit**, linking the new row to the
   report you just wrote. Never in a batch at the end. Record crashes and
   results you dislike too; a page with the failures removed reads as a clean
   run, which is the opposite of what it is for.
8. Repeat.

`hills attempts` keeps the numbers. `journal.html` is where you say what they
meant: why you kept or dropped each idea, which is the part that stops you
re-running a dead idea in an hour, and it is how the user sees where you are
without interrupting you. The skill specifies what the page has to do; what goes
in it is your call.

If the hill declares an exclusive device, official evals serialize. A second one
fails fast; `--queue` waits instead. When you wait, say so, and use the time for
dev work in another direction.

## Crashes and timeouts

A crash is not a score. `passed: false` is.

If the failure is something dumb, a typo or a missing import or a shape
mismatch, fix it and re-run. If the idea itself is fundamentally broken, or you have failed
to make it work after a few attempts, record it as a crash in `journal.html`,
revert,
and move on. Do not spend an hour rescuing an idea that was worth ten minutes.

The hill's watchdog kills a hung evaluation on its own. Your own dev runs have no
watchdog: if one exceeds twice what you expected, kill it and treat it as a
failure. An OOM is a result about the idea, not an accident; record it.

## Simplicity

All else equal, simpler wins. When you weigh a change, weigh the complexity
against the size of the gain:

- a small gain that adds fifty lines of hack: probably not worth keeping
- the same small gain from **deleting** code: definitely keep
- no change in the metric but noticeably simpler code: keep

A simplification that holds the number is a real result and belongs in
`journal.html` as one.

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

## If the evaluation looks wrong

You cannot fix it. You have not seen the hill's internals and are not supposed
to, so a change made from here would be made blind. Stop climbing, write what
looks wrong and what evidence you have into `journal.html`, and hand it back to
whoever authored the hill. Do not keep scoring against an evaluator you believe
is broken just to keep the loop moving.

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

The other way to end badly is stopping early.

**Never stop to ask whether to keep going.** Not "should I continue?", not "is
this a good stopping point?". The user may be asleep or away, and expects to come
back to results. Run until the stopping criteria are met or you are interrupted.
At five minutes an experiment that is roughly a hundred attempts across a night;
the value of the whole arrangement is that they wake up to all of them.

Out of ideas is not a reason to stop, it is a reason to think harder: re-read the
in-scope files for angles you missed, combine two near misses, try something more
radical than you would try while being watched, chase papers referenced in
comments, try removing things.

And if you find a way to score well without doing what the README says the task
is for, that is a finding to report to the user, not a result to submit.
