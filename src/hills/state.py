"""The attempts log: append-only eval history, keyed by tree hash and HMAC-chained.

A changed evaluator is a new game, so a new tree hash starts a fresh history.
Each entry carries the MAC of the previous one, which makes a deleted or edited
line detectable rather than invisible.
"""

import fcntl
import json
from pathlib import Path

from hills import paths, report as report_mod
from hills.canonical import canonical_bytes

ATTEMPTS_FILE = "attempts.jsonl"
DIRTY_KEY = "current"


def state_dir(hill_name: str, tree_hash: str | None) -> Path:
    return paths.state_root() / f"{hill_name}@{tree_hash or DIRTY_KEY}"


def attempts_path(hill_name: str, tree_hash: str | None) -> Path:
    return state_dir(hill_name, tree_hash) / ATTEMPTS_FILE


def chain_mac(entry: dict) -> str:
    return report_mod.mac(canonical_bytes({k: v for k, v in entry.items() if k != "chain"}))


def append(hill_name: str, tree_hash: str | None, entry: dict) -> dict:
    """Append one attempt under a file lock, chained to the entry before it."""
    directory = state_dir(hill_name, tree_hash)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ATTEMPTS_FILE

    with open(path, "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        lines = [line for line in handle.read().splitlines() if line.strip()]
        previous = json.loads(lines[-1]) if lines else None
        record = {
            "seq": (previous["seq"] + 1) if previous else 1,
            "prev": previous["chain"] if previous else "",
            **entry,
        }
        record["chain"] = chain_mac(record)
        handle.seek(0, 2)
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()
        fcntl.flock(handle, fcntl.LOCK_UN)
    return record


def read(hill_name: str, tree_hash: str | None) -> list[dict]:
    """Every attempt, each annotated with whether its link in the chain holds."""
    path = attempts_path(hill_name, tree_hash)
    if not path.is_file():
        return []

    records = []
    expected_prev = ""
    expected_seq = 1
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        intact = (
            record.get("chain") == chain_mac(record)
            and record.get("prev") == expected_prev
            and record.get("seq") == expected_seq
        )
        record["_chain_ok"] = intact
        records.append(record)
        expected_prev = record.get("chain", "")
        expected_seq = record.get("seq", expected_seq) + 1
    return records


def known_tree_hashes(hill_name: str) -> list[str]:
    root = paths.state_root()
    if not root.is_dir():
        return []
    prefix = f"{hill_name}@"
    return sorted(
        entry.name[len(prefix) :]
        for entry in root.iterdir()
        if entry.is_dir() and entry.name.startswith(prefix)
    )
