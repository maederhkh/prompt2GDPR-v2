"""Standalone assert tests for the pure-Python label panel builder."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.label_panel import build_label_panel, annotate_finalizer_with_disputes


def _labels(items):
    return [{"clause_id": cid, "label": lab} for cid, lab in items]


def test_agreement_not_disputed():
    evaluator = {"evaluations": [{"clause_id": "C1", "clause_label": "Compliant"}]}
    refa = {"clause_labels": _labels([("C1", "Compliant")])}
    refb = {"clause_labels": _labels([("C1", "Compliant")])}
    blinda = {"labels": _labels([("C1", "Compliant")])}
    blindb = {"labels": _labels([("C1", "Compliant")])}
    models = {"evaluator": "E", "reflector_a": "Ra", "reflector_b": "Rb",
              "blind_a": "Ra", "blind_b": "Rb"}
    panel = build_label_panel(evaluator, refa, refb, blinda, blindb, models, blind_enabled=True)
    row = panel["per_clause"][0]
    assert row["disputed"] is False
    assert row["evaluator"] == {"label": "Compliant", "model": "E"}
    assert panel["disputed_count"] == 0


def test_single_dissent_is_disputed():
    evaluator = {"evaluations": [{"clause_id": "C1", "clause_label": "Compliant"}]}
    refa = {"clause_labels": _labels([("C1", "Non-Compliant")])}
    refb = {"clause_labels": _labels([("C1", "Compliant")])}
    blinda = {"labels": _labels([("C1", "Compliant")])}
    blindb = {"labels": _labels([("C1", "Compliant")])}
    models = {"evaluator": "E", "reflector_a": "Ra", "reflector_b": "Rb",
              "blind_a": "Ra", "blind_b": "Rb"}
    panel = build_label_panel(evaluator, refa, refb, blinda, blindb, models, blind_enabled=True)
    assert panel["per_clause"][0]["disputed"] is True
    assert panel["disputed_count"] == 1


def test_anchoring_shift_detected():
    # reflector_a (anchored) differs from blind_a (blind) for the same model -> changed
    evaluator = {"evaluations": [{"clause_id": "C1", "clause_label": "Compliant"}]}
    refa = {"clause_labels": _labels([("C1", "Compliant")])}       # anchored: agrees w/ evaluator
    refb = {"clause_labels": _labels([("C1", "Compliant")])}
    blinda = {"labels": _labels([("C1", "Non-Compliant")])}        # blind: disagrees
    blindb = {"labels": _labels([("C1", "Compliant")])}
    models = {"evaluator": "E", "reflector_a": "Ra", "reflector_b": "Rb",
              "blind_a": "Ra", "blind_b": "Rb"}
    panel = build_label_panel(evaluator, refa, refb, blinda, blindb, models, blind_enabled=True)
    row = panel["per_clause"][0]
    assert row["anchoring_shift"]["reflector_a_vs_blind_a"] == "changed"
    assert row["anchoring_shift"]["reflector_b_vs_blind_b"] == "no_change"
    summary = panel["anchoring_summary"]["reflector_a"]
    assert summary["clauses_changed"] == 1
    assert summary["total"] == 1
    assert summary["shift_rate"] == 1.0


def test_blind_disabled_skips_blind_columns():
    evaluator = {"evaluations": [{"clause_id": "C1", "clause_label": "Compliant"}]}
    refa = {"clause_labels": _labels([("C1", "Non-Compliant")])}
    refb = {"clause_labels": _labels([("C1", "Compliant")])}
    models = {"evaluator": "E", "reflector_a": "Ra", "reflector_b": "Rb",
              "blind_a": "Ra", "blind_b": "Rb"}
    panel = build_label_panel(evaluator, refa, refb, None, None, models, blind_enabled=False)
    row = panel["per_clause"][0]
    assert row["blind_a"] is None
    assert row["blind_b"] is None
    assert row["anchoring_shift"] == "not measured (blind labeler disabled)"
    assert panel["blind_labeler_enabled"] is False
    # disputed still computed from evaluator + reflectors
    assert row["disputed"] is True


def test_missing_label_is_null_not_dispute_driver():
    # reflector_b has no label for C1 -> recorded null, not counted as a dissent
    evaluator = {"evaluations": [{"clause_id": "C1", "clause_label": "Compliant"}]}
    refa = {"clause_labels": _labels([("C1", "Compliant")])}
    refb = {"clause_labels": []}  # missing C1
    blinda = {"labels": _labels([("C1", "Compliant")])}
    blindb = {"labels": _labels([("C1", "Compliant")])}
    models = {"evaluator": "E", "reflector_a": "Ra", "reflector_b": "Rb",
              "blind_a": "Ra", "blind_b": "Rb"}
    panel = build_label_panel(evaluator, refa, refb, blinda, blindb, models, blind_enabled=True)
    row = panel["per_clause"][0]
    assert row["reflector_b"] is None
    assert row["disputed"] is False  # all PRESENT labels agree


def test_annotate_finalizer_with_disputes():
    finalizer = {"confidence": "high", "unresolved_flags": []}
    panel = {"per_clause": [{"clause_id": "C1", "disputed": True}], "disputed_count": 1}
    annotate_finalizer_with_disputes(finalizer, panel)
    assert finalizer["confidence"] == "low"
    assert any("C1" in f for f in finalizer["unresolved_flags"])


if __name__ == "__main__":
    test_agreement_not_disputed()
    test_single_dissent_is_disputed()
    test_anchoring_shift_detected()
    test_blind_disabled_skips_blind_columns()
    test_missing_label_is_null_not_dispute_driver()
    test_annotate_finalizer_with_disputes()
    print("OK")
