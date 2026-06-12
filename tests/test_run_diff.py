"""Standalone assert tests for the run diff tool."""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.run_diff import load_run, clause_labels, match_clauses


def _run(policy="policy_x.txt", overall="Compliant", confidence="high",
         clauses=None, models=None):
    """One synthetic run dict. clauses = list of (clause_id, quote, label);
    label None means the clause gets no assessment (unassessed)."""
    if clauses is None:
        clauses = [("C1", "We process your data to provide the service.", "Compliant")]
    run = {
        "policy_name": policy,
        "verified_clauses": [
            {"clause_id": cid, "quote": quote} for cid, quote, _ in clauses
        ],
        "finalizer_output": {
            "overall_label": overall,
            "confidence": confidence,
            "clause_assessments": [
                {"clause_id": cid, "clause_label": label}
                for cid, _, label in clauses if label is not None
            ],
        },
    }
    if models is not None:
        run["agent_models"] = models
    return run


def test_load_run_valid_and_invalid():
    d = Path(tempfile.mkdtemp())
    try:
        good = d / "run.json"
        good.write_text(json.dumps(_run()), encoding="utf-8")
        data = load_run(good)
        assert data["policy_name"] == "policy_x.txt"

        try:
            load_run(d / "missing.json")
            assert False, "expected ValueError for missing file"
        except ValueError:
            pass

        bad = d / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        try:
            load_run(bad)
            assert False, "expected ValueError for invalid JSON"
        except ValueError:
            pass

        notrun = d / "notrun.json"
        notrun.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
        try:
            load_run(notrun)
            assert False, "expected ValueError for non-run JSON"
        except ValueError:
            pass
    finally:
        shutil.rmtree(d)


def test_clause_labels_join_and_unassessed():
    run = _run(clauses=[
        ("C1", "Quote one.", "Compliant"),
        ("C2", "Quote two.", None),               # verified but never assessed
    ])
    records = clause_labels(run)
    assert len(records) == 2
    assert records[0] == {"clause_id": "C1", "quote": "Quote one.", "label": "Compliant"}
    assert records[1]["label"] == "(unassessed)"


def test_match_exact_fuzzy_and_only():
    a = [
        {"clause_id": "C1", "quote": "We process your data to provide the service.", "label": "Compliant"},
        {"clause_id": "C2", "quote": "Data may be shared with our partners for marketing.", "label": "Non-Compliant"},
        {"clause_id": "C3", "quote": "Only run A has this clause about retention.", "label": "Compliant"},
    ]
    b = [
        # exact match for C1 (different ID on purpose — IDs must not matter)
        {"clause_id": "C9", "quote": "We process your data to provide the service.", "label": "Compliant"},
        # fuzzy match for C2 (trailing period missing)
        {"clause_id": "C8", "quote": "Data may be shared with our partners for marketing", "label": "Compliant"},
        # only in B
        {"clause_id": "C7", "quote": "A completely different clause about cookies and consent banners.", "label": "Compliant"},
    ]
    m = match_clauses(a, b)
    assert len(m["pairs"]) == 2
    paired_a_ids = {ra["clause_id"] for ra, _ in m["pairs"]}
    assert paired_a_ids == {"C1", "C2"}
    assert [r["clause_id"] for r in m["only_a"]] == ["C3"]
    assert [r["clause_id"] for r in m["only_b"]] == ["C7"]


def test_match_is_one_to_one():
    # two identical quotes in A, one in B -> only one pair, the other lands in only_a
    a = [
        {"clause_id": "C1", "quote": "Duplicate quote text.", "label": "Compliant"},
        {"clause_id": "C2", "quote": "Duplicate quote text.", "label": "Compliant"},
    ]
    b = [{"clause_id": "C9", "quote": "Duplicate quote text.", "label": "Compliant"}]
    m = match_clauses(a, b)
    assert len(m["pairs"]) == 1
    assert len(m["only_a"]) == 1
    assert m["only_b"] == []


if __name__ == "__main__":
    test_load_run_valid_and_invalid()
    test_clause_labels_join_and_unassessed()
    test_match_exact_fuzzy_and_only()
    test_match_is_one_to_one()
    print("OK")
