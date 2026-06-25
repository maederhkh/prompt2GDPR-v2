"""Standalone assert tests for _render_trace_section in the report generator."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.report_generator import _render_trace_section


def _trace():
    return [
        {"step": 1, "stage": "extractor", "model": "llama-3.3-70b",
         "duration_s": 16.8, "status": "fallback", "note": "single-pass fallback (no Scout)"},
        {"step": 2, "stage": "verifier", "model": None,
         "duration_s": 0.3, "status": "ok", "note": ""},
        {"step": 3, "stage": "evaluator", "model": "gpt-4o-mini",
         "duration_s": 14.6, "status": "ok", "note": ""},
    ]


def test_full_trace_has_heading_summary_and_one_row_per_event():
    lines = _render_trace_section(_trace())
    text = "\n".join(lines)
    assert "## Execution Timeline" in text, text
    assert "| # | Stage | Model | Duration (s) | Status | Note |" in text, text
    assert "3 steps" in text, text          # total step count in summary
    assert "31.7" in text, text             # total duration 16.8+0.3+14.6
    assert "1 fallback" in text, text       # non-ok status surfaced in summary
    # one data row per event
    assert text.count("| extractor |") == 1
    assert text.count("| verifier |") == 1
    assert text.count("| evaluator |") == 1


def test_none_model_renders_dash():
    lines = _render_trace_section(_trace())
    # the verifier row (step 2) has model None -> em dash cell
    verifier_row = [ln for ln in lines if ln.startswith("| 2 |")][0]
    assert "| — |" in verifier_row, verifier_row


def test_pipe_and_newline_in_cells_are_escaped():
    trace = [
        {"step": 1, "stage": "evaluator", "model": "a|b",
         "duration_s": 1.0, "status": "ok", "note": "line1\nline2 | piped"},
    ]
    lines = _render_trace_section(trace)
    text = "\n".join(lines)
    assert "line1 line2 \\| piped" in text, text
    assert "a\\|b" in text, text
    data_rows = [ln for ln in lines if ln.startswith("| 1 |")]
    assert len(data_rows) == 1, data_rows


def test_empty_or_missing_trace_returns_empty_list():
    assert _render_trace_section(None) == []
    assert _render_trace_section([]) == []


if __name__ == "__main__":
    test_full_trace_has_heading_summary_and_one_row_per_event()
    test_none_model_renders_dash()
    test_pipe_and_newline_in_cells_are_escaped()
    test_empty_or_missing_trace_returns_empty_list()
    print("OK")
