"""
Agent 3: Reflector

Audits the outputs of Agents 1 and 2, identifies errors, and produces a
structured review report. The orchestrator uses this report to decide
whether to trigger retries.
"""

from openai import OpenAI

from config import MAX_TOKENS, LABELER_TEMPERATURE
from prompts.reflector_prompt import REFLECTOR_SYSTEM, build_reflector_prompt
from utils.schema_validator import parse_and_repair, validate_reflector_output


def run_reflector(
    client: OpenAI,
    verified_clauses: list[dict],
    flagged_clauses: list[dict],
    evaluator_output: dict,
    model: str = "anthropic/claude-sonnet-4-5",
) -> dict:
    """
    Call the Reflector agent and return its audit report.

    Args:
        client: OpenRouter-configured OpenAI client.
        verified_clauses: Clauses that passed the string-match verifier.
        flagged_clauses: Clauses that failed the string-match verifier.
        evaluator_output: Parsed output from Agent 2.
        model: OpenRouter model slug (e.g. "openai/gpt-4o").

    Returns:
        Parsed reflector output dict with review_status and errors list.

    Raises:
        ValueError: If the output cannot be parsed or validated.
    """
    user_prompt = build_reflector_prompt(
        verified_clauses=verified_clauses,
        flagged_clauses=flagged_clauses,
        evaluator_output=evaluator_output,
    )

    response = client.chat.completions.create(
        model=model,
        max_tokens=MAX_TOKENS["reflector"],
        temperature=LABELER_TEMPERATURE,
        messages=[
            {"role": "system", "content": REFLECTOR_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
    )

    raw = response.choices[0].message.content
    data = parse_and_repair(raw)

    errors = validate_reflector_output(data)
    if errors:
        raise ValueError(
            "Reflector output failed validation:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    return data


def errors_for_agent(reflector_output: dict, agent_id: str) -> list[dict]:
    """
    Filter the Reflector's error list to only errors assigned to a specific agent.

    Args:
        reflector_output: Parsed reflector output dict.
        agent_id: "1" or "2".

    Returns:
        List of error dicts assigned to the given agent.
    """
    return [
        e for e in reflector_output.get("errors", [])
        if str(e.get("responsible_agent", "")) == str(agent_id)
    ]


def build_retry_instructions(errors: list[dict]) -> str:
    """
    Format the Reflector's error list into human-readable retry instructions.

    Args:
        errors: List of error dicts from the Reflector output.

    Returns:
        A string to prepend to the agent's prompt on retry.
    """
    lines = [
        "The quality reviewer found the following problems in your previous output. "
        "Please correct them in your new response:\n"
    ]
    for i, err in enumerate(errors, 1):
        clause_ref = f" (clause {err['clause_id']})" if err.get("clause_id") else ""
        lines.append(f"{i}. [{err['error_type']}]{clause_ref}: {err['description']}")
    return "\n".join(lines)
