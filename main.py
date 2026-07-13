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
import csv
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
from utils.runs_index import append_run_to_index, build_index_row
from agents.blind_labeler import run_blind_labeler
from utils.label_panel import build_label_panel, annotate_finalizer_with_disputes
from config import DEFAULT_MODEL, DEFAULT_AGENT_MODELS, OPENROUTER_BASE_URL, ENABLE_BLIND_LABELER, LABELER_TEMPERATURE
from utils.verifier import verify_clauses
from utils.report_generator import generate_report
from utils.review_report import write_review_report
from utils.run_trace import RunTrace
from utils.usage_meter import UsageMeter, MeteredClient
from utils.policy_loader import load_policy_text, SUPPORTED_EXTENSIONS, discover_policy_files
from utils.batch_comparison import build_comparison_md, build_comparison_csv_rows

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
    policy_text = load_policy_text(policy_path)
    trace = RunTrace()
    meter = UsageMeter()
    client = MeteredClient(client, meter)  # meter every agent LLM call; agents unchanged

    print(f"\n{'='*60}")
    print(f"Policy: {policy_name}")
    for agent, model in agent_models.items():
        print(f"  {agent}: {model}")
    print(f"{'='*60}")

    # ------------------------------------------------------------------
    # Step 1: Extractor (Agent 1)
    # ------------------------------------------------------------------
    print("\n[Agent 1] Extractor — identifying purpose limitation clauses...")
    with trace.step("extractor", model=agent_models["extractor"]), meter.stage("extractor"):
        extractor_output = run_extractor(
            client, policy_name, policy_text,
            model=agent_models["extractor"],
            scout_model=agent_models["scout"],
        )
    if "scout_report" not in extractor_output:
        trace.mark_last(status="fallback", note="single-pass fallback (no Scout)")
    clause_count = len(extractor_output.get("extracted_clauses", []))
    print(f"  Extracted {clause_count} clause(s).")

    # ------------------------------------------------------------------
    # Step 2: String-Match Verifier
    # ------------------------------------------------------------------
    print("\n[Verifier] Checking clause quotes against policy text...")
    with trace.step("verifier"), meter.stage("verifier"):
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
        return _empty_result(policy_name, extractor_output, flagged_clauses, run_metadata, trace.events, meter.to_dict())

    # ------------------------------------------------------------------
    # Step 3: Evaluator (Agent 2) — with retry support
    # ------------------------------------------------------------------
    print("\n[Agent 2] Evaluator — assessing clauses against purpose limitation rubric...")
    with trace.step("evaluator", model=agent_models["evaluator"]), meter.stage("evaluator"):
        evaluator_output = run_evaluator(client, verified_clauses, model=agent_models["evaluator"])
    print(f"  Evaluated {len(evaluator_output.get('evaluations', []))} clause(s).")
    print(f"  Overall label: {evaluator_output.get('overall_label', 'N/A')}")

    # ------------------------------------------------------------------
    # Step 4: Dual Reflectors (Agents 3A & 3B) — parallel independent audit
    # ------------------------------------------------------------------
    print("\n[Agent 3A] Reflector A — independent audit of Agents 1 & 2...")
    with trace.step("reflector_a", model=agent_models["reflector_a"]), meter.stage("reflector_a"):
        reflector_a_initial = run_reflector(
            client, verified_clauses, flagged_clauses, evaluator_output,
            model=agent_models["reflector_a"]
        )
    print(f"  Reflector A status: {reflector_a_initial.get('review_status')}  "
          f"| Errors: {len(reflector_a_initial.get('errors', []))}")

    print("\n[Agent 3B] Reflector B — independent audit of Agents 1 & 2...")
    with trace.step("reflector_b", model=agent_models["reflector_b"]), meter.stage("reflector_b"):
        reflector_b_initial = run_reflector(
            client, verified_clauses, flagged_clauses, evaluator_output,
            model=agent_models["reflector_b"]
        )
    print(f"  Reflector B status: {reflector_b_initial.get('review_status')}  "
          f"| Errors: {len(reflector_b_initial.get('errors', []))}")

    with trace.step("merge"), meter.stage("merge"):
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
        with trace.step("blind_a", model=agent_models["blind_a"]), meter.stage("blind_a"):
            blind_a_output = run_blind_labeler(
                client, verified_clauses, model=agent_models["blind_a"]
            )
        print(f"  Blind A labeled {len(blind_a_output.get('labels', []))} clause(s).")

        print("\n[Blind Labeler B] Independent (unanchored) labeling...")
        with trace.step("blind_b", model=agent_models["blind_b"]), meter.stage("blind_b"):
            blind_b_output = run_blind_labeler(
                client, verified_clauses, model=agent_models["blind_b"]
            )
        print(f"  Blind B labeled {len(blind_b_output.get('labels', []))} clause(s).")
    else:
        print("\n[Blind Labeler] Disabled for this run.")

    with trace.step("label_panel"), meter.stage("label_panel"):
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
                with trace.step(f"extractor (retry {attempt})", model=agent_models["extractor"]), meter.stage(f"extractor (retry {attempt})"):
                    extractor_output = run_extractor(
                        client, policy_name, policy_text,
                        model=agent_models["extractor"],
                        scout_model=agent_models["scout"],
                        retry_instructions=instructions,
                    )
                trace.mark_last(status="retry", note=f"re-run: {len(agent1_errors)} Agent-1 error(s)")
                with trace.step(f"verifier (retry {attempt})"), meter.stage(f"verifier (retry {attempt})"):
                    verified_clauses, flagged_clauses = verify_clauses(
                        extractor_output.get("extracted_clauses", []), policy_text
                    )
                trace.mark_last(status="retry")
                retried = True

            if agent2_errors:
                instructions = build_retry_instructions(agent2_errors)
                print(f"    Re-running Agent 2 ({len(agent2_errors)} error(s))...")
                with trace.step(f"evaluator (retry {attempt})", model=agent_models["evaluator"]), meter.stage(f"evaluator (retry {attempt})"):
                    evaluator_output = run_evaluator(
                        client, verified_clauses,
                        model=agent_models["evaluator"], retry_instructions=instructions
                    )
                trace.mark_last(status="retry", note=f"re-run: {len(agent2_errors)} Agent-2 error(s)")
                retried = True

            if retried:
                with trace.step(f"reflector_a (retry {attempt})", model=agent_models["reflector_a"]), meter.stage(f"reflector_a (retry {attempt})"):
                    ref_a = run_reflector(
                        client, verified_clauses, flagged_clauses, evaluator_output,
                        model=agent_models["reflector_a"]
                    )
                trace.mark_last(status="retry")
                with trace.step(f"reflector_b (retry {attempt})", model=agent_models["reflector_b"]), meter.stage(f"reflector_b (retry {attempt})"):
                    ref_b = run_reflector(
                        client, verified_clauses, flagged_clauses, evaluator_output,
                        model=agent_models["reflector_b"]
                    )
                trace.mark_last(status="retry")
                with trace.step(f"merge (retry {attempt})"), meter.stage(f"merge (retry {attempt})"):
                    final_reflector_output = merge_reflector_outputs(ref_a, ref_b)
                trace.mark_last(status="retry")
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
    with trace.step("finalizer", model=agent_models["finalizer"]), meter.stage("finalizer"):
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
        "run_trace": trace.events,
        "token_usage": meter.to_dict(),
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




