# Climbing a hill

You have a hill name and a goal. That is everything you are supposed to have.

This is an autonomous loop. Do not ask permission before each eval. Ask only if
the stopping criteria are unclear or something outside the loop breaks.

## Start

```
hills describe <name>
```

That returns the README, the params schema, the file list of the committed hill,
and the tree hash you will be scored against. Read the README completely before
writing code. Then look at `examples/` in the hill directory: those are working
submissions, and they answer format questions faster than reasoning does.

You may read anything in the hill except `private/`. `eval.py` is meant to be
read. Reading how you are judged is allowed and encouraged. Reading the held-out
data is not, and there is no version of "just to check the format" that makes it
acceptable.

## Set up directions

Keep research directions as git worktrees of the user's project, so directions
do not overwrite each other and every eval has clean lineage:

```
git worktree add ../<project>-directions/<direction-name>
```

The report records `submission_git` as `branch@short-sha`, which is how a score
stays attached to the code that produced it. Commit inside a direction before
evaluating it, or the label comes back `+dirty` and you will not be able to tell
two attempts apart later.

Two or three directions is usually right. More than that and none of them get
enough attempts to say anything.

## The loop

1. Edit inside one direction.
2. Run informal dev runs to find out whether the idea works at all. These are
   fast, self-timed, and **unofficial**. Say "unofficial" whenever you mention
   one of their numbers.
3. When a candidate looks ready:
   ```
   hills eval ../<project>-directions/<direction> -H <name>
   ```
4. Read the report: `passed`, `metrics`, `config`, `details`, `submission_git`.
   `details` is where the hill author put the feedback: log tails, per-case
   results, failure reasons. Use it.
5. Decide: keep, adjust, or drop the direction. Record why in your own notes.
6. Repeat.

If the hill declares an exclusive device, official evals serialize. A second one
fails fast with a clear message; pass `--queue` to wait instead. When you wait,
say so, and use the time for dev work in another direction.

## Keeping your own diagnostics

The tool gives you no logging channel, and that is deliberate: your submission
is an ordinary process and can write whatever it likes into your workspace. Keep
loss curves, profiles and notes there, and name them by the report's
`submission_hash` so a curve stays attached to the score it produced. The hill
remembers nothing about you; `hills attempts` remembers only what the evaluator
returned.

## Params

`-p key=value` overrides a declared param. Changing a primary param (a time
budget, for instance) puts your report in a different comparability group: a
600-second score and a 300-second score do not compete. Use a smaller budget for
fast iteration if the hill allows it, but the claim at the end must be at the
budget the user cares about.

## Stopping

Stop when the stopping criteria are met, or when the last several attempts stop
moving the metric and you have no untried idea worth its cost. Then:

1. Run the final claim in test mode:
   ```
   hills eval <best direction> -H <name> --final
   ```
2. Report back with:
   - the attempts table from `hills attempts <name>`
   - the best verified result, with its config and `submission_git`
   - the `--final` report
   - what you tried that did not work, briefly
   - dev numbers only if useful, and only labelled unofficial

## Failure modes to avoid

- **Reporting a dev number as a result.** The most common way this loop goes
  wrong. If it did not come from `hills eval`, it is not a result.
- **Tuning against the test split.** `--final` is for the final claim. Running
  it repeatedly and picking the best turns the test split into a validation
  split and quietly destroys the hill.
- **Editing the hill.** If you believe the evaluator is wrong, stop and tell the
  user what you think is wrong and why. Do not change it. `hills eval` refuses a
  dirty hill anyway, and a hill you edited produces a different tree hash, which
  means your score is no longer comparable to anything before it.
- **Optimizing the checker instead of the task.** If you find a way to score
  well without doing the task, that is a finding to report to the user, not a
  result to submit.
- **Claiming progress from a single noisy run.** If the metric is noisy, say so
  and re-run. Two attempts that differ by less than the run-to-run spread are
  not an improvement.
