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
writing code, then look at `examples/` in the hill directory: those are working
submissions and they answer format questions faster than reasoning does.

You may read anything in the hill except `private/`. `eval.py` is meant to be
read, so understanding how you are scored is encouraged; reading the held-out
data is not.

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

Two or three directions is usually right. More than that and none of them gets
enough attempts to say anything. The same no-reset rule applies inside each.

## The loop

1. Edit the in-scope files with one idea.
2. Commit.
3. Dev-run informally if you need to know whether the idea works at all. These
   numbers are **unofficial** and must be labeled that way every time.
4. `hills eval <dir> -H <name>`, redirecting verbose output to a file rather
   than into your context.
5. Read `passed`, `metrics`, `config`, `details`. `details` carries the feedback
   the hill author chose to expose: log tails, per-case results, failure reasons.
6. Decide and record why. The attempts log keeps the numbers; your notes keep the
   reasoning, which is the part that stops you re-running a dead idea in an hour.
7. Repeat.

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
   numbers only if useful, and only labeled unofficial.

## Failure modes to avoid

- **Reporting a dev number as a result.** The most common way this loop goes
  wrong. If `hills eval` did not produce it, it is not a result.
- **Tuning against the test split.** `--final` is for the final claim. Running it
  repeatedly and keeping the best turns the test split into a validation split.
- **Editing the hill.** If you believe the evaluator is wrong, stop and tell the
  user what you think is wrong and why. `hills eval` refuses a dirty hill anyway,
  and a changed hill has a different tree hash, so your score would no longer be
  comparable to anything before it.
- **Optimizing the checker instead of the task.** If you find a way to score well
  without doing the task, that is a finding to report, not a result to submit.
- **Claiming progress from one noisy run.** Two attempts differing by less than
  the run-to-run spread are not an improvement.
- **Stopping early.** The user may be asleep. Run until the criteria are met or
  you are interrupted.
