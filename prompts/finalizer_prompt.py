"""
Prompt for Agent 4: Finalizer.

The Finalizer consolidates all upstream outputs into a single structured compliance
report, sets the confidence level, and flags items requiring human expert review.
"""

FINALIZER_SYSTEM = """\
You are a GDPR compliance reporting specialist. Your role is to consolidate the \
outputs of a multi-agent assessment pipeline into a clear, structured, and legally \
sound final compliance report. You accurately represent the findings of the upstream \
agents. You do not add new legal judgements that were not produced by the Evaluator. \
You clearly highlight unresolved issues and items that require human expert review."""

FINALIZER_USER_TEMPLATE = """\
## Your task
Consolidate the outputs from the assessment pipeline below into a single final \
compliance report for GDPR Article 5(1)(b) — Purpose Limitation.

---

## Confidence rules
Set the "confidence" field as follows:
- "high" — Reflector status is "clean", no flagged clauses, all evaluations have \
  strong justifications.
- "medium" — Reflector found errors that were resolved (retry_count > 0 but \
  review_status is "clean"), or 1-2 clauses were flagged by the verifier.
- "low" — Reflector status is "errors_unresolved", or more than 2 clauses were \
  flagged by the verifier and excluded from evaluation.

The field "human_review_recommended" must always be true — human expert review \
is always required before treating this report as authoritative in a legal context.

---

## Pipeline inputs

### Policy name
{policy_name}

### Assessment date
{assessment_date}

### Extractor output (Agent 1)
{extractor_output_json}

### String-match verifier summary
- Verified clauses: {verified_count}
- Flagged (excluded) clauses: {flagged_count}
{flagged_details}

### Evaluator output (Agent 2)
{evaluator_output_json}

### Reflector audit report (Agent 3)
{reflector_output_json}

---

## Output format
Return ONLY valid JSON matching this exact schema. No prose, no markdown, no explanation.

{{
  "policy_name": "<string>",
  "assessment_date": "<YYYY-MM-DD>",
  "principle_assessed": "Article 5(1)(b) — Purpose Limitation",
  "overall_label": "Compliant|Partially Compliant|Non-Compliant",
  "confidence": "high|medium|low",
  "clause_assessments": [
    {{
      "clause_id": "<string>",
      "quote": "<verbatim clause text>",
      "section_reference": "<string or null>",
      "relevance_type": "<string>",
      "clause_label": "Compliant|Partially Compliant|Non-Compliant",
      "justification": "<string>",
      "stage_1_summary": "<one sentence summarising Stage 1 findings>",
      "stage_2_applicable": "<boolean>",
      "stage_2_summary": "<one sentence summarising Stage 2 findings, or null>",
      "article_89_exception": "<boolean>"
    }}
  ],
  "key_findings": [
    "<string — each item is one specific finding about purpose limitation compliance>"
  ],
  "identified_gaps": [
    "<string — each item is one specific gap or deficiency found in the policy>"
  ],
  "unresolved_flags": [
    "<string — each item describes an unresolved error or excluded clause>"
  ],
  "human_review_recommended": true,
  "human_review_notes": "<string — specific items the human expert should verify, \
or 'None' if reflector status is clean and confidence is high>"
}}
"""


def build_finalizer_prompt(
    policy_name: str,
    assessment_date: str,
    extractor_output: dict,
    verified_clauses: list[dict],
    flagged_clauses: list[dict],
    evaluator_output: dict,
    reflector_output: dict,
) -> str:
    """Return the formatted user prompt for the Finalizer agent."""
    import json

    flagged_details = ""
    if flagged_clauses:
        lines = ["Flagged clause details:"]
        for c in flagged_clauses:
            lines.append(
                f"  - {c.get('clause_id', 'unknown')}: {c.get('verification_note', '')}"
            )
        flagged_details = "\n".join(lines)

    # Send a compact extractor summary (not full clause text) to save context tokens.
    # The full clause text is already embedded in the evaluator output.
    extractor_summary = {
        "policy_name": extractor_output.get("policy_name"),
        "clause_count": len(extractor_output.get("extracted_clauses", [])),
        "coverage_complete": extractor_output.get("coverage_complete"),
        "extraction_notes": extractor_output.get("extraction_notes"),
        "sections_processed": extractor_output.get("sections_processed"),
    }

    return FINALIZER_USER_TEMPLATE.format(
        policy_name=policy_name,
        assessment_date=assessment_date,
        extractor_output_json=json.dumps(extractor_summary, indent=2, ensure_ascii=False),
        verified_count=len(verified_clauses),
        flagged_count=len(flagged_clauses),
        flagged_details=flagged_details,
        evaluator_output_json=json.dumps(evaluator_output, indent=2, ensure_ascii=False),
        reflector_output_json=json.dumps(reflector_output, indent=2, ensure_ascii=False),
    )
