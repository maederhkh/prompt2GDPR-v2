"""Standalone assert tests for the batch comparison renderers."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.batch_comparison import (
    build_comparison_csv_rows,
    build_comparison_md,
    HEADERS,
)


def _ok_entry():
    return {
        "policy": "policy_short",
        "run_index": 1,
        "status": "ok",
        "row": {
            "run_id": "20260622T101500Z",
            "overall_label": "Compliant",
            "confidence": "high",
            "clauses": 6,
            "disputed": 1,
            "retries": 0,
            "agreement_rate": 0.9,
        },
        "error": None,
    }


def _empty_entry():
    # build_index_row on an empty result: labels are "N/A", counts are numbers.
    return {
        "policy": "policy_blank",
        "run_index": 1,
        "status": "empty",
        "row": {
            "run_id": "20260622T101600Z",
            "overall_label": "N/A",
            "confidence": "N/A",
            "clauses": 0,
            "disputed": 0,
            "retries": 0,
            "agreement_rate": "N/A",
        },
        "error": "No verified clauses.",
    }


def _failed_entry():
    return {
        "policy": "policy_broken",
        "run_index": 1,
        "status": "failed",
        "row": None,
        "error": "could not read PDF",
    }


def test_csv_rows_header_and_count():
    entries = [_ok_entry(), _empty_entry(), _failed_entry()]
    rows = build_comparison_csv_rows(entries)
    assert rows[0] == HEADERS, rows[0]
    assert len(rows) == 1 + 3            # header + one row per entry
    # ok row: policy, run, status, then metrics
    assert rows[1][:3] == ["policy_short", "1", "ok"], rows[1]
    assert "Compliant" in rows[1]
    assert "0.9" in rows[1]


def test_missing_metrics_render_em_dash():
    rows = build_comparison_csv_rows([_empty_entry(), _failed_entry()])
    empty_row, failed_row = rows[1], rows[2]
    # "N/A" label/confidence/agreement become em dash; numeric 0 stays "0".
    assert "—" in empty_row                       # from N/A cells
    assert "0" in empty_row                        # clauses/disputed/retries = 0
    assert empty_row[3] == "—"                     # overall_label column
    # failed entry has no row -> all metric cells are em dash
    assert failed_row[:3] == ["policy_broken", "1", "failed"], failed_row
    assert failed_row[3:] == ["—"] * (len(HEADERS) - 3), failed_row


def test_md_has_title_label_and_one_row_per_entry():
    entries = [_ok_entry(), _empty_entry(), _failed_entry()]
    md = build_comparison_md(entries, batch_label="20260622T101500Z")
    assert "20260622T101500Z" in md                # batch label in the title
    assert "| " + " | ".join(HEADERS) + " |" in md  # header row present
    # one data row per entry (count the policy names)
    assert md.count("policy_short") == 1
    assert md.count("policy_blank") == 1
    assert md.count("policy_broken") == 1


if __name__ == "__main__":
    test_csv_rows_header_and_count()
    test_missing_metrics_render_em_dash()
    test_md_has_title_label_and_one_row_per_entry()
    print("OK")
