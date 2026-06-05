"""
Blind Labeler agent.

Assigns a purpose-limitation compliance label to each verified clause using the
same rubric and the same legal-reference tool as the Evaluator — but without ever
seeing the Evaluator's output. Its labels are the "blind" (unanchored) condition
in the anchoring measurement.

Runs at temperature 0 and batches large clause sets exactly like the Evaluator,
so the only difference from the Evaluator is the absence of evaluator output.
"""

import json

from openai import OpenAI

from config import MAX_TOKENS, LABELER_TEMPERATURE
from prompts.blind_labeler_prompt import BLIND_LABELER_SYSTEM, build_blind_labeler_prompt
from utils.schema_validator import parse_and_repair
from utils.legal_tools import LEGAL_TOOLS, execute_tool_call

MAX_TOOL_ITERATIONS = 6
BLIND_LABELER_BATCH_SIZE = 15  # match the evaluator's batch size (confound control)


def run_blind_labeler(
    client: OpenAI,
    verified_clauses: list[dict],
    model: str,
) -> dict:
    """
    Assign a blind compliance label to each verified clause.

    Args:
        client: OpenRouter-configured OpenAI client.
        verified_clauses: Clauses that passed the string-match verifier.
        model: OpenRouter model slug — MUST match the paired reflector's model.

    Returns:
        {"labels": [{"clause_id": str, "label": str}, ...]} — one entry per clause.
        On total failure, returns {"labels": []}; callers treat missing labels as null.
    """
    if not verified_clauses:
        return {"labels": []}

    if len(verified_clauses) > BLIND_LABELER_BATCH_SIZE:
        return _run_batched(client, verified_clauses, model)

    user_prompt = build_blind_labeler_prompt(verified_clauses)
    messages = [
        {"role": "system", "content": BLIND_LABELER_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]

    raw = ""
    for _ in range(MAX_TOOL_ITERATIONS):
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=MAX_TOKENS["blind_labeler"],
                temperature=LABELER_TEMPERATURE,
                messages=messages,
                tools=LEGAL_TOOLS,
                tool_choice="auto",
            )
        except Exception as e:
            print(f"    [Blind Labeler] Warning: call failed ({e}). Returning no labels.")
            return {"labels": []}

        message = response.choices[0].message

        if not message.tool_calls:
            raw = message.content or ""
            break

        assistant_turn = {"role": "assistant", "content": message.content or ""}
        assistant_turn["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in message.tool_calls
        ]
        messages.append(assistant_turn)

        for tc in message.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}
            ref_id = args.get("reference_id", "")
            result_text = execute_tool_call(tc.function.name, args)
            print(f"    [Blind Labeler] get_legal_reference({ref_id!r})")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_text})
    else:
        # Tool cap reached — ask for the final answer without tools
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=MAX_TOKENS["blind_labeler"],
                temperature=LABELER_TEMPERATURE,
                messages=messages,
            )
            raw = response.choices[0].message.content or ""
        except Exception as e:
            print(f"    [Blind Labeler] Warning: final call failed ({e}). Returning no labels.")
            return {"labels": []}

    try:
        data = parse_and_repair(raw)
    except Exception as e:
        print(f"    [Blind Labeler] Warning: could not parse output ({e}). Returning no labels.")
        return {"labels": []}

    labels = data.get("labels", []) if isinstance(data, dict) else []
    if not isinstance(labels, list):
        labels = []
    # Keep only well-formed entries
    clean = [
        {"clause_id": str(x.get("clause_id")), "label": str(x.get("label"))}
        for x in labels
        if isinstance(x, dict) and x.get("clause_id") and x.get("label")
    ]
    return {"labels": clean}


def _run_batched(client: OpenAI, verified_clauses: list[dict], model: str) -> dict:
    """Split into batches of BLIND_LABELER_BATCH_SIZE and merge label lists."""
    total = len(verified_clauses)
    batches = [
        verified_clauses[i:i + BLIND_LABELER_BATCH_SIZE]
        for i in range(0, total, BLIND_LABELER_BATCH_SIZE)
    ]
    print(f"  [Blind Labeler] {total} clauses -> {len(batches)} batch(es).")

    all_labels: list[dict] = []
    for idx, batch in enumerate(batches, start=1):
        print(f"    [Blind Labeler] Batch {idx}/{len(batches)} ({len(batch)} clauses)")
        result = run_blind_labeler(client, batch, model)
        all_labels.extend(result.get("labels", []))
    return {"labels": all_labels}
