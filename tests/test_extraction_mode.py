"""Standalone assert tests for the extractor's extraction_mode flag.

Uses a minimal fake OpenAI-style client (no network). The Scout call uses
SCOUT_SYSTEM; section-extraction and single-pass use EXTRACTOR_SYSTEM, so the
fake routes on the system message. The two-pass policy is crafted so the single
content paragraph is fully covered by the returned clause quote — the self-check
then finds no uncovered paragraphs and makes no further LLM calls.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from prompts.scout_prompt import SCOUT_SYSTEM, build_scout_prompt
from agents.extractor import run_extractor


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Completions:
    def __init__(self, parent):
        self._p = parent

    def create(self, model=None, max_tokens=None, messages=None):
        system = messages[0]["content"]
        if system == SCOUT_SYSTEM:
            if isinstance(self._p.scout_sections, dict):
                body = self._p.scout_sections
            else:
                body = {"relevant_sections": self._p.scout_sections}
        else:
            body = {
                "policy_name": "P",
                "extracted_clauses": self._p.clauses,
                "extraction_notes": None,
                "coverage_complete": True,
            }
        return _Resp(json.dumps(body))


class _Chat:
    def __init__(self, parent):
        self.completions = _Completions(parent)


class FakeClient:
    def __init__(self, scout_sections, clauses):
        self.scout_sections = scout_sections
        self.clauses = clauses
        self.chat = _Chat(self)


_PARAGRAPH = (
    "We use your personal data only for the stated purposes and never for "
    "incompatible secondary purposes."
)

_ANALYTICS_PARAGRAPH = (
    "We use analytics data to understand service performance and improve "
    "features for statistical purposes."
)


def test_single_pass_mode():
    # Scout returns no sections -> single-pass fallback.
    client = FakeClient(
        scout_sections=[],
        clauses=[{
            "clause_id": "C1",
            "quote": _PARAGRAPH,
            "section_reference": "Data Use",
            "relevance_type": "stated_purpose",
        }],
    )
    result = run_extractor(client, "P", "Some policy text.", model="x", scout_model="y")
    assert result["extraction_mode"] == "single_pass", result.get("extraction_mode")


def test_two_pass_mode():
    # Scout returns a heading present in the policy text -> two-pass.
    policy_text = f"Data Use\n\n{_PARAGRAPH}"
    client = FakeClient(
        scout_sections=["Data Use"],
        clauses=[{
            "clause_id": "C1",
            "quote": _PARAGRAPH,                 # == the paragraph -> covered, no self-check calls
            "section_reference": "Data Use",
            "relevance_type": "stated_purpose",
        }],
    )
    result = run_extractor(client, "P", policy_text, model="x", scout_model="y")
    assert result["extraction_mode"] == "two_pass", result.get("extraction_mode")
    assert "sections_processed" in result


def test_structured_scout_report_is_preserved():
    policy_text = (
        f"Data Use\n\n{_PARAGRAPH}\n\n"
        f"Analytics\n\n{_ANALYTICS_PARAGRAPH}"
    )
    client = FakeClient(
        scout_sections={
            "include": [{
                "heading": "Data Use",
                "reason": "Contains stated processing purposes.",
                "signals": ["processing purposes"],
                "confidence": "high",
            }],
            "maybe_include": [{
                "heading": "Analytics",
                "reason": "May describe statistical purposes.",
                "signals": ["analytics"],
                "confidence": "medium",
            }],
            "exclude": [{
                "heading": "Contact",
                "reason": "Administrative only.",
                "signals": [],
                "confidence": "medium",
            }],
        },
        clauses=[{
            "clause_id": "C1",
            "quote": _PARAGRAPH,
            "section_reference": "Data Use",
            "relevance_type": "stated_purpose",
        }, {
            "clause_id": "C2",
            "quote": _ANALYTICS_PARAGRAPH,
            "section_reference": "Analytics",
            "relevance_type": "purpose_statement",
        }],
    )
    result = run_extractor(client, "P", policy_text, model="x", scout_model="y")
    assert result["extraction_mode"] == "two_pass"
    assert result["sections_processed"] == ["Data Use", "Analytics"]
    assert result["scout_report"]["schema_version"] == "section_decisions_v1"
    assert result["scout_report"]["include"][0]["heading"] == "Data Use"
    assert result["scout_report"]["maybe_include"][0]["heading"] == "Analytics"
    assert result["scout_report"]["exclude"][0]["heading"] == "Contact"


def test_empty_structured_scout_output_falls_back_to_single_pass():
    client = FakeClient(
        scout_sections={"include": [], "maybe_include": [], "exclude": []},
        clauses=[{
            "clause_id": "C1",
            "quote": _PARAGRAPH,
            "section_reference": "Data Use",
            "relevance_type": "stated_purpose",
        }],
    )
    result = run_extractor(client, "P", "Some policy text.", model="x", scout_model="y")
    assert result["extraction_mode"] == "single_pass"


def test_scout_prompt_requests_auditable_decisions():
    prompt = build_scout_prompt("Data Use\n\nWe use data for account services.")
    for expected in ["include", "maybe_include", "exclude", "reason", "signals", "confidence"]:
        assert expected in prompt


if __name__ == "__main__":
    test_single_pass_mode()
    test_two_pass_mode()
    test_structured_scout_report_is_preserved()
    test_empty_structured_scout_output_falls_back_to_single_pass()
    test_scout_prompt_requests_auditable_decisions()
    print("OK")