def _write_review_brief(result: dict, output_dir: Path, stem: str):
    """Write <stem>_review.md next to the full report. Convenience artifact —
    a failure here must never fail an otherwise-successful run (mirrors how
    append_run_to_index treats index failures as non-fatal)."""
    try:
        review_path = output_dir / f"{stem}_review.md"
        write_review_report(result, review_path)
        return review_path
    except Exception as exc:  # convenience output must not crash a run
        print(f"  [warn] could not write review brief: {exc}")
        return None


def save_result(result: dict, output_dir: Path, run_index: int = 1) -> Path:
    """Save a run result to a JSON file, a markdown report, and the cumulative
    runs index (md + csv). Returns the JSON path."""
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

    # Markdown — reviewer-focused brief (convenience artifact; never fatal)
    review_path = _write_review_brief(result, output_dir, stem)

    # Cumulative runs index — append one summary row per run (md + csv)
    append_run_to_index(result, output_dir)

    print(f"\nJSON saved to:   {json_path}")
    print(f"Report saved to: {report_path}")
    if review_path is not None:
        print(f"Review saved to: {review_path}")
    return json_path


def _empty_result(policy_name: str, extractor_output: dict, flagged_clauses: list,
                  run_metadata: dict, run_trace: list, token_usage: dict) -> dict:
    return {
        "run_metadata": run_metadata,
        "run_trace": run_trace,
        "token_usage": token_usage,
        "policy_name": policy_name,
        "error": "No verified clauses — all extracted clauses failed string-match verification.",
        "extractor_output": extractor_output,
        "flagged_clauses": flagged_clauses,
    }


