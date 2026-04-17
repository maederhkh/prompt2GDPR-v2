"""
Agent 4: Finalizer

Consolidates all pipeline outputs into a single structured compliance report,
sets the confidence level, and highlights items for human expert review.
"""

from datetime import date

from openai import OpenAI

from config import MAX_TOKENS
from prompts.finalizer_prompt import FINALIZER_SYSTEM, build_finalizer_prompt
from utils.schema_validator import parse_and_repair, validate_finalizer_output


def run_finalizer(
    client: OpenAI,
    policy_name: str,
    extractor_output: dict,
    verified_clauses: list[dict],
    flagged_clauses: list[dict],
    evaluator_output: dict,
    reflector_output: dict,
    model: str = "anthropic/claude-sonnet-4-5",
) -> dict:
    """
    Call the Finalizer agent and return the complete compliance report.

    Args:
        client: OpenRouter-configured OpenAI client.
        policy_name: Display name of the assessed policy.
        extractor_output: Parsed output from Agent 1.
        verified_clauses: Clauses that passed the verifier.
        flagged_clauses: Clauses that failed the verifier.
        evaluator_output: Parsed output from Agent 2.
        reflector_output: Final parsed output from Agent 3 (after any retries).
        model: OpenRouter model slug (e.g. "openai/gpt-4o").

    Returns:
        Parsed finalizer output dict — the complete compliance report.

    Raises:
        ValueError: If the output cannot be parsed or validated.
    """
    assessment_date = date.today().isoformat()

    # Mark reflector status as unresolved if retries were exhausted
    _annotate_reflector_status(reflector_output)

    user_prompt = build_finalizer_prompt(
        policy_name=policy_name,
        assessment_date=assessment_date,
        extractor_output=extractor_output,
        verified_clauses=verified_clauses,
        flagged_clauses=flagged_clauses,
        evaluator_output=evaluator_output,
        reflector_output=reflector_output,
    )

    response = client.chat.completions.create(
        model=model,
        max_tokens=MAX_TOKENS["finalizer"],
        messages=[
            {"role": "system", "content": FINALIZER_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
    )

    raw = response.choices[0].message.content
    data = parse_and_repair(raw)

    errors = validate_finalizer_output(data)
    if errors:
        raise ValueError(
            "Finalizer output failed validation:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    # Ensure human_review_recommended is always True
    data["human_review_recommended"] = True

    # Surface incomplete coverage as an unresolved flag
    if not extractor_output.get("coverage_complete", True):
        flag = (
            "Extraction coverage incomplete: the policy may contain more purpose "
            "limitation clauses than the 15-clause extraction limit allowed. "
            f"Extractor notes: {extractor_output.get('extraction_notes', 'none')}. "
            "Human reviewer should read the full policy for additional clauses."
        )
        data.setdefault("unresolved_flags", [])
        if flag not in data["unresolved_flags"]:
            data["unresolved_flags"].append(flag)
        # Downgrade confidence if it was high
        if data.get("confidence") == "high":
            data["confidence"] = "medium"

    return data


def _annotate_reflector_status(reflector_output: dict) -> None:
    """
    If the reflector output contains unresolved errors (set by the orchestrator),
    ensure review_status reflects this. Mutates in place.
    """
    if reflector_output.get("_retries_exhausted"):
        reflector_output["review_status"] = "errors_unresolved"
