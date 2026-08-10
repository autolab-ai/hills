"""Evaluator for nanogpt-10min.

The evaluator owns the clock and the metric. It launches the submitted train.py
as a subprocess, kills it at the deadline, and scores whatever checkpoint exists
at that moment against a held-out split the climber never sees.

The climber can read this file. Nothing here reveals the held-out data: the
split lives under private/ and is referenced by path only. Reading it beyond the
header would be pointless anyway -- the metric is computed on every token of it.
"""

import math
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import torch

HILL = Path(__file__).resolve().parent
TRAIN_DATA = HILL / "data" / "train.bin"
VAL_DATA = HILL / "private" / "data" / "val.bin"
TEST_DATA = HILL / "private" / "data" / "test.bin"

# Evaluation is fixed by the hill, not by the submission.
CONTEXT = 512
EVAL_BATCH = 8
LOG_TAIL_LINES = 40


def device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def gpu_profile() -> str:
    """A coarse hardware string. Primary config: scores only compare within it."""
    if torch.cuda.is_available():
        properties = torch.cuda.get_device_properties(0)
        name = properties.name.lower()
        for noise in ("nvidia ", "geforce ", "rtx ", "gtx "):
            name = name.replace(noise, "")
        slug = "".join(char if char.isalnum() else "-" for char in name).strip("-")
        while "--" in slug:
            slug = slug.replace("--", "-")
        return f"{slug}-{round(properties.total_memory / 1024**3)}gb"
    if torch.backends.mps.is_available():
        return "apple-mps"
    return "cpu"


def workdir() -> Path:
    """A fresh directory per evaluation, so no run can be scored on another's
    checkpoint. Placed inside the run directory when there is one, so the author
    can inspect the training output afterwards."""
    parent = Path(os.environ.get("HILLS_RUN_DIR", tempfile.gettempdir()))
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="train-", dir=parent))


def fail(reason: str, config: list[dict], **details) -> dict:
    return {
        "passed": False,
        "metrics": [],
        "config": config,
        "details": {"error": reason, **details},
    }


def run_training(submission: Path, out_dir: Path, time_limit_s: int, log_path: Path) -> dict:
    """Launch the submission and stop it at the deadline. Returns timing facts."""
    command = [
        sys.executable,
        "train.py",
        "--data",
        str(TRAIN_DATA),
        "--out",
        str(out_dir),
    ]
    started = time.perf_counter()
    with open(log_path, "wb") as log:
        process = subprocess.Popen(
            command,
            cwd=submission,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            process.wait(timeout=time_limit_s)
            killed = False
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            process.wait()
            killed = True
    return {
        "elapsed_s": round(time.perf_counter() - started, 1),
        "killed_at_limit": killed,
        "exit_code": process.returncode,
    }


def load_tokens(path: Path) -> torch.Tensor:
    return torch.from_numpy(np.fromfile(path, dtype=np.uint16).astype(np.int64))


@torch.no_grad()
def bits_per_byte(model, tokens: torch.Tensor, target: torch.device) -> tuple[float, int]:
    """Total cross-entropy over non-overlapping windows, in bits per predicted byte."""
    usable = (len(tokens) - 1) // CONTEXT * CONTEXT
    inputs = tokens[:usable].view(-1, CONTEXT)
    targets = tokens[1 : usable + 1].view(-1, CONTEXT)

    total_nats = 0.0
    counted = 0
    for start in range(0, len(inputs), EVAL_BATCH):
        batch_x = inputs[start : start + EVAL_BATCH].to(target)
        batch_y = targets[start : start + EVAL_BATCH].to(target)
        logits = model(batch_x).float()
        if logits.shape[:2] != batch_x.shape:
            raise ValueError(
                f"model returned logits of shape {tuple(logits.shape)}; "
                f"expected ({batch_x.shape[0]}, {batch_x.shape[1]}, vocab)"
            )
        if logits.shape[-1] < 256:
            raise ValueError(
                f"model returned a vocabulary of {logits.shape[-1]}; the corpus is bytes, "
                "so it must be at least 256"
            )
        loss = torch.nn.functional.cross_entropy(
            logits.reshape(-1, logits.shape[-1]), batch_y.reshape(-1), reduction="sum"
        )
        total_nats += loss.item()
        counted += batch_y.numel()
    return total_nats / (math.log(2) * counted), counted


def tail(path: Path) -> str:
    if not path.is_file():
        return ""
    return "\n".join(path.read_text(errors="replace").splitlines()[-LOG_TAIL_LINES:])


def eval(submission: Path, *, final: bool = False, time_limit_s: int = 600) -> dict:
    target = device()
    config = [
        {"name": "gpu", "value": gpu_profile(), "primary": True},
        {"name": "time_limit_s", "value": time_limit_s, "primary": True},
        {"name": "mode", "value": "test" if final else "validation", "primary": True},
        {"name": "torch", "value": torch.__version__, "primary": False},
        {"name": "context", "value": CONTEXT, "primary": False},
    ]

    if not (submission / "train.py").is_file():
        return fail("submission must contain train.py at its root", config)

    work = workdir()
    out_dir = work / "checkpoints"
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = work / "train.log"
    timing = run_training(submission, out_dir, time_limit_s, log_path)

    checkpoint = out_dir / "final.pt"
    if not checkpoint.is_file():
        return fail(
            f"no checkpoint at checkpoints/final.pt after {timing['elapsed_s']}s. "
            "Write it periodically: your process is killed at the deadline.",
            config,
            training=timing,
            train_log_tail=tail(log_path),
        )

    try:
        model = torch.jit.load(checkpoint, map_location=target)
    except (RuntimeError, ValueError) as error:
        return fail(
            f"checkpoints/final.pt is not a loadable TorchScript module: {error}",
            config,
            training=timing,
            train_log_tail=tail(log_path),
        )
    model.eval()

    split = TEST_DATA if final else VAL_DATA
    try:
        bpb, counted = bits_per_byte(model, load_tokens(split), target)
    except (ValueError, RuntimeError) as error:
        return fail(
            f"the checkpoint could not be evaluated: {error}",
            config,
            training=timing,
            train_log_tail=tail(log_path),
        )

    parameters = sum(p.numel() for p in model.parameters())
    config.append({"name": "model_params", "value": parameters, "primary": False})

    return {
        "passed": True,
        "metrics": [{"name": "val_bpb", "value": bpb, "direction": "min"}],
        "config": config,
        "details": {
            "eval_tokens": counted,
            "training": timing,
            "model_params": parameters,
            "train_log_tail": tail(log_path),
        },
    }
