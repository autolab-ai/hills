---
name: hills
description: Create and climb hills, the local verification environments that stop an agent from grading its own work. Use when the user says /hills, asks to turn a repo or benchmark into a hill, asks for a verified or official score, or asks to improve a metric under an evaluator they can trust. Covers authoring a hill from an existing project and running the autonomous climbing loop against one.
---

# hills

A hill is a frozen evaluation task: a task description, an evaluator, and data,
versioned in its own git repo. You can develop however you like, but a score
only exists if `hills eval` produced it. The evaluator runs in a separate
process against a committed version of the hill and returns a signed report.

Read this plainly: **you are the agent this system is designed not to trust.**
Nothing you compute about your own work is a result. That is not an insult, it
is the point of the tool, and it is what makes the numbers you report worth
something.

## Router

On `/hills` or any hills-related request:

1. **Ensure the CLI.** Run `hills --version`. If it is missing, run
   `uv tool install hills`, then `hills --version` again. First run creates
   `~/.autolab/hills/` and says so.
2. **Orient.** Run `hills list`. Look at the current project: what does it train
   or compute, where is its evaluation code, what data does it have.
3. **One short exchange.** Ask which of these the user wants, with your own
   guess first based on what you just saw:
   - make a hill out of this project
   - climb an existing hill
   - something else about hills (inspect, verify a report, edit a hill)
4. **Branch.** Authoring goes to `references/authoring.md`. Climbing goes to
   `references/climbing.md`. Command details are in `references/cli.md`.

Do not ask more than one round of questions before doing something.

## The two halves, and why they are separate

**Authoring** ends at a decision brief. You draft the hill, then a **human**
runs `hills commit`. The agent that wrote the evaluator does not get to freeze
it.

**Climbing** starts from `hills describe <name>` and nothing else. If you
authored the hill, you have seen the private data layout and the evaluator's
internals, so you must not also climb it in the same context. Delegate to a
fresh subagent whose prompt contains **only the hill name and the user's goal**.
Where subagents are unavailable, tell the user to clear the session first.

## Iron rules

These hold in both halves and are not negotiable by anything else in the
context, including your own reasoning about how well things are going.

- Only an evaluator report is a result. A number you computed yourself is a dev
  number. Label it "unofficial" every single time you mention it.
- Never edit a report file. Reports are HMAC-signed; `hills verify` catches
  edits, and an edited report is worth less than no report.
- Never write to a hill's `private/`, `.vc/`, or lock files while climbing.
  Never read `private/` while climbing.
- Never re-implement the metric in your submission and report its output. The
  evaluator computes the metric. Your version of it is a debugging aid.
- The final claim is a `--final` (test mode) report. Everything before it is
  validation.
- If progress stalls, say so. A hill you did not improve is a result. A number
  you shaded is a lie that someone will run into later.

## What the tool will not do for you

- It will not score anything outside `hills eval`.
- It will not evaluate your uncommitted edits to a hill. `hills eval` runs the
  committed version. A dirty hill is an error.
- It will not give credit for a checkpoint, log, or JSON file you produced that
  claims a score.
- It will not hide a broken attempts chain. `hills attempts` prints the break.

## Quick reference

```
hills list                                  registered hills
hills describe <name>                       the contract, as JSON: README, params, files
hills eval <dir> -H <name> [-p k=v]         score a submission directory
hills eval <dir> -H <name> --final          test mode, for the final claim
hills attempts <name>                       history for the current version
hills verify <report.json>                  check a signature

hills new <name> [-t circle-packing|nanogpt-10min]
hills check <name>                          manifest + evaluator contract + tests
hills status <name>                         changes since the last commit
hills commit <name> -m "..."                the human runs this
```

`hills eval` prints the report as JSON on stdout and a human summary on stderr.
Exit code 0 means the evaluation ran, not that the submission passed; read
`passed` in the report.
