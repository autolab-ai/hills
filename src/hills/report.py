"""Report envelopes: identity, provenance, signature, and how reports rank.

Hill authors produce the core (passed / metrics / config / details). Everything
here is added by the tool.
"""

import hmac
import json
import os
import secrets
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from hills import paths
from hills.canonical import canonical_bytes
from hills.errors import HillsError
from hills.hashing import tool_hash

REPORT_VERSION = 1
SIGNATURE_PREFIX = "hmac-sha256:"


def machine_key() -> bytes:
    """The per-machine signing key, created on first use outside any project."""
    path = paths.key_path()
    if not path.is_file():
        paths.ensure_home()
        path.write_text(secrets.token_hex(32) + "\n")
        path.chmod(0o600)
    return bytes.fromhex(path.read_text().strip())


def mac(payload: bytes) -> str:
    return hmac.new(machine_key(), payload, "sha256").hexdigest()


def sign(report: dict) -> str:
    unsigned = {key: value for key, value in report.items() if key != "signature"}
    return SIGNATURE_PREFIX + mac(canonical_bytes(unsigned))


def verify(report: dict) -> bool:
    signature = report.get("signature")
    if not isinstance(signature, str) or not signature.startswith(SIGNATURE_PREFIX):
        return False
    return hmac.compare_digest(signature, sign(report))


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def submission_git(directory: Path) -> str | None:
    """branch@short-sha when the submission is a git checkout, +dirty if modified."""
    def git(*args: str) -> str | None:
        result = subprocess.run(
            ["git", *args], cwd=directory, capture_output=True, text=True
        )
        return result.stdout.strip() if result.returncode == 0 else None

    if git("rev-parse", "--is-inside-work-tree") != "true":
        return None
    short = git("rev-parse", "--short", "HEAD")
    if not short:
        return None
    branch = git("rev-parse", "--abbrev-ref", "HEAD") or "HEAD"
    suffix = "+dirty" if git("status", "--porcelain") else ""
    return f"{branch}@{short}{suffix}"


def build(
    *,
    hill_name: str,
    tree_hash: str | None,
    commit: str | None,
    submission_hash: str,
    submission_git_label: str | None,
    core: dict,
    params: dict,
    final: bool,
    official: bool,
    official_reason: str | None,
    tool_version: str,
) -> dict:
    report = {
        "hill": hill_name,
        "tree_hash": tree_hash,
        "commit": commit,
        "submission_hash": submission_hash,
        "submission_git": submission_git_label,
        "passed": core["passed"],
        "config": core["config"],
        "metrics": core["metrics"],
        "details": core["details"],
        "params": params,
        "final": final,
        "official": official,
        "official_reason": official_reason,
        "tool": {"version": tool_version, "sha256": tool_hash()},
        "timestamp": now_utc(),
        "report_version": REPORT_VERSION,
    }
    report["signature"] = sign(report)
    return report


# -- comparison --------------------------------------------------------------


def comparability_key(report: dict) -> tuple:
    """Two reports are comparable when their primary config entries match."""
    primary = [
        (entry["name"], entry["value"])
        for entry in report.get("config", [])
        if entry.get("primary")
    ]
    return (report.get("final", False), tuple(sorted(primary)))


def comparability_label(key: tuple) -> str:
    final, primary = key
    label = "  ".join(f"{name}={value}" for name, value in primary) or "(no primary config)"
    return label + ("   [--final]" if final else "")


def rank_key(report: dict) -> tuple:
    """Lexicographic in the evaluator's own metric order; direction-aware."""
    return tuple(
        metric["value"] if metric["direction"] == "min" else -metric["value"]
        for metric in report["metrics"]
    )


def rank(reports: list[dict]) -> dict[tuple, list[dict]]:
    """Group passing reports by comparability, best first inside each group."""
    groups: dict[tuple, list[dict]] = {}
    for report in reports:
        if not report.get("passed"):
            continue
        groups.setdefault(comparability_key(report), []).append(report)
    for group in groups.values():
        group.sort(key=rank_key)
    return groups


def read(path: Path) -> dict:
    if not Path(path).is_file():
        raise HillsError(f"no report at {path}")
    return json.loads(Path(path).read_text())


def key_exists() -> bool:
    return paths.key_path().is_file() and os.access(paths.key_path(), os.R_OK)
