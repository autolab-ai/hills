"""Per-device locks.

When a hill's metric is a physical measurement on shared hardware, two official
runs at once corrupt both. A hill declares `exclusive: gpu` in its manifest and
the tool serializes on that device for the duration of the evaluation.
"""

import fcntl
import os
import re
import sys
from contextlib import contextmanager

from hills import paths
from hills.errors import DeviceBusy


def resolve_device(exclusive: str) -> str:
    """Turn a manifest device class into the concrete device being contended for."""
    if exclusive != "gpu":
        return exclusive
    visible = os.environ.get("CUDA_VISIBLE_DEVICES", "").strip()
    index = visible.split(",")[0].strip() if visible else "0"
    return f"gpu:{index or '0'}"


@contextmanager
def hold(device: str | None, queue: bool):
    if device is None:
        yield None
        return

    paths.locks_root().mkdir(parents=True, exist_ok=True)
    lock_file = paths.locks_root() / (re.sub(r"[^A-Za-z0-9_.-]", "_", device) + ".lock")
    with open(lock_file, "a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.seek(0)
            holder = handle.read().strip() or "another process"
            if not queue:
                raise DeviceBusy(
                    f"device {device} is busy with another official eval ({holder}). "
                    "Wait for it, or pass --queue to wait in line."
                ) from None
            print(f"hills: waiting for {device} (held by {holder})", file=sys.stderr)
            fcntl.flock(handle, fcntl.LOCK_EX)

        handle.seek(0)
        handle.truncate()
        handle.write(f"pid {os.getpid()}\n")
        handle.flush()
        try:
            yield device
        finally:
            handle.seek(0)
            handle.truncate()
            handle.flush()
            fcntl.flock(handle, fcntl.LOCK_UN)
