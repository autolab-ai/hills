"""Run a subprocess, tee its output to a log, and kill the whole group on timeout.

Shared by the uv path (``uvenv``) and the container path (``runtime``) so both
stream, log, and reap identically.
"""

import contextlib
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path


def stream_run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict | None = None,
    timeout: float | None = None,
    log_path: Path | None = None,
    stream: bool = False,
) -> tuple[int, str]:
    """Run ``argv``, returning (exit code, combined output).

    A timeout kills the whole process group and re-raises ``TimeoutExpired``.
    """
    process = subprocess.Popen(
        argv,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    chunks: list[bytes] = []
    sink = open(log_path, "wb") if log_path else None

    def pump() -> None:
        for line in process.stdout:
            chunks.append(line)
            if sink:
                sink.write(line)
                sink.flush()
            if stream:
                sys.stderr.buffer.write(line)
                sys.stderr.buffer.flush()

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()

    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        terminate_group(process)
        reader.join(timeout=5)
        if sink:
            sink.close()
        raise
    finally:
        reader.join(timeout=10)
        if sink and not sink.closed:
            sink.close()

    return process.returncode, b"".join(chunks).decode("utf-8", "replace")


def terminate_group(process: subprocess.Popen) -> None:
    """Kill the process AND its whole group: SIGTERM, a grace period, then
    SIGKILL any survivors — regardless of whether the group leader already
    exited. Returning as soon as the leader dies (the old behavior) left
    children that ignore SIGTERM, or that the leader spawned, running. The group
    id is captured up front so a leader that exits mid-way can't hide it."""
    try:
        pgid = os.getpgid(process.pid)
    except ProcessLookupError:
        return

    def _sig(sig: int) -> None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(pgid, sig)

    _sig(signal.SIGTERM)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=5)
    # KILL any process still in the group, even if the leader already exited.
    _sig(signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=5)
