"""
Agent 2: Evaluator

Applies the two-stage purpose limitation rubric (Article 5(1)(b) + Article 89)
to each verified clause produced by the Extractor + Verifier.

Uses tool calling to retrieve legal references on demand:
  - Primary sources (GDPR articles, recitals) — always available, consulted first
  - Secondary sources (WP29/EDPB opinions) — consulted only if primary is insufficient

Every reference retrieved is logged in the output under references_used[].
"""

import json

from openai import OpenAI

from config import MAX_TOKENS
from prompts.evaluator_prompt import EVALUATOR_SYSTEM, build_evaluator_prompt
from utils.schema_validator import parse_and_repair, validate_evaluator_output
from utils.legal_tools import LEGAL_TOOLS, execute_tool_call, ref_source_type

MAX_TOOL_ITERATIONS = 6   # safety cap on the tool-calling loop
EVALUATOR_BATCH_SIZE = 15  # max clauses per LLM call — prevents output truncation


def run_evaluator(
    client: OpenAI,
    verified_clauses: list[dict],
    model: str = "anthropic/claude-sonnet-4-5",
    retry_instructions: str | None = None,
) -> dict:
    """
    Call the Evaluator agent and return its parsed output.

    The agent runs in a tool-calling loop: it may call get_legal_reference
    multiple times before producing its final JSON assessment. Every call is
    tracked and injected into the output as references_used[].

    Args:
        client: OpenRouter-configured OpenAI client.
        verified_clauses: List of clause dicts that passed the string-match verifier.
        model: OpenRouter model slug (e.g. "openai/gpt-4o").
        retry_instructions: If this is a retry triggered by the Reflector,
                            additional instructions describing what went wrong.

    Returns:
        Parsed evaluator output dict including references_used[].

    Raises:
        ValueError: If verified_clauses is empty, or if the output cannot be
                    parsed or validated.
    """
    if not verified_clauses:
        raise ValueError(
            "Evaluator received no verified clauses. "
            "Cannot perform assessment without policy evidence."
        )

    # ------------------------------------------------------------------
    # Batching: if there are more clauses than EVALUATOR_BATCH_SIZE,
    # split into chunks and merge results. This prevents output truncation
    # when the two-pass extractor returns many clauses from a long policy.
    # ------------------------------------------------------------------
    if len(verified_clauses) > EVALUATOR_BATCH_SIZE:
        return _run_batched_evaluator(client, verified_clauses, model, retry_instructions)

    user_prompt = build_evaluator_prompt(verified_clauses)

    if retry_instructions:
        user_prompt = (
            f"## Retry instructions from quality reviewer\n"
            f"{retry_instructions}\n\n"
            f"---\n\n"
            + user_prompt
        )

    messages = [
        {"role": "system", "content": EVALUATOR_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]

    # Track all tool calls made during this run
    tools_called: list[dict] = []
    raw: str = ""

    # -----------------------------------------------------------------------
    # Tool-calling loop
    # -----------------------------------------------------------------------
    for iteration in range(MAX_TOOL_ITERATIONS):
        response = client.chat.completions.create(
            model=model,
            max_tokens=MAX_TOKENS["evaluator"],
            messages=messages,
            tools=LEGAL_TOOLS,
            tool_choice="auto",
        )

        message = response.choices[0].message

        # No tool calls → final answer
        if not message.tool_calls:
            raw = message.content or ""
            break

        # Build the assistant turn (OpenAI format requires tool_calls list)
        assistant_turn: dict = {"role": "assistant", "content": message.content or ""}
        assistant_turn["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in message.tool_calls
        ]
        messages.append(assistant_turn)

        # Execute each tool call and append results
        for tc in message.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            ref_id = args.get("reference_id", "")
            result_text = execute_tool_call(tc.function.name, args)

            # Log this call
            tools_called.append({
                "reference_id": ref_id,
                "source_type": ref_source_type(ref_id),
                "reason": args.get("reason", ""),
            })

            print(f"    [Tool] get_legal_reference({ref_id!r}) — "
                  f"{args.get('reason', '')[:60]}")

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_text,
            })
    else:
        # Max iterations reached — request final answer without tools
        print(f"  [Evaluator] Tool iteration cap ({MAX_TOOL_ITERATIONS}) reached. "
              f"Requesting final answer.")
        response = client.chat.completions.create(
            model=model,
            max_tokens=MAX_TOKENS["evaluator"],
            messages=messages,
        )
        raw = response.choices[0].message.content or ""

    # -----------------------------------------------------------------------
    # Parse, validate, and enrich with tool call log
    # -----------------------------------------------------------------------
    data = parse_and_repair(raw)

    errors = validate_evaluator_output(data)
    if errors:
        raise ValueError(
            "Evaluator output failed validation:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    # Merge objective tool call log with model's self-reported references_used.
    # The model's list takes precedence for the used_for field;
    # tools_called ensures nothing is silently omitted.
    existing_ids = {r.get("reference_id") for r in data.get("references_used", [])}
    for call in tools_called:
        if call["reference_id"] not in existing_ids:
            data.setdefault("references_used", []).append({
                "reference_id": call["reference_id"],
                "source_type": call["source_type"],
                "used_for": call.get("reason", ""),
            })

    # Always include the raw tool call log for the audit trail
    data["tools_called"] = tools_called

    return data


# ---------------------------------------------------------------------------
# Batched evaluation — used when clause count exceeds EVALUATOR_BATCH_SIZE
# ---------------------------------------------------------------------------

def _run_batched_evaluator(
    client: OpenAI,
    verified_clauses: list[dict],
    model: str,
    retry_instructions: str | None,
) -> dict:
    """
    Split verified_clauses into batches of EVALUATOR_BATCH_SIZE, evaluate
    each batch independently, then merge all evaluations into a single output.

    The overall_label is derived from the merged clause-level labels:
      - Any Non-Compliant  → overall Non-Compliant
      - Mix of Compliant + Partially Compliant → overall Partially Compliant
      - All Compliant → overall Compliant
    """
    total = len(verified_clauses)
    batches = [
        verified_clauses[i:i + EVALUATOR_BATCH_SIZE]
        for i in range(0, total, EVALUATOR_BATCH_SIZE)
    ]
    print(f"  [Evaluator] {total} clauses -> {len(batches)} batch(es) of "
          f"up to {EVALUATOR_BATCH_SIZE} each.")

    all_evaluations: list[dict] = []
    all_references: list[dict] = []
    all_tools_called: list[dict] = []

    for batch_idx, batch in enumerate(batches, start=1):
        ids = [c.get("clause_id", "?") for c in batch]
        print(f"    [Evaluator] Batch {batch_idx}/{len(batches)}: "
              f"{ids[0]}–{ids[-1]} ({len(batch)} clauses)")

        batch_result = run_evaluator(
            client=client,
            verified_clauses=batch,
            model=model,
            retry_instructions=retry_instructions,
        )

        all_evaluations.extend(batch_result.get("evaluations", []))
        all_references.extend(batch_result.get("references_used", []))
        all_tools_called.extend(batch_result.get("tools_called", []))

    # Derive overall label from clause-level labels
    labels = [e.get("clause_label", "") for e in all_evaluations]
    if "Non-Compliant" in labels:
        overall_label = "Non-Compliant"
    elif "Partially Compliant" in labels:
        overall_label = "Partially Compliant"
    else:
        overall_label = "Compliant"

    non_count = labels.count("Non-Compliant")
    partial_count = labels.count("Partially Compliant")
    compliant_count = labels.count("Compliant")
    overall_justification = (
        f"Batched evaluation of {total} clauses across {len(batches)} batch(es). "
        f"Label breakdown: {compliant_count} Compliant, "
        f"{partial_count} Partially Compliant, {non_count} Non-Compliant. "
        f"Overall label derived from clause-level labels per purpose limitation rules."
    )

    # Deduplicate references by reference_id
    seen_refs: set[str] = set()
    unique_refs: list[dict] = []
    for ref in all_references:
        rid = ref.get("reference_id", "")
        if rid not in seen_refs:
            seen_refs.add(rid)
            unique_refs.append(ref)

    merged = {
        "evaluations": all_evaluations,
        "overall_label": overall_label,
        "overall_justification": overall_justification,
        "references_used": unique_refs,
        "tools_called": all_tools_called,
        "_batched": True,
        "_batch_count": len(batches),
    }

    errors = validate_evaluator_output(merged)
    if errors:
        raise ValueError(
            "Batched evaluator output failed validation:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    return merged
