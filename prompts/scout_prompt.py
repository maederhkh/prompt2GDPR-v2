"""
Prompt for Pass 1 of two-pass extraction: Section Scout.

The Scout reads the full policy and returns a list of section headings
that are likely to contain purpose limitation content. It does NOT extract
or assess anything — it only identifies which sections to examine.
"""

SCOUT_SYSTEM = """\
You are a document analyst specialising in GDPR privacy policies. \
Your only task is to identify which sections of a policy contain content \
relevant to GDPR Article 5(1)(b) — purpose limitation. \
You are NOT assessing compliance. You are not extracting text. \
You are only producing a map of relevant sections so that a deeper \
extraction step can examine each one in full."""

SCOUT_USER_TEMPLATE = """\
Read the privacy policy below. Identify every section that is likely to contain \
content relevant to GDPR Article 5(1)(b) — purpose limitation.

Include a section if it contains ANY of the following:
- Statements of what personal data is used for (processing purposes)
- Legal bases tied to specific processing activities
- Secondary or further use of already-collected data
- Data sharing with third parties where purposes are described
- Research, analytics, profiling, or statistical processing
- Public health, archiving, or scientific purposes (Article 89 exceptions)
- Use of data for legal claims, compliance, or regulatory obligations
- Consent-based processing with stated purposes

When in doubt, include the section. It is better to examine too many sections \
than to miss one.

Return ONLY valid JSON with a single field "relevant_sections" — \
a list of section headings exactly as they appear in the policy text. \
If a section has no heading, describe it briefly (e.g. "opening paragraph").

Example:
{{"relevant_sections": ["3.1 When you access our Services", "3.8 Statistical purposes", "4. Sharing your data"]}}

---

## Privacy Policy

{policy_text}
"""


def build_scout_prompt(policy_text: str) -> str:
    return SCOUT_USER_TEMPLATE.format(policy_text=policy_text)
