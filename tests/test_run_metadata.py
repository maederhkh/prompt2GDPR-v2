"""Standalone assert tests for the run-metadata builder."""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from utils.run_metadata import build_run_metadata, _sha256_hex, _git_commit


def test_sha256_hex_is_deterministic_and_8_chars():
    a = _sha256_hex(b"hello world")
    b = _sha256_hex(b"hello world")
    assert a == b, "same bytes must hash to the same value"
    assert len(a) == 8, f"expected 8 hex chars, got {len(a)}: {a!r}"
    assert all(c in "0123456789abcdef" for c in a), f"not lowercase hex: {a!r}"


def test_sha256_hex_changes_with_content():
    assert _sha256_hex(b"hello world") != _sha256_hex(b"hello worle"), \
        "a one-byte change must change the hash"


def test_git_commit_shape():
    gc = _git_commit()
    assert isinstance(gc, dict)
    assert set(gc.keys()) == {"sha", "dirty"}
    assert isinstance(gc["sha"], str)
    assert gc["dirty"] is None or isinstance(gc["dirty"], bool)


def test_build_run_metadata_keys_and_types():
    md = build_run_metadata(
        policy_path=Path(__file__),       # a real file with bytes to hash
        temperature=0,
        blind_enabled=True,
        clause_count=71,
    )
    assert set(md.keys()) == {
        "run_id", "utc_timestamp", "git_commit", "policy_file",
        "policy_sha256", "temperature", "blind_enabled", "clause_count",
    }
    # run_id is a compact UTC timestamp: YYYYMMDDTHHMMSSZ
    assert re.fullmatch(r"\d{8}T\d{6}Z", md["run_id"]), md["run_id"]
    # utc_timestamp is ISO-8601 ending in Z
    assert md["utc_timestamp"].endswith("Z")
    # both come from the same instant: run_id is the timestamp with separators stripped
    compact = md["utc_timestamp"].replace("-", "").replace(":", "")
    assert md["run_id"] == compact, (md["run_id"], md["utc_timestamp"])
    assert isinstance(md["git_commit"], dict)
    assert md["policy_file"] == "test_run_metadata.py"
    assert len(md["policy_sha256"]) == 8
    assert md["temperature"] == 0
    assert md["blind_enabled"] is True
    assert md["clause_count"] == 71


if __name__ == "__main__":
    test_sha256_hex_is_deterministic_and_8_chars()
    test_sha256_hex_changes_with_content()
    test_git_commit_shape()
    test_build_run_metadata_keys_and_types()
    print("OK")
