"""Standalone assert tests for _render_scout_section in the report generator."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.report_generator import _render_scout_section


def _report():
    return {
        "schema_version": "section_decisions_v1",
        "include": [
            {"heading": "3.1 How we use data", "reason": "States processing purposes.",
             "signals": ["processing purposes"], "confidence": "high"},
        ],
        "maybe_include": [
            {"heading": "3.8 Statistics", "reason": "May describe analytics.",
             "signals": ["analytics"], "confidence": "medium"},
        ],
        "exclude": [
            {"heading": "12. Contact us", "reason": "Administrative only.",
             "signals": [], "confidence": "low"},
        ],
    }


def test_full_report_has_heading_counts_and_one_row_per_decision():
    lines = _render_scout_section(_report())
    text = "\n".join(lines)
    assert "### Section Scout" in text, text
    # counts line: 1 included, 1 maybe, 1 excluded
    assert "**1** included" in text and "**1** maybe-include" in text and "**1** excluded" in text, text
    # table header present
    assert "| Section | Decision | Confidence | Reason |" in text, text
    # one data row per decision (3 headings appear)
    assert text.count("3.1 How we use data") == 1
    assert text.count("3.8 Statistics") == 1
    assert text.count("12. Contact us") == 1


def test_grouping_and_decision_labels():
    lines = _render_scout_section(_report())
    text = "\n".join(lines)
    # include row appears before maybe row before exclude row
    i_inc = text.index("3.1 How we use data")
    i_maybe = text.index("3.8 Statistics")
    i_exc = text.index("12. Contact us")
    assert i_inc < i_maybe < i_exc, (i_inc, i_maybe, i_exc)
    # decision labels: include -> "include", maybe_include -> "maybe", exclude -> "exclude"
    assert "| include |" in text, text
    assert "| maybe |" in text, text
    assert "| exclude |" in text, text


def test_pipe_and_newline_in_reason_are_escaped():
    report = {
        "include": [
            {"heading": "A | B", "reason": "first line\nsecond | piped",
             "signals": [], "confidence": "high"},
        ],
        "maybe_include": [],
        "exclude": [],
    }
    lines = _render_scout_section(report)
    text = "\n".join(lines)
    # the raw reason must not introduce a literal newline inside the table region,
    # and pipes inside cells must be escaped to "\|"
    assert "first line second \\| piped" in text, text
    assert "A \\| B" in text, text
    # no decision's content should create an extra unescaped row break:
    # every table data row starts with "| " — count matches the single decision
    data_rows = [ln for ln in lines if ln.startswith("| ") and "Section" not in ln and "---" not in ln]
    assert len(data_rows) == 1, data_rows


def test_empty_or_missing_report_returns_empty_list():
    assert _render_scout_section(None) == []
    assert _render_scout_section({}) == []
    assert _render_scout_section(
        {"include": [], "maybe_include": [], "exclude": []}
    ) == []


if __name__ == "__main__":
    test_full_report_has_heading_counts_and_one_row_per_decision()
    test_grouping_and_decision_labels()
    test_pipe_and_newline_in_reason_are_escaped()
    test_empty_or_missing_report_returns_empty_list()
    print("OK")