def _write_batch_comparison(entries: list, output_dir: Path) -> None:
    """Write comparison_<batch_label>.md and .csv for one batch run.

    batch_label is the run_id of the first entry that has a row (ok or empty);
    "failed" if every policy failed. Never fatal — the per-policy JSON/report
    and the cumulative runs index remain the source of truth.
    """
    try:
        batch_label = next(
            (e["row"]["run_id"] for e in entries if e.get("row")), "failed"
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        md_path = output_dir / f"comparison_{batch_label}.md"
        csv_path = output_dir / f"comparison_{batch_label}.csv"
        md_path.write_text(build_comparison_md(entries, batch_label), encoding="utf-8")
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(build_comparison_csv_rows(entries))
        print(f"\nBatch comparison (md):  {md_path}")
        print(f"Batch comparison (csv): {csv_path}")
    except Exception as exc:  # comparison is a convenience aggregate; never fatal
        print(f"  [batch] WARNING: could not write comparison: {exc}")


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="GDPR Article 5(1)(b) Purpose Limitation Compliance Workflow"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--policy",
        help="Path to a single privacy policy file (.txt/.md/.html/.htm/.pdf/.docx).",
    )
    source.add_argument(
        "--policy-dir",
        help="Path to a folder; runs every supported policy file inside it "
             "(batch/corpus mode). Mutually exclusive with --policy.",
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

    if args.policy_dir:
        batch_mode = True
        policy_dir = Path(args.policy_dir)
        if not policy_dir.is_dir():
            print(f"ERROR: policy directory not found: {policy_dir}", file=sys.stderr)
            sys.exit(1)
        policy_files = discover_policy_files(policy_dir)
        if not policy_files:
            print(
                f"ERROR: no supported policy files "
                f"({' '.join(sorted(SUPPORTED_EXTENSIONS))}) found in {policy_dir}",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"Batch mode: {len(policy_files)} policy file(s) in {policy_dir}")
    else:
        batch_mode = False
        policy_path = Path(args.policy)
        if not policy_path.exists():
            print(f"ERROR: Policy file not found: {policy_path}", file=sys.stderr)
            sys.exit(1)
        if policy_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            print(
                f"ERROR: unsupported policy format '{policy_path.suffix}'; "
                f"supported: {' '.join(sorted(SUPPORTED_EXTENSIONS))}",
                file=sys.stderr,
            )
            sys.exit(1)
        policy_files = [policy_path]

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

    blind_enabled = ENABLE_BLIND_LABELER and not args.no_blind_labeler
    entries = []
    for policy_path in policy_files:
        if batch_mode:
            print(f"\n{'#'*60}")
            print(f"# Policy: {policy_path.name}")
            print(f"{'#'*60}")
        for run_i in range(1, args.runs + 1):
            if args.runs > 1:
                # Preserve the original single-mode run banner verbatim.
                print(f"\n{'#'*60}")
                print(f"# Run {run_i} of {args.runs}")
                print(f"{'#'*60}")
            try:
                result = run_pipeline(
                    client, policy_path,
                    agent_models=agent_models, blind_enabled=blind_enabled,
                )
            except Exception as exc:
                # Single mode preserves prior behavior: report and exit non-zero.
                if not batch_mode:
                    print(f"ERROR: could not read policy: {exc}", file=sys.stderr)
                    sys.exit(1)
                # Batch mode: record the failure and keep going with the rest.
                print(f"  [batch] ERROR: {policy_path.name} failed: {exc} — continuing.",
                      file=sys.stderr)
                entries.append({
                    "policy": policy_path.stem, "run_index": run_i,
                    "status": "failed", "row": None, "error": str(exc),
                })
                continue

            save_result(result, output_dir, run_index=run_i)
            entries.append({
                "policy": policy_path.stem,
                "run_index": run_i,
                "status": "empty" if result.get("error") else "ok",
                "row": build_index_row(result),
                "error": result.get("error"),
            })

    if batch_mode:
        _write_batch_comparison(entries, output_dir)



if __name__ == "__main__":
    main()
