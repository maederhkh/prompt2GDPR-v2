"""
main.py — Orchestrator for the GDPR Purpose Limitation Compliance Workflow.

Pipeline:
  Policy text
    → Agent 1 (Extractor)
    → String-Match Verifier
    → Agent 2 (Evaluator)
    → Agent 3 (Reflector)  [with retry loop, max 2 retries per agent]
    → Agent 4 (Finalizer)
    → Evaluation metrics (M1-M5)
    → JSON output saved to output/results/

Usage:
    python main.py --policy data/policies/policy_short.txt
    python main.py --policy data/policies/policy_long.txt --runs 3
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from agents.extractor import run_extractor
from agents.evaluator import run_evaluator
from agents.reflector import run_reflector, errors_for_agent, build_retry_instructions
from utils.reflector_merge import merge_reflector_outputs
from agents.finalizer import run_finalizer
from utils.run_metadata import build_run_metadata
from agents.blind_labeler import run_blind_labeler
from utils.label_panel import build_label_panel, annotate_finalizer_with_disputes
from config import DEFAULT_MODEL, DEFAULT_AGENT_MODELS, OPENROUTER_BASE_URL, ENABLE_BLIND_LABELER, LABELER_TEMPERATURE
from utils.verifier import verify_clauses
from utils.report_generator import generate_report

MAX_RETRIES = 2


def run_pipeline(client: OpenAI, policy_path: Path, agent_models: dict,
                 blind_enabled: bool = True) -> dict:
    """
    Execute the full 4-agent pipeline for a single policy file.

    Args:
        client: OpenRouter-configured OpenAI client.
        policy_path: Path to the policy text file.
        agent_models: Dict with keys "extractor", "evaluator", "reflector",
                      "finalizer" mapping to the model slug for each agent.
        blind_enabled: If True, run Blind Labeler A and B for anchoring measurement.

    Returns:
        A dict containing all intermediate outputs, the final report,
        and the evaluation metrics for this run.
    """
    policy_name = policy_path.stem
    policy_text = policy_path.read_text(encoding="utf-8", errors="replace")

    print(f"\n{'='*60}")
    print(f"Policy: {policy_name}")
    for agent, model in agent_models.items():
        print(f"  {agent}: {model}")
    print(f"{'='*60}")

    # ------------------------------------------------------------------
    # Step 1: Extractor (Agent 1)
    # ------------------------------------------------------------------
    print("\n[Agent 1] Extractor — identifying purpose limitation clauses...")
    extractor_output = run_extractor(
        client, policy_name, policy_text,
        model=agent_models["extractor"],
        scout_model=agent_models["scout"],
    )
    clause_count = len(extractor_output.get("extracted_clauses", []))
    print(f"  Extracted {clause_count} clause(s).")

    # ------------------------------------------------------------------
    # Step 2: String-Match Verifier
    # ------------------------------------------------------------------
    print("\n[Verifier] Checking clause quotes against policy text...")
    verified_clauses, flagged_clauses = verify_clauses(
        extractor_output.get("extracted_clauses", []),
        policy_text,
    )
    print(f"  Verified: {len(verified_clauses)}  |  Flagged: {len(flagged_clauses)}")

    # Build run provenance once, now that the verified clause count is known.
    # Used by both the empty-result early return and the normal result below.
    run_metadata = build_run_metadata(
        policy_path=policy_path,
        temperature=LABELER_TEMPERATURE,
        blind_enabled=blind_enabled,
        clause_count=len(verified_clauses),
    )

    if flagged_clauses:
        for fc in flagged_clauses:
            print(f"  ! Flagged: {fc.get('clause_id')} — {fc.get('verification_note', '')[:80]}")

    if not verified_clauses:
        print("  WARNING: No verified clauses. Pipeline cannot continue with evaluation.")
        return _empty_result(policy_name, extractor_output, flagged_clauses, run_metadata)

    # ------------------------------------------------------------------
    # Step 3: Evaluator (Agent 2) — with retry support
    # ------------------------------------------------------------------
    print("\n[Agent 2] Evaluator — assessing clauses against purpose limitation rubric...")
    evaluator_output = run_evaluator(client, verified_clauses, model=agent_models["evaluator"])
    print(f"  Evaluated {len(evaluator_output.get('evaluations', []))} clause(s).")
    print(f"  Overall label: {evaluator_output.get('overall_label', 'N/A')}")

    # ------------------------------------------------------------------
    # Step 4: Dual Reflectors (Agents 3A & 3B) — parallel independent audit
    # ------------------------------------------------------------------
    print("\n[Agent 3A] Reflector A — independent audit of Agents 1 & 2...")
    reflector_a_initial = run_reflector(
        client, verified_clauses, flagged_clauses, evaluator_output,
        model=agent_models["reflector_a"]
    )
    print(f"  Reflector A status: {reflector_a_initial.get('review_status')}  "
          f"| Errors: {len(reflector_a_initial.get('errors', []))}")

    print("\n[Agent 3B] Reflector B — independent audit of Agents 1 & 2...")
    reflector_b_initial = run_reflector(
        client, verified_clauses, flagged_clauses, evaluator_output,
        model=agent_models["reflector_b"]
    )
    print(f"  Reflector B status: {reflector_b_initial.get('review_status')}  "
          f"| Errors: {len(reflector_b_initial.get('errors', []))}")

    initial_reflector_output = merge_reflector_outputs(reflector_a_initial, reflector_b_initial)
    agreement = initial_reflector_output.get("agreement_rate", 1.0)
    print(f"\n  [Merge] Status: {initial_reflector_output['review_status']}  "
          f"| Total unique errors: {len(initial_reflector_output.get('errors', []))}  "
          f"| Agreement rate: {agreement:.0%}  "
          f"(both={initial_reflector_output['both_flagged_count']}, "
          f"A-only={initial_reflector_output['a_only_count']}, "
          f"B-only={initial_reflector_output['b_only_count']})")

    # ------------------------------------------------------------------
    # Blind Labelers + Label Panel
    # ------------------------------------------------------------------
    blind_a_output = None
    blind_b_output = None
    if blind_enabled:
        print("\n[Blind Labeler A] Independent (unanchored) labeling...")
        blind_a_output = run_blind_labeler(
            client, verified_clauses, model=agent_models["blind_a"]
        )
        print(f"  Blind A labeled {len(blind_a_output.get('labels', []))} clause(s).")

        print("\n[Blind Labeler B] Independent (unanchored) labeling...")
        blind_b_output = run_blind_labeler(
            client, verified_clauses, model=agent_models["blind_b"]
        )
        print(f"  Blind B labeled {len(blind_b_output.get('labels', []))} clause(s).")
    else:
        print("\n[Blind Labeler] Disabled for this run.")

    label_panel = build_label_panel(
        evaluator_output=evaluator_output,
        reflector_a=reflector_a_initial,
        reflector_b=reflector_b_initial,
        blind_a=blind_a_output,
        blind_b=blind_b_output,
        models=agent_models,
        blind_enabled=blind_enabled,
    )
    print("\n[Label Panel] Assembling per-clause labels...")
    print(f"  {label_panel['disputed_count']} disputed clause(s).")
    if blind_enabled and label_panel.get("anchoring_summary"):
        for ref_key in ("reflector_a", "reflector_b"):
            summary = label_panel["anchoring_summary"][ref_key]
            rate = summary["shift_rate"]
            rate_str = f"{rate:.0%}" if rate is not None else "n/a"
            print(f"  [Anchoring] {ref_key} ({summary['model']}): "
                  f"{summary['clauses_changed']}/{summary['total']} changed ({rate_str}).")

    final_reflector_output = initial_reflector_output
    retry_count = 0

    if initial_reflector_output.get("review_status") == "errors_found":
        errors = initial_reflector_output.get("errors", [])
        print(f"\n  Found {len(errors)} unique error(s). Initiating retry loop...")

        agent1_errors = errors_for_agent(initial_reflector_output, "1")
        agent2_errors = errors_for_agent(initial_reflector_output, "2")

        for attempt in range(1, MAX_RETRIES + 1):
            print(f"  Retry {attempt}/{MAX_RETRIES}...")
            retried = False

            if agent1_errors:
                instructions = build_retry_instructions(agent1_errors)
                print(f"    Re-running Agent 1 ({len(agent1_errors)} error(s))...")
                extractor_output = run_extractor(
                    client, policy_name, policy_text,
                    model=agent_models["extractor"],
                    scout_model=agent_models["scout"],
                    retry_instructions=instructions,
                )
                verified_clauses, flagged_clauses = verify_clauses(
                    extractor_output.get("extracted_clauses", []), policy_text
                )
                retried = True

            if agent2_errors:
                instructions = build_retry_instructions(agent2_errors)
                print(f"    Re-running Agent 2 ({len(agent2_errors)} error(s))...")
                evaluator_output = run_evaluator(
                    client, verified_clauses,
                    model=agent_models["evaluator"], retry_instructions=instructions
                )
                retried = True

            if retried:
                ref_a = run_reflector(
                    client, verified_clauses, flagged_clauses, evaluator_output,
                    model=agent_models["reflector_a"]
                )
                ref_b = run_reflector(
                    client, verified_clauses, flagged_clauses, evaluator_output,
                    model=agent_models["reflector_b"]
                )
                final_reflector_output = merge_reflector_outputs(ref_a, ref_b)
                final_reflector_output["retry_count"] = attempt
                retry_count = attempt

                if final_reflector_output.get("review_status") == "clean":
                    print(f"  Errors resolved after {attempt} retry(ies).")
                    break

                agent1_errors = errors_for_agent(final_reflector_output, "1")
                agent2_errors = errors_for_agent(final_reflector_output, "2")
            else:
                break

        if final_reflector_output.get("review_status") != "clean":
            print(f"  WARNING: {len(final_reflector_output.get('errors', []))} error(s) "
                  f"remain unresolved after {MAX_RETRIES} retries. Flagging for human review.")
            final_reflector_output["_retries_exhausted"] = True
    else:
        print("  Both reflectors clean. No retries needed.")

    # ------------------------------------------------------------------
    # Step 5: Finalizer (Agent 4)
    # ------------------------------------------------------------------
    print("\n[Agent 4] Finalizer — consolidating compliance report...")
    finalizer_output = run_finalizer(
        client=client,
        policy_name=policy_name,
        extractor_output=extractor_output,
        verified_clauses=verified_clauses,
        flagged_clauses=flagged_clauses,
        evaluator_output=evaluator_output,
        reflector_output=final_reflector_output,
        model=agent_models["finalizer"],
    )
    print(f"  Final label: {finalizer_output.get('overall_label')} "
          f"(confidence: {finalizer_output.get('confidence')})")

    annotate_finalizer_with_disputes(finalizer_output, label_panel)

    return {
        "run_metadata": run_metadata,
        "policy_name": policy_name,
        "agent_models": agent_models,
        "extractor_output": extractor_output,
        "verified_clauses": verified_clauses,
        "flagged_clauses": flagged_clauses,
        "evaluator_output": evaluator_output,
        "reflector_a_initial": reflector_a_initial,
        "reflector_b_initial": reflector_b_initial,
        "initial_reflector_output": initial_reflector_output,   # merged
        "final_reflector_output": final_reflector_output,       # merged after retries
        "retry_count": retry_count,
        "finalizer_output": finalizer_output,
        "label_panel": label_panel,
        "blind_a_output": blind_a_output,
        "blind_b_output": blind_b_output,
    }




def save_result(result: dict, output_dir: Path, run_index: int = 1) -> Path:
    """Save a run result to a JSON file, a markdown report, and the cumulative
    model usage log. Returns the JSON path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    policy_name = result.get("policy_name", "unknown")

    # Unique, time-based run id from run_metadata (falls back to run{N} if absent).
    run_id = result.get("run_metadata", {}).get("run_id") or f"run{run_index}"
    # Distinguish multiple runs within one invocation (--runs N>1).
    multi_suffix = f"-run{run_index}" if run_index > 1 else ""
    stem = f"{policy_name}_{run_id}{multi_suffix}"

    # JSON — full machine-readable output
    json_path = output_dir / f"{stem}.json"
    json_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    # Markdown — human-readable report
    report_path = output_dir / f"{stem}_report.md"
    generate_report(result, report_path)

    # Cumulative model usage log — append one row per run for easy comparison
    _append_model_usage_log(result, output_dir, run_index)

    print(f"\nJSON saved to:   {json_path}")
    print(f"Report saved to: {report_path}")
    return json_path


