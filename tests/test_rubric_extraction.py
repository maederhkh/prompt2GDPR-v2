"""Verify the evaluator prompt still contains all rubric content after extraction."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from prompts.evaluator_prompt import build_evaluator_prompt

CLAUSES = [{"clause_id": "C1", "quote": "x", "section_reference": "s", "relevance_type": "purpose_statement"}]
rendered = build_evaluator_prompt(CLAUSES)

required_phrases = [
    "## Two-stage rubric",
    "Stage 1 — Purpose Specification",
    "determined_at_collection",
    "Stage 2 — Compatibility Assessment",
    "Article 89 Exception Branch",
    "no other labels are permitted",
    "Criterion answer values",
    '"yes", "no", or "partial"',
    "{",  # the JSON schema braces must still be present below the rubric
]
for phrase in required_phrases:
    assert phrase in rendered, f"MISSING after extraction: {phrase!r}"

print("OK")
