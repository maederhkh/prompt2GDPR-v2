"""Standalone assert tests for the review report renderer."""
import json
import os
import sys
import shutil
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from review_run import default_output_path, main as review_main
from utils.review_report import render_review_report, write_review_report


def _result(**overrides):
    result = {
        "policy_name": "policy_short",
        "run_metadata": {
            "run_id": "20260607T143022Z",
            "utc_timestamp": "2026-06-07T14:30:22Z",
            "policy_file": "policy_short.txt",
            "policy_sha256": "a1b2c3d4",
            "blind_enabled": True,
            "clause_count": 2,
            "git_commit": {"sha": "cac701e", "dirty": True},
        },
        "agent_models": {
            "extractor": "llama-3.3-70b",
            "evaluator": "gpt-4o-mini",
            "reflector_a": "gpt-4o-mini",
            "reflector_b": "gpt-4o-mini",
            "blind_a": "gpt-4o-mini",
            "blind_b": "gpt-4o-mini",
            "finalizer": "gpt-4o-mini",
        },
        "extractor_output": {
            "extraction_mode": "two_pass",
            "coverage_complete": True,
        },
        "verified_clauses": [
            {
                "clause_id": "C1",
                "quote": "We only use your email to send receipts.",
                "relevance_type": "explicit",
            },
            {
                "clause_id": "C2",
                "quote": "We may share data for future research.",
                "relevance_type": "explicit",
            },
        ],
        "flagged_clauses": [],
        "evaluator_output": {
            "overall_label": "Compliant",
            "evaluations": [
                {
                    "clause_id": "C1",
                    "clause_label": "Compliant",
                    "justification": "Clear limited use.",
                    "stage_1": {"specific": True},
                },
                {
                    "clause_id": "C2",
                    "clause_label": "Compliant",
                    "justification": "Research sharing is stated.",
                    "stage_1": {"specific": True},
                },
            ],
            "references_used": [
                {
                    "reference_id": "recital_50",
                    "source_type": "primary",
                    "used_for": "Purpose limitation guidance.",
                }
            ],
            "tools_called": [],
        },
        "reflector_a_initial": {
            "review_status": "clean",
            "errors": [],
            "agreement_rate": 1.0,
            "reflector_notes": "No issues.",
        },
        "reflector_b_initial": {
            "review_status": "clean",
            "errors": [],
            "agreement_rate": 1.0,
            "reflector_notes": "No issues.",
        },
        "final_reflector_output": {
            "review_status": "clean",
            "agreement_rate": 1.0,
            "errors": [],
            "_retries_exhausted": False,
        },
        "retry_count": 0,
        "label_panel": {
            "blind_labeler_enabled": True,
            "per_clause": [
                {
                    "clause_id": "C1",
                    "disputed": False,
                    "evaluator": {"label": "Compliant", "model": "gpt-4o-mini"},
                    "reflector_a": {"label": "Compliant", "model": "gpt-4o-mini"},
                    "reflector_b": {"label": "Compliant", "model": "gpt-4o-mini"},
                    "blind_a": {"label": "Compliant", "model": "gpt-4o-mini"},
                    "blind_b": {"label": "Compliant", "model": "gpt-4o-mini"},
                },
                {
                    "clause_id": "C2",
                    "disputed": False,
                    "evaluator": {"label": "Compliant", "model": "gpt-4o-mini"},
                    "reflector_a": {"label": "Compliant", "model": "gpt-4o-mini"},
                    "reflector_b": {"label": "Compliant", "model": "gpt-4o-mini"},
                    "blind_a": {"label": "Compliant", "model": "gpt-4o-mini"},
                    "blind_b": {"label": "Compliant", "model": "gpt-4o-mini"},
                },
            ],
        },
        "finalizer_output": {
            "overall_label": "Compliant",
            "confidence": "high",
            "unresolved_flags": [],
            "human_review_notes": "No urgent follow-up.",
            "identified_gaps": ["None identified."],
            "key_findings": ["The policy states a limited purpose for processing."],
        },
    }
    result.update(overrides)
    return result


def test_disputed_clause_is_high_priority_and_lists_labels():
    result = _result(
        label_panel={
            "blind_labeler_enabled": True,
            "per_clause": [
                {
                    "clause_id": "C2",
                    "disputed": True,
                    "evaluator": {"label": "Compliant", "model": "gpt-4o-mini"},
                    "reflector_a": {"label": "Partially Compliant", "model": "gpt-4o-mini"},
                    "reflector_b": {"label": "Compliant", "model": "gpt-4o-mini"},
                    "blind_a": {"label": "Non-Compliant", "model": "gpt-4o-mini"},
                    "blind_b": {"label": "Partially Compliant", "model": "gpt-4o-mini"},
                }
            ],
        }
    )
    text = render_review_report(result)
    assert "# Human Review Brief" in text, text
    assert "High | label_panel | C2 | Disputed clause needs human review." in text, text
    assert "## Disputed Clauses" in text, text
    assert "| C2 | Compliant | Partially Compliant | Compliant | Non-Compliant | Partially Compliant |" in text, text
    assert "We may share data for future research." in text, text


