"""One canonical JSON encoding, used everywhere a hash or signature is taken."""

import json


def canonical_bytes(obj) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def dumps(obj) -> str:
    """Human-readable JSON for files and stdout."""
    return json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False)
