"""
Agent 1: Extractor (two-pass architecture)

Pass 1 — Section Scout:
    A lightweight call that reads the full policy and returns a list of
    section headings likely to contain purpose limitation content.

Pass 2 — Deep Extractor:
    For each identified section, a focused call extracts verbatim
    complete paragraphs (not individual sentences). This prevents the
    single-pass problem of stopping at the purpose sentence and missing
    safeguards or legal basis text in the same paragraph.
"""

from openai import OpenAI

from config import DEFAULT_AGENT_MODELS, MAX_TOKENS
from prompts.extractor_prompt import (
    EXTRACTOR_SYSTEM,
    build_extractor_prompt,
    build_section_extractor_prompt,
)
from prompts.scout_prompt import SCOUT_SYSTEM, build_scout_prompt
from utils.schema_validator import parse_and_repair, validate_extractor_output
from utils.section_splitter import split_sections


def run_extractor(
    client: OpenAI,
    policy_name: str,
    policy_text: str,
    model: str | None = None,
    scout_model: str | None = None,
    retry_instructions: str | None = None,
) -> dict:
    """
    Run two-pass extraction on a privacy policy.

    Pass 1 identifies relevant sections; Pass 2 extracts complete
    paragraphs from each section. Falls back to single-pass if the
    Scout returns no usable sections.

    Args:
        client: OpenRouter-configured OpenAI client.
        policy_name: Display name of the policy.
        policy_text: Full raw policy text.
        model: OpenRouter model slug for Pass 2 (Deep Extractor).
               Defaults to DEFAULT_AGENT_MODELS["extractor"].
        scout_model: OpenRouter model slug for Pass 1 (Scout).
                     Defaults to DEFAULT_AGENT_MODELS["scout"].
        retry_instructions: Additional instructions from the Reflector on retry.

    Returns:
        Parsed extractor output dict with all clauses merged.
    """
    # Resolve model defaults
    _model = model or DEFAULT_AGENT_MODELS.get("extractor", "anthropic/claude-sonnet-4-5")
    _scout_model = scout_model or DEFAULT_AGENT_MODELS.get("scout", _model)

    # ------------------------------------------------------------------
    # Pass 1: Section Scout
    # ------------------------------------------------------------------
    scout_sections = _run_scout(client, policy_text, _scout_model)

    if not scout_sections:
        # Scout returned nothing — fall back to single-pass
        print("    [Scout] No sections identified. Falling back to single-pass extraction.")
        return _run_single_pass(client, policy_name, policy_text, _model, retry_instructions)

    # ------------------------------------------------------------------
    # Split policy text into section chunks
    # ------------------------------------------------------------------
    sections = split_sections(policy_text, scout_sections)
    print(f"    [Scout] Identified {len(scout_sections)} relevant section(s). "
          f"Located {len(sections)} in policy text.")

    # If splitter couldn't locate sections, fall back to single-pass
    if len(sections) == 1 and sections[0]["name"] == "Full Policy":
        print("    [Scout] Section boundaries not found. Falling back to single-pass extraction.")
        return _run_single_pass(client, policy_name, policy_text, _model, retry_instructions)

    # ------------------------------------------------------------------
    # Pass 2: Deep extraction — one call per section
    # ------------------------------------------------------------------
    all_clauses: list[dict] = []
    clause_counter = 1

    for section in sections:
        section_clauses = _extract_from_section(
            client=client,
            section_name=section["name"],
            section_text=section["text"],
            clause_id_start=clause_counter,
            model=_model,
            retry_instructions=retry_instructions,
        )
        all_clauses.extend(section_clauses)
        clause_counter += len(section_clauses)

    notes = (
        f"Two-pass extraction: {len(sections)} section(s) processed "
        f"({', '.join(s['name'] for s in sections)})."
    )

    result = {
        "policy_name": policy_name,
        "extracted_clauses": all_clauses,
        "extraction_notes": notes,
        "coverage_complete": True,
        "sections_processed": [s["name"] for s in sections],
    }

    errors = validate_extractor_output(result)
    if errors:
        raise ValueError(
            "Extractor output failed validation:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_scout(client: OpenAI, policy_text: str, model: str) -> list[str]:
    """
    Pass 1: ask the model which sections are relevant to purpose limitation.
    Returns a list of section heading strings, or [] on failure.
    """
    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=MAX_TOKENS["scout"],
            messages=[
                {"role": "system", "content": SCOUT_SYSTEM},
                {"role": "user", "content": build_scout_prompt(policy_text)},
            ],
        )
        raw = response.choices[0].message.content or ""
        data = parse_and_repair(raw)
        sections = data.get("relevant_sections", [])
        if isinstance(sections, list):
            return [str(s) for s in sections if s]
    except Exception as e:
        print(f"    [Scout] Warning: scout call failed ({e}). Will fall back to single-pass.")
    return []


def _extract_from_section(
    client: OpenAI,
    section_name: str,
    section_text: str,
    clause_id_start: int,
    model: str,
    retry_instructions: str | None,
) -> list[dict]:
    """
    Pass 2: extract complete paragraphs from a single policy section.
    Returns a (possibly empty) list of clause dicts.
    """
    user_prompt = build_section_extractor_prompt(
        section_name=section_name,
        section_text=section_text,
        clause_id_start=clause_id_start,
    )

    if retry_instructions:
        user_prompt = (
            f"## Retry instructions from quality reviewer\n"
            f"{retry_instructions}\n\n---\n\n"
            + user_prompt
        )

    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=MAX_TOKENS["extractor"],
            messages=[
                {"role": "system", "content": EXTRACTOR_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
        )
        raw = response.choices[0].message.content or ""
        data = parse_and_repair(raw)
        clauses = data.get("extracted_clauses", [])
        if isinstance(clauses, list):
            return clauses
    except Exception as e:
        print(f"    [Extractor] Warning: section '{section_name}' extraction failed ({e}).")
    return []


def _run_single_pass(
    client: OpenAI,
    policy_name: str,
    policy_text: str,
    model: str,
    retry_instructions: str | None,
) -> dict:
    """
    Fallback: original single-pass extraction over the full policy text.
    Used when the Scout fails or section boundaries cannot be located.
    """
    user_prompt = build_extractor_prompt(policy_name, policy_text)

    if retry_instructions:
        user_prompt = (
            f"## Retry instructions from quality reviewer\n"
            f"{retry_instructions}\n\n---\n\n"
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
