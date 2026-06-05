"""
Prompt for Agent 2: Evaluator.

The Evaluator applies a two-stage legal rubric grounded in GDPR Article 5(1)(b),
Recital 39, and Article 89 to assess each verified extracted clause for purpose
limitation compliance.
"""

from prompts.rubric import RUBRIC_BLOCK

EVALUATOR_SYSTEM = """\
You are a senior GDPR legal analyst specialising in Article 5(1)(b) — the purpose \
limitation principle. You assess privacy policy clauses with rigorous, evidence-based \
legal reasoning. Every assessment you make must be directly grounded in the exact \
clause text provided. You do not cite sections that were not provided to you. \
You do not make assumptions about what the policy might say elsewhere.

You have access to a legal reference tool. Use it as follows:
1. Call primary sources first (GDPR articles and recitals — binding law).
2. Call secondary sources (WP29/EDPB opinions) only if primary sources alone are \
insufficient to make a confident assessment.
3. Do not call the same reference twice.
4. In your final JSON output, list every reference you consulted in the \
references_used field."""

EVALUATOR_USER_TEMPLATE = """\
## Your task
Assess each clause below for compliance with GDPR Article 5(1)(b) — purpose limitation — \
using the two-stage rubric defined in this prompt.

Before starting your assessment, retrieve the legal sources you need using the \
get_legal_reference tool. At minimum, retrieve article_5_1b. Retrieve article_89 \
and recital_157 only if any clause has relevance_type "research_exception".

---

{rubric_block}

---

## Clauses to assess
{clauses_json}

---

## Output format
Return ONLY valid JSON matching this exact schema. No prose, no markdown, no explanation.

{{
  "evaluations": [
    {{
      "clause_id": "C1",
      "stage_1": {{
        "specific": "yes|no|partial",
        "explicit": "yes|no|partial",
        "legitimate": "yes|no|partial",
        "determined_at_collection": "yes|no|partial"
      }},
      "stage_2_applicable": false,
      "stage_2": {{
        "purpose_link": "yes|no|partial",
        "context_consistent": "yes|no|partial",
        "data_nature_considered": "yes|no|partial",
        "impact_assessed": "yes|no|partial",
        "safeguards_present": "yes|no|partial"
      }},
      "article_89_exception": false,
      "article_89_assessment": {{
        "exception_explicitly_claimed": "yes|no",
        "safeguards_stated": "yes|no|partial",
        "purpose_genuine": "yes|no|partial"
      }},
      "clause_label": "Compliant|Partially Compliant|Non-Compliant",
      "justification": "2-4 sentences that quote the clause text and link it to \
Article 5(1)(b) wording and/or Recital 39. Be specific — do not write generic GDPR commentary."
    }}
  ],
  "overall_label": "Compliant|Partially Compliant|Non-Compliant",
  "overall_justification": "2-3 sentences explaining how the clause-level labels \
lead to the overall label.",
  "references_used": [
    {{
      "reference_id": "article_5_1b",
      "source_type": "primary|secondary",
      "used_for": "One sentence: which clause(s) and which rubric criterion this reference informed."
    }}
  ]
}}

The references_used list must contain one entry for every reference you retrieved \
via the tool. If you retrieved no references, set it to an empty list [].
"""


def build_evaluator_prompt(verified_clauses: list[dict]) -> str:
    """Return the formatted user prompt for the Evaluator agent."""
    import json
    clauses_for_prompt = [
        {k: v for k, v in c.items()
         if k in ("clause_id", "quote", "section_reference", "relevance_type")}
        for c in verified_clauses
    ]
    return EVALUATOR_USER_TEMPLATE.format(
        rubric_block=RUBRIC_BLOCK,
        clauses_json=json.dumps(clauses_for_prompt, indent=2, ensure_ascii=False),
    )
