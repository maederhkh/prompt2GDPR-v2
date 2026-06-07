"""
Run-metadata builder.

Assembles a small provenance block stamped onto every pipeline result so any
output can be traced back to WHEN it ran (utc_timestamp / run_id), WHICH code
version produced it (git_commit), and WHICH exact input it read (policy_sha256).

Pure stdlib. The git lookup degrades gracefully — metadata must never crash a run.
"""

import datetime
import hashlib
import subprocess
from pathlib import Path


def _sha256_hex(data: bytes) -> str:
    """Return the first 8 hex chars of the SHA-256 of `data`."""
    return hashlib.sha256(data).hexdigest()[:8]


def _git_commit() -> dict:
    """
    Return {"sha": <short hash>, "dirty": <bool>} for the current HEAD.

    Degrades to {"sha": "unknown", "dirty": None} if git is unavailable or this
    is not a git repository. Never raises.
    """
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if sha.returncode != 0:
            return {"sha": "unknown", "dirty": None}
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=5,
        )
        dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
        return {"sha": sha.stdout.strip(), "dirty": dirty}
    except Exception:
        return {"sha": "unknown", "dirty": None}


def build_run_metadata(
    policy_path: Path,
    temperature,
    blind_enabled: bool,
    clause_count: int,
) -> dict:
    """
    Build the run_metadata provenance block.

    Args:
        policy_path: Path to the policy file that was analyzed.
        temperature: The label-producing sampling temperature (config.LABELER_TEMPERATURE).
        blind_enabled: Whether the Blind Labeler tier ran this run.
        clause_count: Number of verified clauses evaluated this run.

    Returns:
        A dict with keys: run_id, utc_timestamp, git_commit, policy_file,
        policy_sha256, temperature, blind_enabled, clause_count.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    return {
        "run_id": now.strftime("%Y%m%dT%H%M%SZ"),
        "utc_timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": _git_commit(),
        "policy_file": policy_path.name,
        "policy_sha256": _sha256_hex(policy_path.read_bytes()),
        "temperature": temperature,
        "blind_enabled": blind_enabled,
        "clause_count": clause_count,
    }
