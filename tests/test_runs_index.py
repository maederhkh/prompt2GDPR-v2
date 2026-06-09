"""Standalone assert tests for the runs index builder."""
import csv as _csv
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.runs_index import build_index_row, append_run_to_index, FIELDS


def _full_result():
    return {
        "policy_name": "policy_short",
        "run_metadata": {
            "run_id": "20260607T143022Z",
            "utc_timestamp": "2026-06-07T14:30:22Z",
            "policy_file": "policy_short.txt",
            "policy_sha256": "a1b2c3d4",
            "git_commit": {"sha": "cac701e", "dirty": True},
            "clause_count": 68,
            "blind_enabled": True,
        },
        "finalizer_output": {"overall_label": "Partially compliant", "confidence": "low"},
        "final_reflector_output": {"agreement_rate": 0.86},
        "retry_count": 1,
        "verified_clauses": [1] * 68,
        "label_panel": {
            "disputed_count": 26,
            "anchoring_summary": {
                "reflector_a": {"shift_rate": 0.35},
                "reflector_b": {"shift_rate": 0.37},
            },
        },
    }


def _empty_result():
    # Mirrors _empty_result() in main.py: no finalizer/label_panel, clause_count 0.
    return {
        "policy_name": "policy_short",
        "run_metadata": {
            "run_id": "20260101T000000Z",
            "policy_file": "policy_short.txt",
            "policy_sha256": "deadbeef",
            "git_commit": {"sha": "abc1234", "dirty": False},
            "clause_count": 0,
            "blind_enabled": False,
        },
        "error": "No verified clauses.",
        "extractor_output": {},
        "flagged_clauses": [],
    }


def test_build_index_row_full():
    row = build_index_row(_full_result())
    # exact field order matches FIELDS
    assert list(row.keys()) == FIELDS, list(row.keys())
    assert row["run_id"] == "20260607T143022Z"
    assert row["date"] == "2026-06-07 14:30 UTC"
    assert row["policy"] == "policy_short.txt"
    assert row["policy_sha256"] == "a1b2c3d4"
    assert row["commit"] == "cac701e (dirty)"
    assert row["overall_label"] == "Partially compliant"
    assert row["confidence"] == "low"
    assert row["clauses"] == 68
    assert row["agreement_rate"] == 0.86
    assert row["retries"] == 1
    assert row["disputed"] == 26
    assert row["blind"] == "on"
    assert row["anchoring_a"] == 0.35
    assert row["anchoring_b"] == 0.37


def test_build_index_row_empty_result():
    row = build_index_row(_empty_result())
    assert list(row.keys()) == FIELDS
    assert row["run_id"] == "20260101T000000Z"
    assert row["date"] == "N/A"
    assert row["clauses"] == 0
    assert row["overall_label"] == "N/A"
    assert row["confidence"] == "N/A"
    assert row["agreement_rate"] == "N/A"
    assert row["disputed"] == 0
    assert row["blind"] == "off"
    assert row["commit"] == "abc1234"        # no (dirty) suffix
    assert row["anchoring_a"] == "—"     # em dash
    assert row["anchoring_b"] == "—"


def test_append_newest_first():
    d = Path(tempfile.mkdtemp())
    try:
        append_run_to_index(_empty_result(), d)   # run_id ...0000Z (appended first)
        append_run_to_index(_full_result(), d)     # run_id ...3022Z (appended last)

        csv_path = d / "runs_index.csv"
        md_path = d / "runs_index.md"
        assert csv_path.exists() and md_path.exists()

        with csv_path.open(encoding="utf-8") as f:
            rows = list(_csv.reader(f))
        assert rows[0] == FIELDS                    # one header
        assert len(rows) == 3                        # header + 2 data rows
        assert rows[1][0] == "20260607T143022Z"     # newest (last appended) on top
        assert rows[2][0] == "20260101T000000Z"     # older below

        md = md_path.read_text(encoding="utf-8")
        assert md.count("| Run ID |") == 1          # header table row appears once
        assert "20260101T000000Z" in md and "20260607T143022Z" in md
    finally:
        shutil.rmtree(d)


def test_schema_mismatch_backs_up():
    d = Path(tempfile.mkdtemp())
    try:
        csv_path = d / "runs_index.csv"
        md_path = d / "runs_index.md"
        # Pre-create an OLD-schema index whose header != current FIELDS.
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(["run_id", "policy", "overall_label"])      # old 3-col header
            w.writerow(["20250101T000000Z", "old.txt", "Compliant"])
        md_path.write_text("# Old index\n", encoding="utf-8")

        append_run_to_index(_full_result(), d)

        # Old files were backed up, not lost.
        assert (d / "runs_index.csv.bak").exists()
        assert (d / "runs_index.md.bak").exists()

        # New CSV uses the current schema and contains only the new run.
        with csv_path.open(encoding="utf-8") as f:
            rows = list(_csv.reader(f))
        assert rows[0] == FIELDS
        assert len(rows) == 2                         # header + 1 new row
        assert rows[1][0] == "20260607T143022Z"
        assert "20250101T000000Z" not in [r[0] for r in rows[1:]]  # old row not carried over
    finally:
        shutil.rmtree(d)


if __name__ == "__main__":
    test_build_index_row_full()
    test_build_index_row_empty_result()
    test_append_newest_first()
    test_schema_mismatch_backs_up()
    print("OK")
