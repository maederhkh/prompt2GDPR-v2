"""
Legal reference tools for the Evaluator agent.

Provides:
  - LEGAL_TOOLS: tool definitions for the OpenAI tools API
  - execute_tool_call(): loads and returns the requested reference text
  - PRIMARY_REFS / SECONDARY_REFS: reference registry

File layout expected:
  data/legal_refs/primary/article_5_1b.txt
  data/legal_refs/primary/article_89.txt
  data/legal_refs/primary/recital_39.txt
  data/legal_refs/primary/recital_50.txt
  data/legal_refs/primary/recital_157.txt
  data/legal_refs/secondary/wp29_purpose_limitation_excerpts.txt
"""

import json
from pathlib import Path

LEGAL_REFS_DIR = Path(__file__).parent.parent / "data" / "legal_refs"

# Registry: reference_id → relative path from LEGAL_REFS_DIR
PRIMARY_REFS: dict[str, str] = {
    "article_5_1b":  "primary/article_5_1b.txt",
    "article_89":    "primary/article_89.txt",
    "recital_39":    "primary/recital_39.txt",
    "recital_50":    "primary/recital_50.txt",
    "recital_157":   "primary/recital_157.txt",
}

SECONDARY_REFS: dict[str, str] = {
    "wp29_purpose_limitation": "secondary/wp29_purpose_limitation_excerpts.txt",
}

ALL_REFS: dict[str, str] = {**PRIMARY_REFS, **SECONDARY_REFS}

_REF_DESCRIPTIONS: dict[str, str] = {
    "article_5_1b":
        "GDPR Article 5(1)(b) — the purpose limitation principle "
        "[PRIMARY — binding law]",
    "article_89":
        "GDPR Article 89 — safeguards for research / archiving / statistics exceptions "
        "[PRIMARY — binding law]",
    "recital_39":
        "Recital 39 — defines 'specified, explicit, legitimate' purposes and "
        "the at-collection requirement "
        "[PRIMARY — binding law]",
    "recital_50":
        "Recital 50 — compatible further processing criteria "
        "[PRIMARY — binding law]",
    "recital_157":
        "Recital 157 — definitions for scientific research, statistics, and archiving "
        "[PRIMARY — binding law]",
    "wp29_purpose_limitation":
        "WP29 Opinion 03/2013 (WP203) — authoritative guidance on the purpose limitation "
        "compatibility test; five-factor analysis "
        "[SECONDARY — authoritative, not binding; consult only if primary sources "
        "are insufficient]",
}


# ---------------------------------------------------------------------------
# Tool definition — passed to client.chat.completions.create(tools=...)
# ---------------------------------------------------------------------------

LEGAL_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_legal_reference",
            "description": (
                "Retrieve the exact text of a GDPR legal source to support your clause assessment.\n\n"
                "IMPORTANT RULES:\n"
                "1. Always consult primary sources first — they are binding law.\n"
                "2. Only call a secondary source if the primary sources you have already "
                "retrieved are genuinely insufficient to make a confident assessment.\n"
                "3. Do not call the same reference_id twice.\n\n"
                "Available references:\n"
                + "\n".join(
                    f"  • {rid}: {desc}"
                    for rid, desc in _REF_DESCRIPTIONS.items()
                )
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reference_id": {
                        "type": "string",
                        "enum": list(ALL_REFS.keys()),
                        "description": "Identifier of the reference to retrieve.",
                    },
                    "reason": {
                        "type": "string",
                        "description": (
                            "One sentence explaining why you need this specific reference "
                            "for your current assessment."
                        ),
                    },
                },
                "required": ["reference_id", "reason"],
            },
        },
    }
]


# ---------------------------------------------------------------------------
# Tool executor — called by the agent loop when the model issues a tool call
# ---------------------------------------------------------------------------

def execute_tool_call(tool_name: str, arguments: dict) -> str:
    """
    Execute a legal tool call and return the reference text as a string.

    Args:
        tool_name: Must be "get_legal_reference".
        arguments: Parsed JSON arguments dict (reference_id, reason).

    Returns:
        Formatted reference text, or a descriptive error string.
    """
    if tool_name != "get_legal_reference":
        return f"[ERROR] Unknown tool: '{tool_name}'."

    ref_id = arguments.get("reference_id", "")

    if ref_id not in ALL_REFS:
        return (
            f"[ERROR] Unknown reference_id: '{ref_id}'. "
            f"Valid options: {list(ALL_REFS.keys())}"
        )

    ref_path = LEGAL_REFS_DIR / ALL_REFS[ref_id]

    if not ref_path.exists():
        return (
            f"[MISSING FILE] The reference '{ref_id}' has not been added yet.\n"
            f"Expected location: data/legal_refs/{ALL_REFS[ref_id]}\n"
            f"Please add the text and re-run."
        )

    source_type = "PRIMARY" if ref_id in PRIMARY_REFS else "SECONDARY"
    text = ref_path.read_text(encoding="utf-8").strip()

    return (
        f"[{source_type} SOURCE — {ref_id}]\n"
        f"{_REF_DESCRIPTIONS[ref_id]}\n\n"
        f"{text}"
    )


def ref_source_type(ref_id: str) -> str:
    """Return 'primary' or 'secondary' for a given reference_id."""
    return "primary" if ref_id in PRIMARY_REFS else "secondary"
