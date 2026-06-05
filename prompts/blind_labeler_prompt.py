"""
Prompt for the Blind Labeler.

The Blind Labeler assigns a purpose-limitation compliance label to each clause
using the SAME rubric as the Evaluator, but it never sees the Evaluator's output.
This produces an unanchored ("blind") label for the anchoring measurement.

It has access to the same legal-reference tool as the Evaluator so that tool
access is not a confound between labelers.
"""

from prompts.rubric import RUBRIC_BLOCK

BLIND_LABELER_SYSTEM = """\
You are a senior GDPR legal analyst specialising in Article 5(1)(b) — the purpose \
limitation principle. You assign a compliance label to each clause using rigorous, \
evidence-based legal reasoning grounded in the exact clause text provided. You do not \
make assumptions about what the policy might say elsewhere.

You have access to a legal reference tool. Use primary sources (GDPR articles and \
recitals) first; use secondary sources only if primary sources are insufficient. \
Do not call the same reference twice.

You are labeling independently. No other analyst's assessment is provided to you, \
and you must form your own judgment solely from the clause text and the rubric."""

BLIND_LABELER_USER_TEMPLATE = """\
## Your task
Assign a purpose-limitation compliance label to each clause below, using the rubric.

Before labeling, retrieve the legal sources you need using the get_legal_reference \
tool. At minimum, retrieve article_5_1b.

---

{rubric_block}

---

## Clauses to label
{clauses_json}

---

## Output format
Return ONLY valid JSON matching this exact schema. No prose, no markdown, no explanation.

{{
  "labels": [
    {{ "clause_id": "C1", "label": "Compliant|Partially Compliant|Non-Compliant" }}
  ]
}}

Include exactly one entry per clause provided. Use only the three permitted label values.
"""


def build_blind_labeler_prompt(verified_clauses: list[dict]) -> str:
    """Return the formatted user prompt for the Blind Labeler."""
    import json
    clauses_for_prompt = [
        {k: v for k, v in c.items()
         if k in ("clause_id", "quote", "section_reference", "relevance_type")}
        for c in verified_clauses
    ]
    return BLIND_LABELER_USER_TEMPLATE.format(
        rubric_block=RUBRIC_BLOCK,
        clauses_json=json.dumps(clauses_for_prompt, indent=2, ensure_ascii=False),
    )