def _append_model_usage_log(result: dict, output_dir: Path, run_index: int) -> None:
    """Append one entry to output/model_usage_log.md for cross-run comparison."""
    import datetime

    log_path = output_dir / "model_usage_log.md"
    agent_models = result.get("agent_models", {})
    policy_name = result.get("policy_name", "unknown")
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    overall_label = result.get("finalizer_output", {}).get("overall_label", "N/A")
    retry_count = result.get("retry_count", 0)
    clause_count = len(result.get("verified_clauses", []))

    # Write header if file does not exist yet
    if not log_path.exists():
        header = (
            "# Model Usage Log\n\n"
            "One row per pipeline run. Use this to compare model choices across runs.\n\n"
            "| Run | Date | Policy | Scout | Extractor | Evaluator | "
            "Reflector A | Reflector B | Finalizer | "
            "Clauses | Label | Retries |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|---|\n"
        )
        log_path.write_text(header, encoding="utf-8")

    row = (
        f"| {run_index} | {timestamp} | {policy_name} "
        f"| {agent_models.get('scout', 'N/A')} "
        f"| {agent_models.get('extractor', 'N/A')} "
        f"| {agent_models.get('evaluator', 'N/A')} "
        f"| {agent_models.get('reflector_a', 'N/A')} "
        f"| {agent_models.get('reflector_b', 'N/A')} "
        f"| {agent_models.get('finalizer', 'N/A')} "
        f"| {clause_count} | {overall_label} | {retry_count} |\n"
    )

    with log_path.open("a", encoding="utf-8") as f:
        f.write(row)

    print(f"Model log updated: {log_path}")