def test_flagged_clause_is_high_priority():
    result = _result(
        flagged_clauses=[
            {
                "clause_id": "C9",
                "quote": "A quote that could not be verified.",
                "verification_note": "No close match found.",
            }
        ]
    )
    text = render_review_report(result)
    assert "High | flagged_clauses | C9 | Clause quote failed string-match verification." in text, text
    assert "## Flagged Evidence" in text, text
    assert "No close match found." in text, text
    assert "A quote that could not be verified." in text, text


def test_reflector_errors_render_final_state():
    result = _result(
        retry_count=2,
        final_reflector_output={
            "review_status": "errors_found",
            "agreement_rate": 0.5,
            "_retries_exhausted": True,
            "errors": [
                {
                    "agent": "Reflector A",
                    "clause_id": "C2",
                    "error_type": "grounding_error",
                    "type": "ignored_fallback",
                    "severity": "high",
                    "description": "The clause quote was not grounded in the source text.",
                    "recommendation": "Re-check the clause against the verified quote.",
                }
            ],
        },
    )
    text = render_review_report(result)
    assert "High | reflector | - | Reflector errors remain after retries." in text, text
    assert "Medium | reflector | - | Inter-reflector agreement below 80%." in text, text
    assert "Final merged status: **errors_found**" in text, text
    assert "Retries exhausted: **yes**" in text, text
    assert "| Reflector A | C2 | grounding_error | high | The clause quote was not grounded in the source text. | Re-check the clause against the verified quote. |" in text, text
    assert "The clause quote was not grounded in the source text." in text, text
    assert "Re-check the clause against the verified quote." in text, text


def test_reflector_errors_fall_back_to_type_when_error_type_missing():
    text = render_review_report(
        _result(
            final_reflector_output={
                "review_status": "errors_found",
                "agreement_rate": 1.0,
                "_retries_exhausted": False,
                "errors": [
                    {
                        "agent": "Reflector B",
                        "clause_id": "C7",
                        "type": "coverage_error",
                        "severity": "medium",
                        "description": "The clause was not covered by the verifier.",
                        "recommendation": "Check the extraction coverage for the clause.",
                    }
                ],
            }
        )
    )
    assert "| Reflector B | C7 | coverage_error | medium | The clause was not covered by the verifier. | Check the extraction coverage for the clause. |" in text, text


def test_blind_disabled_notes_anchoring_not_measured():
    result = _result(
        run_metadata={
            "run_id": "20260607T143022Z",
            "utc_timestamp": "2026-06-07T14:30:22Z",
            "policy_file": "policy_short.txt",
            "policy_sha256": "a1b2c3d4",
            "clause_count": 2,
            "git_commit": {"sha": "cac701e", "dirty": False},
        },
        label_panel={
            "blind_labeler_enabled": False,
            "per_clause": [
                {
                    "clause_id": "C1",
                    "disputed": True,
                    "evaluator": {"label": "Compliant", "model": "gpt-4o-mini"},
                    "reflector_a": {"label": "Partially Compliant", "model": "gpt-4o-mini"},
                    "reflector_b": {"label": "Compliant", "model": "gpt-4o-mini"},
                }
            ],
        },
    )
    text = render_review_report(result)
    assert "Medium | label_panel | - | Blind labeler disabled; anchoring was not measured." in text, text
    assert "_Blind labeling disabled for this run; anchoring was not measured._" in text, text
    assert "| Clause | Evaluator | Reflector A | Reflector B | Quote |" in text, text
    assert text.index("_Blind labeling disabled for this run; anchoring was not measured._") < text.index("| Clause | Evaluator | Reflector A | Reflector B | Quote |"), text


def test_empty_items_section_renders_none_without_table_shell():
    text = render_review_report(
        _result(
            finalizer_output={
                "overall_label": None,
                "confidence": "high",
                "unresolved_flags": [],
                "human_review_notes": "No urgent follow-up.",
                "identified_gaps": [],
                "key_findings": [],
            },
            label_panel={"blind_labeler_enabled": True, "per_clause": []},
            flagged_clauses=[],
            final_reflector_output={
                "review_status": "clean",
                "agreement_rate": 1.0,
                "errors": [],
                "_retries_exhausted": False,
            },
            retry_count=0,
        )
    )
    assert "## Items Needing Review\n\n_None._\n\n" in text, text
    assert "## Items Needing Review\n\n| Priority | Source | Clause | Reason |" not in text, text


