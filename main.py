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
from config import DEFAULT_MODEL, DEFAULT_AGENT_MODELS, OPENROUTER_BASE_URL
from utils.verifier import verify_clauses
from evaluation.metrics import compute_all_metrics, m3_label_stability

MAX_RETRIES = 2


def run_pipeline(client: OpenAI, policy_path: Path, agent_models: dict) -> dict:
    """
    Execute the full 4-agent pipeline for a single policy file.

    Args:
        client: OpenRouter-configured OpenAI client.
        policy_path: Path to the policy text file.
        agent_models: Dict with keys "extractor", "evaluator", "reflector",
                      "finalizer" mapping to the model slug for each agent.

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
    extractor_output = run_extractor(client, policy_name, policy_text, model=agent_models["extractor"])
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
    if flagged_clauses:
        for fc in flagged_clauses:
            print(f"  ! Flagged: {fc.get('clause_id')} — {fc.get('verification_note', '')[:80]}")

    if not verified_clauses:
        print("  WARNING: No verified clauses. Pipeline cannot continue with evaluation.")
        return _empty_result(policy_name, extractor_output, flagged_clauses)

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
                    model=agent_models["extractor"], retry_instructions=instructions
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

    # ------------------------------------------------------------------
    # Step 6: Evaluation metrics
    # ------------------------------------------------------------------
    print("\n[Metrics] Computing M1–M5...")
    metrics = compute_all_metrics(
        extractor_output=extractor_output,
        verified_clauses=verified_clauses,
        flagged_clauses=flagged_clauses,
        evaluator_output=evaluator_output,
        reflector_a_initial=reflector_a_initial,
        reflector_b_initial=reflector_b_initial,
        initial_reflector_output=initial_reflector_output,
        final_reflector_output=final_reflector_output,
        finalizer_output=finalizer_output,
    )
    _print_metrics(metrics)

    return {
        "policy_name": policy_name,
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
        "metrics": metrics,
    }


def _print_metrics(metrics: dict) -> None:
    m1 = metrics.get("M1_rubric_alignment", {})
    m2 = metrics.get("M2_evidence_grounding", {})
    m4 = metrics.get("M4_structural_completeness", {})
    m5 = metrics.get("M5_reflector_correction_rate", {})

    print(f"  M1 Rubric Alignment:       {m1.get('overall_score', 0):.2%}")
    print(f"  M2 Verifier Pass Rate:     {m2.get('verifier_pass_rate', 0):.2%}  "
          f"| Evaluator Grounding: {m2.get('evaluator_grounding_rate', 0):.2%}")
    print(f"  M4 Structural Completeness:{m4.get('overall_score', 0):.2%}")
    print(f"  M5 Reflector Correction:   {m5.get('correction_rate', 0):.2%}  "
          f"(resolved {m5.get('resolved_count', 0)}/{m5.get('initial_error_count', 0)})  "
          f"| Agreement: {m5.get('agreement_rate', 1.0):.2%}")


def save_result(result: dict, output_dir: Path, run_index: int = 1) -> Path:
    """Save a run result to a JSON file and return the file path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    policy_name = result.get("policy_name", "unknown")
    filename = f"{policy_name}_run{run_index}.json"
    out_path = output_dir / filename
    out_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(f"\nResult saved to: {out_path}")
    return out_path


def _empty_result(policy_name: str, extractor_output: dict, flagged_clauses: list) -> dict:
    return {
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
        "--model-extractor",
        default=None,
        metavar="MODEL",
        help="Model for Agent 1 (Extractor). Overrides --model.",
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
        "extractor":   _resolve("extractor",   args.model_extractor),
        "evaluator":   _resolve("evaluator",   args.model_evaluator),
        "reflector_a": _resolve("reflector_a", args.model_reflector_a),
        "reflector_b": _resolve("reflector_b", args.model_reflector_b),
        "finalizer":   _resolve("finalizer",   args.model_finalizer),
    }

    all_results = []
    for run_i in range(1, args.runs + 1):
        if args.runs > 1:
            print(f"\n{'#'*60}")
            print(f"# Run {run_i} of {args.runs}")
            print(f"{'#'*60}")

        result = run_pipeline(client, policy_path, agent_models=agent_models)
        save_result(result, output_dir, run_index=run_i)
        all_results.append(result)

    # Compute M3 label stability if multiple runs
    if args.runs > 1:
        final_outputs = [r.get("finalizer_output", {}) for r in all_results]
        m3 = m3_label_stability(final_outputs, label_field="overall_label")
        print(f"\n{'='*60}")
        print("M3 Label Stability (across all runs):")
        print(f"  Labels:    {m3['labels_per_run']}")
        print(f"  Flips:     {m3['flip_count']} / {m3['total_comparisons']}")
        print(f"  Flip rate: {m3['flip_rate']:.2%}")
        print(f"  Stable:    {m3['is_stable']}")

        # Save M3 to a summary file
        m3_path = output_dir / f"{policy_path.stem}_m3_stability.json"
        m3_path.write_text(json.dumps(m3, indent=2), encoding="utf-8")
        print(f"  Saved M3 report to: {m3_path}")


if __name__ == "__main__":
    main()
