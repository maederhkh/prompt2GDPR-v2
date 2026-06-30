"""Standalone assert tests for the runs summary analyzer."""
import csv as _csv
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.runs_index import FIELDS
from utils.runs_summary import load_index_rows, summarize, build_summary_md, main


def _row(**overrides):
    """One synthetic index row (all 15 fields, as strings, like the CSV)."""
    base = {
        "run_id": "20260611T100000Z",
        "date": "2026-06-11 10:00 UTC",
        "policy": "policy_short.txt",
        "policy_sha256": "abcd1234",
        "commit": "bae249d",
        "overall_label": "Compliant",
        "confidence": "high",
        "clauses": "10",
        "coverage": "high",
        "agreement_rate": "0.9",
        "retries": "0",
        "disputed": "0",
        "blind": "on",
        "anchoring_a": "0.2",
        "anchoring_b": "0.3",
        "duration_s": "31.7",
    }
    base.update(overrides)
    return base


def test_summarize_counts_and_averages():
    rows = [
        _row(),
        _row(run_id="2", date="2026-06-10 09:00 UTC", overall_label="Non-Compliant",
             confidence="low", clauses="20", coverage="low", agreement_rate="0.7",
             retries="2", disputed="3"),
        _row(run_id="3", date="N/A", overall_label="N/A", confidence="N/A",
             clauses="0", coverage="—", agreement_rate="N/A",
             retries="0", disputed="0", anchoring_a="—", anchoring_b="—"),
    ]
    s = summarize(rows)
    assert s["runs"] == 3
    # N/A date excluded from the range, but the run still counts
    assert s["date_range"] == ("2026-06-10 09:00 UTC", "2026-06-11 10:00 UTC")
    assert s["clauses"]["min"] == 0 and s["clauses"]["max"] == 20
    assert s["clauses"]["n"] == 3
    assert s["coverage"] == {"high": 1, "low": 1, "unknown": 1, "fallback_rate": 0.5}
    assert s["labels"]["Compliant"] == 1 and s["labels"]["N/A"] == 1
    assert s["confidence"]["high"] == 1 and s["confidence"]["low"] == 1
    # denominator rule: the N/A agreement cell is excluded -> avg(0.9, 0.7) over 2 of 3
    assert abs(s["agreement"]["avg"] - 0.8) < 1e-9 and s["agreement"]["n"] == 2
    assert s["retry_runs"] == 1            # only run 2 had retries >= 1
    assert s["disputed_runs"] == 1         # only run 2 had disputed >= 1
    assert abs(s["anchoring_a"]["avg"] - 0.2) < 1e-9 and s["anchoring_a"]["n"] == 2


def test_summarize_all_na_column_is_none():
    rows = [_row(agreement_rate="N/A"), _row(run_id="2", agreement_rate="—")]
    s = summarize(rows)
    assert s["agreement"] is None


def test_fallback_rate_none_when_no_judged_runs():
    s = summarize([_row(coverage="—")])
    assert s["coverage"]["fallback_rate"] is None


def test_summarize_empty():
    s = summarize([])
    assert s["runs"] == 0 and s["date_range"] is None and s["clauses"] is None


def test_load_rejects_old_schema():
    d = Path(tempfile.mkdtemp())
    try:
        p = d / "runs_index.csv"
        with p.open("w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(["run_id", "policy"])          # old/unknown header
            w.writerow(["x", "y"])
        try:
            load_index_rows(p)
            assert False, "expected ValueError for old schema"
        except ValueError:
            pass
    finally:
        shutil.rmtree(d)


def test_load_well_formed_csv():
    d = Path(tempfile.mkdtemp())
    try:
        p = d / "runs_index.csv"
        r = _row()
        with p.open("w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(FIELDS)
            w.writerow([r[k] for k in FIELDS])
        rows = load_index_rows(p)
        assert len(rows) == 1
        assert rows[0]["run_id"] == "20260611T100000Z"
        assert rows[0]["coverage"] == "high"
    finally:
        shutil.rmtree(d)


def test_build_summary_md_per_policy():
    rows = [
        _row(policy="b_policy.txt"),
        _row(run_id="2", policy="a_policy.txt", coverage="low"),
    ]
    md = build_summary_md(rows)
    assert md.startswith("# Runs Summary")
    assert "## Overall" in md and "## Per-policy" in md
    # one section per distinct policy, alphabetical order
    ia = md.index("### a_policy.txt")
    ib = md.index("### b_policy.txt")
    assert ia < ib
    # denominator rendered on averages; fallback rate from 1 high / 1 low
    assert "(from 2 of 2 runs)" in md
    assert "fallback rate 50%" in md


def test_build_summary_md_empty():
    md = build_summary_md([])
    assert "0 run(s)" in md
    assert "## Overall" in md
    assert "_No runs recorded yet._" in md


def test_main_end_to_end():
    d = Path(tempfile.mkdtemp())
    try:
        p = d / "runs_index.csv"
        with p.open("w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(FIELDS)
            for r in (_row(), _row(run_id="2", coverage="low", policy="other.txt")):
                w.writerow([r[k] for k in FIELDS])
        rc = main(output_dir=d)
        assert rc == 0
        out = (d / "runs_summary.md").read_text(encoding="utf-8")
        assert "## Overall" in out and "### other.txt" in out
    finally:
        shutil.rmtree(d)


def test_main_missing_index_writes_nothing():
    d = Path(tempfile.mkdtemp())
    try:
        rc = main(output_dir=d)
        assert rc == 0
        assert not (d / "runs_summary.md").exists()
    finally:
        shutil.rmtree(d)


def test_main_old_schema_writes_nothing():
    d = Path(tempfile.mkdtemp())
    try:
        p = d / "runs_index.csv"
        with p.open("w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(["run_id", "policy"])          # old header
        rc = main(output_dir=d)
        assert rc == 0
        assert not (d / "runs_summary.md").exists()
    finally:
        shutil.rmtree(d)


if __name__ == "__main__":
    test_summarize_counts_and_averages()
    test_summarize_all_na_column_is_none()
    test_fallback_rate_none_when_no_judged_runs()
    test_summarize_empty()
    test_load_rejects_old_schema()
    test_load_well_formed_csv()
    test_build_summary_md_per_policy()
    test_build_summary_md_empty()
    test_main_end_to_end()
    test_main_missing_index_writes_nothing()
    test_main_old_schema_writes_nothing()
    print("OK")
