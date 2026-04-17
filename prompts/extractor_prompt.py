"""
Prompt for Agent 1: Extractor.

The Extractor reads the full privacy policy text and identifies every clause
that is relevant to GDPR Article 5(1)(b) — purpose limitation.
"""

EXTRACTOR_SYSTEM = """\
You are a GDPR legal specialist with deep expertise in Article 5(1)(b) — the \
purpose limitation principle. Your task is to extract clauses from privacy policies \
that are relevant to purpose limitation assessment. You extract only what is \
explicitly written in the policy — you do not paraphrase, infer, or add information \
that is not present. You quote the policy verbatim."""

EXTRACTOR_USER_TEMPLATE = """\
## Task
Read the privacy policy below and extract every clause that is relevant to \
GDPR Article 5(1)(b) — purpose limitation.

## What to extract
Look specifically for the following types of content:
1. Stated processing purposes (per processing activity or category of data)
2. Legal basis references that are linked to a specific stated purpose
3. Secondary or further use clauses (data used beyond the original collection purpose)
4. Third-party data sharing clauses that include the purpose of sharing
5. Research, analytics, profiling, or product development purpose clauses
6. Any clause that explicitly invokes Article 89 GDPR exceptions \
(scientific/historical research, archiving in the public interest, statistics)

## Rules
- Quote each clause **verbatim** — copy the exact words from the policy.
- Do not paraphrase, summarise, or combine multiple clauses into one quote.
- Include the section title or number in "section_reference" if it appears in the policy.
- Identify the most relevant type for each clause using the relevance_type values below.
- Extract a maximum of 15 clauses. If more than 15 are present, select the \
15 most directly relevant to purpose limitation, prioritising clauses that cover \
distinct purposes or processing activities over clauses that repeat similar content.
- If a clause is ambiguous about whether it belongs, include it and note the \
ambiguity in "extraction_notes".
- Set "coverage_complete" to true if you believe you have captured all materially \
relevant clauses. Set it to false if the policy contained more relevant content \
than the 15-clause limit allowed — and briefly describe what was omitted in \
"extraction_notes".

## relevance_type values
- stated_purpose — a clause that directly states what personal data is collected for
- legal_basis — a clause that states the legal basis tied to a specific purpose
- secondary_use — a clause describing further processing beyond the original purpose
- third_party — a clause describing sharing data with third parties and the purpose
- research_exception — a clause invoking Article 89 exceptions
- other — relevant to purpose limitation but does not fit the above

## Output format
Return ONLY valid JSON matching this exact schema. No prose, no markdown, no explanation.

{{
  "policy_name": "<name or filename of the policy>",
  "extracted_clauses": [
    {{
      "clause_id": "C1",
      "quote": "<verbatim text from the policy>",
      "section_reference": "<section title or number, or null if not present>",
      "relevance_type": "<stated_purpose | legal_basis | secondary_use | third_party | research_exception | other>"
    }}
  ],
  "extraction_notes": "<any ambiguity, coverage gaps, or observations — or null>",
  "coverage_complete": true
}}

---

## Policy name
{policy_name}

## Privacy policy text
{policy_text}
"""


def build_extractor_prompt(policy_name: str, policy_text: str) -> str:
    """Return the formatted user prompt for the Extractor agent."""
    return EXTRACTOR_USER_TEMPLATE.format(
        policy_name=policy_name,
        policy_text=policy_text,
    )
