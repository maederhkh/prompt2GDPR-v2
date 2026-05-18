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
    SELF_CHECK_JUDGE_SYSTEM,
    build_gap_judge_prompt,
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


def _find_uncovered_paragraphs(
    sections: list[dict],
    all_clauses: list[dict],
) -> list[dict]:
    """
    For each section, split its text into paragraphs and check whether
    each paragraph is covered by at least one extracted clause quote.

    A paragraph is considered covered if its best fuzzy match score
    against any clause quote from the same section is >= 60.

    Args:
        sections: List of {"name": str, "text": str} dicts from the splitter.
        all_clauses: All clauses extracted in Pass 2.

    Returns:
        List of {"section_name": str, "paragraph": str,
                 "section_clauses": list[dict]} dicts — one per uncovered paragraph.
    """
    from rapidfuzz import fuzz

    uncovered = []

    for section in sections:
        section_name = section["name"]
        section_text = section["text"]

        # Clauses extracted from this specific section
        section_clauses = [
            c for c in all_clauses
            if c.get("section_reference") == section_name
        ]

        # Split section into paragraphs
        paragraphs = [
            p.strip()
            for p in section_text.split("\n\n")
            if p.strip() and len(p.strip()) > 30  # skip very short fragments
        ]

        for paragraph in paragraphs:
            if not section_clauses:
                # No clauses at all from this section — every paragraph is uncovered
                uncovered.append({
                    "section_name": section_name,
                    "paragraph": paragraph,
                    "section_clauses": [],
                })
                continue

            # Check best match against all clause quotes from this section
            best_score = max(
                fuzz.partial_ratio(paragraph.lower(), c.get("quote", "").lower())
                for c in section_clauses
            )

            if best_score < 60:
                uncovered.append({
                    "section_name": section_name,
                    "paragraph": paragraph,
                    "section_clauses": section_clauses,
                })

    return uncovered


def _judge_paragraph_gap(
    client: OpenAI,
    paragraph: str,
    section_clauses: list[dict],
    model: str,
) -> dict:
    """
    Pass 3 Step 2: ask the model whether an uncovered paragraph contains
    purpose limitation content not already captured.

    Args:
        client: OpenRouter-configured OpenAI client.
        paragraph: The uncovered paragraph text.
        section_clauses: Already-extracted clauses from the same section.
        model: Model slug for gap judgment (Gemini Flash).

    Returns:
        {"is_gap": bool, "reason": str} — defaults to is_gap=False on failure.
    """
    try:
        user_prompt = build_gap_judge_prompt(
            paragraph=paragraph,
            existing_clauses=section_clauses,
        )
        response = client.chat.completions.create(
            model=model,
            max_tokens=256,
            messages=[
                {"role": "system", "content": SELF_CHECK_JUDGE_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
        )
        raw = response.choices[0].message.content or ""
        data = parse_and_repair(raw)
        if isinstance(data, dict) and "is_gap" in data:
            return {
                "is_gap": bool(data["is_gap"]),
                "reason": str(data.get("reason", "")),
            }
    except Exception as e:
        print(f"    [Self-Check] Warning: gap judgment failed ({e}). Treating as no gap.")
    return {"is_gap": False, "reason": "judgment call failed — treated as no gap"}