def _empty_result(policy_name: str, extractor_output: dict, flagged_clauses: list,
                  run_metadata: dict) -> dict:
    return {
        "run_metadata": run_metadata,
        "policy_name": policy_name,
        "error": "No verified clauses — all extracted clauses failed string-match verification.",
        "extractor_output": extractor_output,
        "flagged_clauses": flagged_clauses,
    }


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="GDPR Article 5(1)(b) Purpose Limitation Compliance Workflow"
    )
    parser.add_argument(
        "--policy",
        required=True,
        help="Path to the privacy policy text file (.txt)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Number of times to run the pipeline (for label stability / M3 measurement). Default: 1.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=(
            f"OpenRouter model slug for all agents (global default). "
            f"Default: {DEFAULT_MODEL}. "
            "Overridden per-agent by --model-extractor / --model-evaluator / etc."
        ),
    )
    parser.add_argument(
        "--model-scout",
        default=None,
        metavar="MODEL",
        help="Model for Pass 1 Scout (section identifier inside Agent 1). Overrides --model.",
    )
    parser.add_argument(
        "--model-extractor",
        default=None,
        metavar="MODEL",
        help="Model for Agent 1 Pass 2 (Deep Extractor). Overrides --model.",
    )
    parser.add_argument(
        "--model-evaluator",
        default=None,
        metavar="MODEL",
        help="Model for Agent 2 (Evaluator). Overrides --model.",
    )
    parser.add_argument(
        "--model-reflector-a",
        default=None,
        metavar="MODEL",
        help="Model for Agent 3A (Reflector A). Overrides --model.",
    )
    parser.add_argument(
        "--model-reflector-b",
        default=None,
        metavar="MODEL",
        help="Model for Agent 3B (Reflector B). Overrides --model.",
    )
    parser.add_argument(
        "--model-finalizer",
        default=None,
        metavar="MODEL",
        help="Model for Agent 4 (Finalizer). Overrides --model.",
    )
    parser.add_argument(
        "--no-blind-labeler",
        action="store_true",
        help="Disable the Blind Labeler tier for this run (skips 2 LLM calls; "
             "label panel still records evaluator + reflector labels).",
    )
    parser.add_argument(
        "--output-dir",
        default="output/results",
        help="Directory to save result JSON files. Default: output/results/",
    )
    args = parser.parse_args()

    policy_path = Path(args.policy)
    if not policy_path.exists():
        print(f"ERROR: Policy file not found: {policy_path}", file=sys.stderr)
        sys.exit(1)

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)
    output_dir = Path(args.output_dir)

    # Resolve per-agent models: explicit --model-X > config default > global --model
    def _resolve(agent: str, cli_override) -> str:
        return cli_override or DEFAULT_AGENT_MODELS.get(agent) or args.model

    agent_models = {
        "scout":       _resolve("scout",       args.model_scout),
        "extractor":   _resolve("extractor",   args.model_extractor),
        "evaluator":   _resolve("evaluator",   args.model_evaluator),
        "reflector_a": _resolve("reflector_a", args.model_reflector_a),
        "reflector_b": _resolve("reflector_b", args.model_reflector_b),
        "finalizer":   _resolve("finalizer",   args.model_finalizer),
        "blind_a":     _resolve("blind_a",     None),
        "blind_b":     _resolve("blind_b",     None),
    }

    all_results = []
    for run_i in range(1, args.runs + 1):
        if args.runs > 1:
            print(f"\n{'#'*60}")
            print(f"# Run {run_i} of {args.runs}")
            print(f"{'#'*60}")

        blind_enabled = ENABLE_BLIND_LABELER and not args.no_blind_labeler
        result = run_pipeline(
            client, policy_path, agent_models=agent_models, blind_enabled=blind_enabled
        )
        save_result(result, output_dir, run_index=run_i)
        all_results.append(result)



if __name__ == "__main__":
    main()
