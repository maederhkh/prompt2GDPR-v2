"""Standalone assert tests for _render_usage_section in the report generator."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.report_generator import _render_usage_section


def _usage():
    return {
        "calls": [],  # not read by the renderer
        "by_stage": [
            {"stage": "extractor", "calls": 4, "prompt_tokens": 10000,
             "completion_tokens": 2400, "total_tokens": 12400, "cost": 0.018},
            {"stage": "evaluator", "calls": 1, "prompt_tokens": 6000,
             "completion_tokens": 2100, "total_tokens": 8100, "cost": None},
        ],
        "totals": {"calls": 5, "prompt_tokens": 16000, "completion_tokens": 4500,
                   "total_tokens": 20500, "cost": 0.018},
    }


def test_full_usage_has_heading_summary_rows_and_total():
    lines = _render_usage_section(_usage())
    text = "\n".join(lines)
    assert "## Token Usage & Cost" in text, text
    assert "| Agent | Calls | Prompt | Completion | Total tokens | Cost (USD) |" in text, text
    assert "5 call(s)" in text, text
    assert "20,500 tokens" in text, text     # totals with thousands separator
    assert "$0.0180" in text, text           # total cost, 4dp
    assert text.count("| extractor |") == 1
    assert text.count("| evaluator |") == 1
    assert "| **TOTAL** |" in text, text


def test_none_cost_renders_dash():
    lines = _render_usage_section(_usage())
    evaluator_row = [ln for ln in lines if ln.startswith("| evaluator |")][0]
    assert "| — |" in evaluator_row, evaluator_row


def test_token_counts_use_thousands_separators():
    lines = _render_usage_section(_usage())
    extractor_row = [ln for ln in lines if ln.startswith("| extractor |")][0]
    assert "12,400" in extractor_row, extractor_row


def test_empty_or_missing_usage_returns_empty_list():
    assert _render_usage_section(None) == []
    assert _render_usage_section({}) == []
    assert _render_usage_section({"by_stage": []}) == []


if __name__ == "__main__":
    test_full_usage_has_heading_summary_rows_and_total()
    test_none_cost_renders_dash()
    test_token_counts_use_thousands_separators()
    test_empty_or_missing_usage_returns_empty_list()
    print("OK")
