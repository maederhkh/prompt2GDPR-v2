"""
JSON schema validation and repair utilities.

The thesis found that LLMs sometimes produce malformed JSON even when explicitly
instructed to follow a schema. This module validates and attempts to repair agent
outputs before they are passed downstream.
"""

import json
import re

from json_repair import repair_json


def parse_and_repair(raw: str) -> dict | list:
    """
    Attempt to parse a raw LLM response as JSON.

    Repair steps (in order):
    1. Direct parse.
    2. Extract the first JSON object/array (strip markdown fences / prose).
    3. Clean common artefacts (smart quotes, trailing commas, comments).
    4. json-repair — handles unescaped quotes, truncated responses, etc.

    Raises:
        ValueError: If the response cannot be parsed into valid JSON after all
                    repair attempts.
    """
    # Step 0: strip thinking tags (Qwen3, DeepSeek-R1, and similar models
    # prepend <think>...</think> blocks before their actual JSON output)
    raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()

    # Step 1: direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Step 2: extract the first {...} or [...] block
    extracted = _extract_json_block(raw)
    if extracted:
        try:
            return json.loads(extracted)
        except json.JSONDecodeError:
            pass

    # Step 3: clean common artefacts and retry
    cleaned = _clean_artefacts(extracted or raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Step 4: json-repair (handles unescaped quotes, truncated JSON, etc.)
    try:
        repaired = repair_json(cleaned, return_objects=True)
        if isinstance(repaired, (dict, list)):
            return repaired
    except Exception:
        pass

    raise ValueError(
        f"Could not parse agent response as JSON after repair attempts.\n"
        f"Raw content (first 500 chars): {raw[:500]}"
    )


def _extract_json_block(text: str) -> str | None:
    """Extract the first complete JSON object or array from a string."""
    # Try to find opening brace or bracket
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        start = text.find(start_char)
        if start == -1:
            continue
        # Walk forward counting depth to find the matching close
        depth = 0
        in_string = False
        escape_next = False
        for i, ch in enumerate(text[start:], start=start):
            if escape_next:
                escape_next = False
                continue
            if ch == '\\' and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == start_char:
                depth += 1
            elif ch == end_char:
                depth -= 1
                if depth == 0:
                    return text[start: i + 1]
    return None


def _clean_artefacts(text: str) -> str:
    """Fix common LLM JSON artefacts."""
    # Replace smart/curly quotes with standard quotes
    text = text.replace('\u201c', '"').replace('\u201d', '"')
    text = text.replace('\u2018', "'").replace('\u2019', "'")
    # Remove trailing commas before } or ]
    text = re.sub(r',\s*([}\]])', r'\1', text)
    # Remove comments (// ...) — LLMs sometimes add these
    text = re.sub(r'//[^\n]*', '', text)
    return text


def validate_extractor_output(data: dict) -> list[str]:
    """
    Validate the Extractor (Agent 1) output structure.

    Returns a list of error messages. Empty list means valid.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["Root must be a JSON object."]
    if "extracted_clauses" not in data:
        errors.append("Missing required field: extracted_clauses")
    else:
        clauses = data["extracted_clauses"]
        if not isinstance(clauses, list):
            errors.append("extracted_clauses must be a list.")
        else:
            for i, clause in enumerate(clauses):
                for field in ("clause_id", "quote", "relevance_type"):
                    if field not in clause:
                        errors.append(f"Clause {i}: missing field '{field}'.")
                    elif not isinstance(clause[field], str) or not clause[field].strip():
                        errors.append(f"Clause {i}: field '{field}' must be a non-empty string.")
    return errors


def validate_evaluator_output(data: dict) -> list[str]:
    """
    Validate the Evaluator (Agent 2) output structure.

    Returns a list of error messages. Empty list means valid.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["Root must be a JSON object."]
    if "evaluations" not in data:
        errors.append("Missing required field: evaluations")
    else:
        evals = data["evaluations"]
        if not isinstance(evals, list):
            errors.append("evaluations must be a list.")
        else:
            valid_labels = {"Compliant", "Partially Compliant", "Non-Compliant"}
            for i, ev in enumerate(evals):
                if "clause_id" not in ev:
                    errors.append(f"Evaluation {i}: missing field 'clause_id'.")
                if "clause_label" not in ev:
                    errors.append(f"Evaluation {i}: missing field 'clause_label'.")
                elif ev["clause_label"] not in valid_labels:
                    errors.append(
                        f"Evaluation {i}: invalid clause_label '{ev['clause_label']}'. "
                        f"Must be one of {valid_labels}."
                    )
                if "justification" not in ev or not ev.get("justification", "").strip():
                    errors.append(f"Evaluation {i}: missing or empty 'justification'.")
                if "stage_1" not in ev:
                    errors.append(f"Evaluation {i}: missing 'stage_1' assessment block.")
    if "overall_label" not in data:
        errors.append("Missing required field: overall_label")

    # references_used is optional but must be a list if present
    if "references_used" in data and not isinstance(data["references_used"], list):
        errors.append("references_used must be a list.")

    return errors


def validate_reflector_output(data: dict) -> list[str]:
    """Validate the Reflector (Agent 3) output structure."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["Root must be a JSON object."]
    if "review_status" not in data:
        errors.append("Missing required field: review_status")
    elif data["review_status"] not in {"clean", "errors_found", "errors_unresolved"}:
        errors.append(f"Invalid review_status: '{data['review_status']}'.")
    return errors


def validate_finalizer_output(data: dict) -> list[str]:
    """Validate the Finalizer (Agent 4) output structure."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["Root must be a JSON object."]
    for field in ("policy_name", "overall_label", "confidence",
                  "key_findings", "identified_gaps"):
        if field not in data:
            errors.append(f"Missing required field: '{field}'.")
    return errors
