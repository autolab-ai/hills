# nanogpt-10min

Train a byte-level language model for a fixed wall-clock budget and be scored on
a held-out split you never see.

Before the first `hills check`, build the corpus:

```
uv run python prepare_data.py
```

That writes `data/train.bin` (yours to train on) and `private/data/{val,test}.bin`
(held out). The text is synthesized from a seeded generator so the hill is
identical on every machine and needs no network.

## Task

Write `train.py`. The evaluator runs it, kills it at the time limit, and scores
the checkpoint it finds. Lower bits-per-byte on the held-out split wins.

Everything about the model and the optimizer is yours: architecture, width,
depth, schedule, batch size, precision, kernels. The only fixed things are the
budget, the data you may train on, and how the metric is computed.

## Submission format

A submission is a **directory** containing at least:

```
train.py
```

The evaluator invokes it as:

```
python train.py --data <hill>/data/train.bin --out <workdir>/checkpoints/
```

with the working directory set to your submission, using the hill's own Python
environment (see `pyproject.toml`). Anything else in the directory is yours:
modules, configs, custom kernels.

`train.py` must leave a checkpoint at `<out>/final.pt`:

- saved with `torch.jit.save`, loadable with `torch.jit.load`
- callable as `logits = model(idx)` where `idx` is `int64` of shape `(B, 512)`
- returning float logits of shape `(B, 512, V)` with `V >= 256`

**Your process is killed at the deadline with no warning.** Write the checkpoint
periodically, and write it atomically (save to a temp path, then `os.replace`),
or a kill mid-save will leave you with nothing to score. The example submission
in `examples/baseline/` does exactly this in ten lines.

## Metric

| metric    | direction | meaning                                      |
|-----------|-----------|----------------------------------------------|
| `val_bpb` | min       | bits per byte on the held-out split          |

The evaluator computes it itself: non-overlapping windows of 512 tokens over
every byte of the split, teacher-forced cross-entropy in fp32, summed and
divided by `ln 2` times the number of predicted bytes. One token is one byte, so
bits-per-byte and bits-per-token are the same number. A uniform model scores
8.0.

With `--final` the same computation runs against `private/data/test.bin`
instead. Use it for the final claim, not for iteration.

## Configuration and comparability

| entry          | primary | why                                              |
|----------------|---------|--------------------------------------------------|
| `gpu`          | yes     | a wall-clock budget means a different accelerator is a different task |
| `time_limit_s` | yes     | 300 seconds and 600 seconds are different games   |
| `mode`         | yes     | validation and test scores never rank together    |
| `torch`        | no      | informational                                     |
| `context`      | no      | fixed by the hill at 512                          |
| `model_params` | no      | reported so scaling is visible in the record      |

Reports only rank against reports with the same primary tuple.

## Parameters

| param          | default | meaning                                |
|----------------|---------|-----------------------------------------|
| `time_limit_s` | 600     | seconds of wall clock for `train.py`    |

```
hills eval ./my-run -H nanogpt-10min
hills eval ./my-run -H nanogpt-10min -p time_limit_s=300
hills eval ./my-run -H nanogpt-10min --final
```

Because the metric is a measurement on one accelerator, official evals of this
hill serialize on the device. A second eval fails fast, or waits with `--queue`.

## Feedback you get back

Every report includes the last 40 lines of your training log, the wall clock
actually consumed, whether you were killed at the limit, your exit code, and
your parameter count. Instrument `train.py` however you like: it is an ordinary
process and its stdout comes back to you.

## What the evaluator will not do

- It will not read a loss your code computed. It loads your checkpoint and
  computes bits-per-byte itself.
- It will not let your code run the clock. The deadline is enforced by the
  evaluator's own timer around your process.
- It will not score a checkpoint that is missing, unloadable, or the wrong
  shape. Those are failed attempts, with the reason in `details`.

## Known limits

Model size is not constrained. A larger model trained for the same wall clock is
a legitimate way to win here, and it is recorded as `model_params` in every
report rather than being forbidden.

The evaluator does not sandbox the filesystem. `private/data/` is protected by
convention and by the fact that nothing hands your process its path, not by
enforcement. That is the trust posture of the whole tool: it defends against an
agent grading its own work, not against a human who wants to cheat themselves.
