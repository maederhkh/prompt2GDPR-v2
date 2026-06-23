"""
Prompt for Pass 1 of two-pass extraction: Section Scout.

The Scout reads the full policy and returns auditable section decisions
for content likely to contain purpose limitation material. It does NOT
extract or assess anything; it only identifies which sections to examine.
"""

SCOUT_SYSTEM = """\
You are a document analyst specialising in GDPR privacy policies. \
Your only task is to identify which sections of a policy contain content \
relevant to GDPR Article 5(1)(b) - purpose limitation. \
You are NOT assessing compliance. You are not extracting text. \
You are only producing a map of relevant sections so that a deeper \
extraction step can examine each one in full."""

SCOUT_USER_TEMPLATE = """\
Read the privacy policy below. Classify policy sections by whether they are \
likely to contain content relevant to GDPR Article 5(1)(b) - purpose limitation.

Include a section if it contains ANY of the following:
- Statements of what personal data is used for (processing purposes)
- Legal bases tied to specific processing activities
- Secondary or further use of already-collected data
- Data sharing with third parties where purposes are described
- Research, analytics, profiling, or statistical processing
- Public health, archiving, or scientific purposes (Article 89 exceptions)
- Use of data for legal claims, compliance, or regulatory obligations
- Consent-based processing with stated purposes

Use "include" for sections that clearly contain purpose-limitation content. \
Use "maybe_include" for borderline sections that may contain relevant purpose, \
legal basis, sharing, analytics, research, consent, or compliance language. \
When in doubt, choose "maybe_include" rather than "exclude". It is better for \
the extractor to examine too many sections than to miss one.

Use "exclude" for sections that appear administrative only, such as contact \
details, version history, navigation text, or content with no processing \
purpose signal.

Return ONLY valid JSON with exactly these fields:
- "include": section decision objects
- "maybe_include": section decision objects
- "exclude": section decision objects

Each section decision object must contain:
- "heading": the section heading exactly as it appears in the policy text; if \
  a section has no heading, describe it briefly, e.g. "opening paragraph"
- "reason": a short explanation for the classification
- "signals": a short list of matched purpose-limitation signals
- "confidence": "high", "medium", or "low"

Example:
{{
  "include": [
    {{
      "heading": "3.1 When you access our Services",
      "reason": "Describes purposes for processing service usage data.",
      "signals": ["processing purposes"],
      "confidence": "high"
    }}
  ],
  "maybe_include": [
    {{
      "heading": "3.8 Statistical purposes",
      "reason": "May describe statistical or analytics purposes.",
      "signals": ["statistical purposes", "analytics"],
      "confidence": "medium"
    }}
  ],
  "exclude": [
    {{
      "heading": "12. Contact us",
      "reason": "Administrative contact information only.",
      "signals": [],
      "confidence": "medium"
    }}
  ]
}}

---

## Privacy Policy

{policy_text}
"""


def build_scout_prompt(policy_text: str) -> str:
    return SCOUT_USER_TEMPLATE.format(policy_text=policy_text)
