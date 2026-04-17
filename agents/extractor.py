"""
Agent 1: Extractor

Reads the full privacy policy text and extracts clauses relevant to
GDPR Article 5(1)(b) — purpose limitation.
"""

from openai import OpenAI

from config import MAX_TOKENS
from prompts.extractor_prompt import EXTRACTOR_SYSTEM, build_extractor_prompt
from utils.schema_validator import parse_and_repair, validate_extractor_output


def run_extractor(
    client: OpenAI,
    policy_name: str,
    policy_text: str,
    model: str = "anthropic/claude-sonnet-4-5",
    retry_instructions: str | None = None,
) -> dict:
    """
    Call the Extractor agent and return its parsed output.

    Args:
        client: OpenRouter-configured OpenAI client.
        policy_name: Display name of the policy being assessed.
        policy_text: Full raw text of the privacy policy.
        model: OpenRouter model slug (e.g. "openai/gpt-4o").
        retry_instructions: If this is a retry triggered by the Reflector,
                            additional instructions describing what went wrong.

    Returns:
        Parsed extractor output dict.

    Raises:
        ValueError: If the agent output cannot be parsed or validated.
    """
    user_prompt = build_extractor_prompt(policy_name, policy_text)

    if retry_instructions:
        user_prompt = (
            f"## Retry instructions from quality reviewer\n"
            f"{retry_instructions}\n\n"
            f"---\n\n"
            + user_prompt
        )

    response = client.chat.completions.create(
        model=model,
        max_tokens=MAX_TOKENS["extractor"],
        messages=[
            {"role": "system", "content": EXTRACTOR_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
    )

    raw = response.choices[0].message.content
    data = parse_and_repair(raw)

    errors = validate_extractor_output(data)
    if errors:
        raise ValueError(
            "Extractor output failed validation:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    return data
