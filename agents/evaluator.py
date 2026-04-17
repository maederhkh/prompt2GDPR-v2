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