def test_minimal_older_result_renders_without_crashing():
    text = render_review_report({
        "policy_name": "old_policy",
        "finalizer_output": {"overall_label": "N/A", "confidence": "medium"},
    })
    assert "# Human Review Brief" in text, text
    assert "old_policy" in text, text
    assert "Medium | finalizer | - | Final confidence is medium." in text, text
    assert "## Run Context" in text, text
    assert "_None._" in text, text
    assert "| Blind labeler | N/A |" in text, text


def test_write_review_report_creates_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "review.md"
        write_review_report(_result(), out_path)
        assert out_path.exists(), out_path
        assert out_path.read_text(encoding="utf-8").startswith("# Human Review Brief")


def test_default_output_path_adds_review_suffix():
    path = Path("output/results/sample_run.json")
    assert default_output_path(path) == Path("output/results/sample_run_review.md")


def test_review_run_main_writes_default_output():
    tmp = Path(tempfile.mkdtemp())
    try:
        run_path = tmp / "sample_run.json"
        run_path.write_text(json.dumps(_result()), encoding="utf-8")
        rc = review_main(run_path)
        assert rc == 0
        out = tmp / "sample_run_review.md"
        assert out.exists()
        assert out.read_text(encoding="utf-8").startswith("# Human Review Brief")
    finally:
        shutil.rmtree(tmp)


def test_review_run_main_writes_explicit_override_output():
    tmp = Path(tempfile.mkdtemp())
    try:
        run_path = tmp / "sample_run.json"
        out_path = tmp / "custom" / "brief.md"
        out_path.parent.mkdir()
        run_path.write_text(json.dumps(_result()), encoding="utf-8")
        rc = review_main(run_path, output=out_path)
        assert rc == 0
        assert out_path.exists()
        assert out_path.read_text(encoding="utf-8").startswith("# Human Review Brief")
    finally:
        shutil.rmtree(tmp)


def test_review_run_main_invalid_json_writes_nothing():
    tmp = Path(tempfile.mkdtemp())
    try:
        run_path = tmp / "broken.json"
        run_path.write_text("{not valid json}", encoding="utf-8")
        rc = review_main(run_path)
        assert rc == 0
        assert list(tmp.glob("*_review.md")) == []
    finally:
        shutil.rmtree(tmp)


def test_review_run_main_missing_required_keys_writes_nothing():
    tmp = Path(tempfile.mkdtemp())
    try:
        run_path = tmp / "missing_keys.json"
        run_path.write_text(json.dumps({"policy_name": "policy_short"}), encoding="utf-8")
        rc = review_main(run_path)
        assert rc == 0
        assert list(tmp.glob("*_review.md")) == []
    finally:
        shutil.rmtree(tmp)


def test_review_run_main_missing_file_preserves_input_path_text():
    tmp = Path(tempfile.mkdtemp())
    try:
        missing = "output/results/nonexistent.json"
        out = StringIO()
        with redirect_stdout(out):
            rc = review_main(missing)
        assert rc == 0
        assert out.getvalue().strip() == (
            "Cannot generate review brief: file not found: output/results/nonexistent.json"
        )
        assert list(tmp.glob("*_review.md")) == []
    finally:
        shutil.rmtree(tmp)


def test_review_run_main_bad_input_writes_nothing():
    tmp = Path(tempfile.mkdtemp())
    try:
        rc = review_main(tmp / "missing.json")
        assert rc == 0
        assert list(tmp.glob("*_review.md")) == []
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    test_disputed_clause_is_high_priority_and_lists_labels()
    test_flagged_clause_is_high_priority()
    test_reflector_errors_render_final_state()
    test_reflector_errors_fall_back_to_type_when_error_type_missing()
    test_empty_items_section_renders_none_without_table_shell()
    test_blind_disabled_notes_anchoring_not_measured()
    test_minimal_older_result_renders_without_crashing()
    test_write_review_report_creates_file()
    test_default_output_path_adds_review_suffix()
    test_review_run_main_writes_default_output()
    test_review_run_main_writes_explicit_override_output()
    test_review_run_main_invalid_json_writes_nothing()
    test_review_run_main_missing_required_keys_writes_nothing()
    test_review_run_main_missing_file_preserves_input_path_text()
    test_review_run_main_bad_input_writes_nothing()
    print("OK")
