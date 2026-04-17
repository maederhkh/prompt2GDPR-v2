"""
Evaluation metrics for the agentic GDPR purpose limitation workflow.

Adapted from the four metrics used in the thesis (RAS/JJS, FGS, flip rate, OQS-S)
plus a new agentic-specific metric (M5: Reflector Correction Rate).

Metric reference:
  M1 — Rubric Alignment Score (adapted RAS): % of rubric criteria correctly assessed.
  M2 — Evidence Grounding Score (adapted FGS): % of clauses verified + grounded.
  M3 — Label Stability (adapted flip rate): label changes across runs / retries.
  M4 — Structural Completeness (adapted OQS-S): schema field completeness per agent.
  M5 — Reflector Correction Rate (new): errors resolved / total errors flagged.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# M1: Rubric Alignment Score
# ---------------------------------------------------------------------------

STAGE_1_CRITERIA = ("specific", "explicit", "legitimate", "determined_at_collection")
STAGE_2_CRITERIA = (
    "purpose_link", "context_consistent", "data_nature_considered",
    "impact_assessed", "safeguards_present",
)
ARTICLE_89_CRITERIA = (
    "exception_explicitly_claimed", "safeguards_stated", "purpose_genuine",
)

VALID_ANSWERS = {"yes", "no", "partial"}


def m1_rubric_alignment(evaluator_output: dict) -> dict:
    """
    M1: Rubric Alignment Score.

    For each evaluation, count the proportion of rubric criteria that have a
    valid, non-null answer. A criterion answered as "yes", "no", or "partial"
    is considered assessed (regardless of correctness — correctness requires
    human expert ground truth). This measures structural rubric coverage.

    Returns:
        {
          "per_clause": {clause_id: score_0_to_1},
          "overall_score": float,          # mean across all clauses
          "total_criteria_assessed": int,
          "total_criteria_possible": int,
        }
    """
    evaluations = evaluator_output.get("evaluations", [])
    if not evaluations:
        return {"per_clause": {}, "overall_score": 0.0,
                "total_criteria_assessed": 0, "total_criteria_possible": 0}

    per_clause: dict[str, float] = {}
    total_assessed = 0
    total_possible = 0

    for ev in evaluations:
        clause_id = ev.get("clause_id", "unknown")
        assessed = 0
        possible = 0

        # Stage 1 — always applicable
        stage_1 = ev.get("stage_1", {})
        for crit in STAGE_1_CRITERIA:
            possible += 1
            if stage_1.get(crit, "").lower() in VALID_ANSWERS:
                assessed += 1

        # Stage 2 — only if applicable
        if ev.get("stage_2_applicable", False):
            stage_2 = ev.get("stage_2", {})
            for crit in STAGE_2_CRITERIA:
                possible += 1
                if stage_2.get(crit, "").lower() in VALID_ANSWERS:
                    assessed += 1

        # Article 89 — only if exception flagged
        if ev.get("article_89_exception", False):
            art89 = ev.get("article_89_assessment", {})
            for crit in ARTICLE_89_CRITERIA:
                possible += 1
                if art89.get(crit, "").lower() in VALID_ANSWERS:
                    assessed += 1

        score = assessed / possible if possible > 0 else 0.0
        per_clause[clause_id] = round(score, 4)
        total_assessed += assessed
        total_possible += possible

    overall = total_assessed / total_possible if total_possible > 0 else 0.0
    return {
        "per_clause": per_clause,
        "overall_score": round(overall, 4),
        "total_criteria_assessed": total_assessed,
        "total_criteria_possible": total_possible,
    }


# ---------------------------------------------------------------------------
# M2: Evidence Grounding Score
# ---------------------------------------------------------------------------

def m2_evidence_grounding(
    verified_clauses: list[dict],
    flagged_clauses: list[dict],
    evaluator_output: dict,
) -> dict:
    """
    M2: Evidence Grounding Score (adapted FGS).

    Two sub-scores:
    - Verifier pass rate: % of Agent 1 clauses that passed string-match verification.
    - Evaluator grounding rate: % of Evaluator evaluations whose clause_id maps to
      a verified clause (not a phantom).

    Returns:
        {
          "verifier_pass_rate": float,        # verified / (verified + flagged)
          "evaluator_grounding_rate": float,  # grounded evals / total evals
          "verified_count": int,
          "flagged_count": int,
          "phantom_count": int,               # evals referencing non-verified clause_ids
        }
    """
    verified_ids = {c.get("clause_id") for c in verified_clauses}
    total_extracted = len(verified_clauses) + len(flagged_clauses)

    verifier_pass_rate = (
        len(verified_clauses) / total_extracted if total_extracted > 0 else 0.0
    )

    evaluations = evaluator_output.get("evaluations", [])
    phantom_count = sum(
        1 for ev in evaluations if ev.get("clause_id") not in verified_ids
    )
    grounding_rate = (
        (len(evaluations) - phantom_count) / len(evaluations)
        if evaluations else 0.0
    )

    return {
        "verifier_pass_rate": round(verifier_pass_rate, 4),
        "evaluator_grounding_rate": round(grounding_rate, 4),
        "verified_count": len(verified_clauses),
        "flagged_count": len(flagged_clauses),
        "phantom_count": phantom_count,
    }


# ---------------------------------------------------------------------------
# M3: Label Stability
# ---------------------------------------------------------------------------

def m3_label_stability(
    run_results: list[dict],
    label_field: str = "overall_label",
) -> dict:
    """
    M3: Label Stability (adapted flip rate).

    Compare overall_label (or any label field) across multiple runs of the
    same workflow on the same policy. A "flip" occurs when the label differs
    between two runs.

    Args:
        run_results: List of finalizer output dicts, one per run.
        label_field: The field to track for stability.

    Returns:
        {
          "labels_per_run": [str, ...],
          "flip_count": int,
          "total_comparisons": int,
          "flip_rate": float,    # flips / total_comparisons (0.0 = perfectly stable)
          "is_stable": bool,
        }
    """
    labels = [r.get(label_field, "MISSING") for r in run_results]
    n = len(labels)
    if n < 2:
        return {
            "labels_per_run": labels,
            "flip_count": 0,
            "total_comparisons": 0,
            "flip_rate": 0.0,
            "is_stable": True,
        }

    # Count consecutive flips
    flips = sum(1 for i in range(n - 1) if labels[i] != labels[i + 1])
    total_comparisons = n - 1
    flip_rate = flips / total_comparisons

    return {
        "labels_per_run": labels,
        "flip_count": flips,
        "total_comparisons": total_comparisons,
        "flip_rate": round(flip_rate, 4),
        "is_stable": flip_rate == 0.0,
    }


# ---------------------------------------------------------------------------
# M4: Structural Completeness
# ---------------------------------------------------------------------------

EXTRACTOR_REQUIRED_FIELDS = {"policy_name", "extracted_clauses", "extraction_notes"}
EVALUATOR_REQUIRED_FIELDS = {"evaluations", "overall_label", "overall_justification"}
REFLECTOR_REQUIRED_FIELDS = {"review_status", "errors", "reflector_notes"}
FINALIZER_REQUIRED_FIELDS = {
    "policy_name", "assessment_date", "principle_assessed",
    "overall_label", "confidence", "clause_assessments",
    "key_findings", "identified_gaps", "unresolved_flags",
    "human_review_recommended", "human_review_notes",
}


def m4_structural_completeness(
    extractor_output: dict,
    evaluator_output: dict,
    reflector_a_output: dict,
    reflector_b_output: dict,
    finalizer_output: dict,
) -> dict:
    """
    M4: Structural Completeness (adapted OQS-S).

    For each agent output, compute the proportion of required schema fields
    that are present and non-null. Both reflectors are scored individually;
    the reflector score is their average.

    Returns:
        {
          "extractor_score": float,
          "evaluator_score": float,
          "reflector_a_score": float,
          "reflector_b_score": float,
          "reflector_score": float,   # average of A and B
          "finalizer_score": float,
          "overall_score": float,
          "missing_fields": {agent_name: [field, ...]},
        }
    """
    def score_fields(data: dict, required: set) -> tuple[float, list[str]]:
        missing = [f for f in required if f not in data or data[f] is None]
        s = (len(required) - len(missing)) / len(required) if required else 1.0
        return round(s, 4), missing

    ext_score,   ext_missing   = score_fields(extractor_output,  EXTRACTOR_REQUIRED_FIELDS)
    eval_score,  eval_missing  = score_fields(evaluator_output,  EVALUATOR_REQUIRED_FIELDS)
    ref_a_score, ref_a_missing = score_fields(reflector_a_output, REFLECTOR_REQUIRED_FIELDS)
    ref_b_score, ref_b_missing = score_fields(reflector_b_output, REFLECTOR_REQUIRED_FIELDS)
    fin_score,   fin_missing   = score_fields(finalizer_output,  FINALIZER_REQUIRED_FIELDS)

    ref_avg = round((ref_a_score + ref_b_score) / 2, 4)
    overall = round((ext_score + eval_score + ref_avg + fin_score) / 4, 4)

    return {
        "extractor_score":  ext_score,
        "evaluator_score":  eval_score,
        "reflector_a_score": ref_a_score,
        "reflector_b_score": ref_b_score,
        "reflector_score":  ref_avg,
        "finalizer_score":  fin_score,
        "overall_score":    overall,
        "missing_fields": {
            "extractor":   ext_missing,
            "evaluator":   eval_missing,
            "reflector_a": ref_a_missing,
            "reflector_b": ref_b_missing,
            "finalizer":   fin_missing,
        },
    }


# ---------------------------------------------------------------------------
# M5: Reflector Correction Rate (new agentic metric)
# ---------------------------------------------------------------------------

def m5_reflector_correction_rate(
    initial_reflector_output: dict,
    final_reflector_output: dict,
) -> dict:
    """
    M5: Reflector Correction Rate (extended for dual-reflector setup).

    Measures what proportion of errors flagged by the merged Reflectors on the
    first review were successfully resolved after retries. Also captures the
    inter-reflector agreement rate from the initial merged output.

    Args:
        initial_reflector_output: Merged reflector output from the first review pass.
        final_reflector_output: Merged reflector output from the final review pass
                                (after retries, or same as initial if no retries).

    Returns:
        {
          "initial_error_count": int,
          "final_error_count": int,
          "resolved_count": int,
          "correction_rate": float,     # resolved / initial (1.0 = all fixed)
          "agreement_rate": float,      # inter-reflector agreement on initial pass
          "both_flagged_count": int,    # errors caught by both reflectors
          "a_only_count": int,
          "b_only_count": int,
          "retries_exhausted": bool,
        }
    """
    initial_errors = initial_reflector_output.get("errors", [])
    final_errors = final_reflector_output.get("errors", [])
    retries_exhausted = final_reflector_output.get("_retries_exhausted", False)

    initial_count = len(initial_errors)
    final_count = len(final_errors)
    resolved = max(0, initial_count - final_count)
    rate = resolved / initial_count if initial_count > 0 else 1.0

    return {
        "initial_error_count": initial_count,
        "final_error_count": final_count,
        "resolved_count": resolved,
        "correction_rate": round(rate, 4),
        "agreement_rate": initial_reflector_output.get("agreement_rate", 1.0),
        "both_flagged_count": initial_reflector_output.get("both_flagged_count", 0),
        "a_only_count": initial_reflector_output.get("a_only_count", 0),
        "b_only_count": initial_reflector_output.get("b_only_count", 0),
        "retries_exhausted": retries_exhausted,
    }


# ---------------------------------------------------------------------------
# Aggregate: compute all metrics for a single run
# ---------------------------------------------------------------------------

def compute_all_metrics(
    extractor_output: dict,
    verified_clauses: list[dict],
    flagged_clauses: list[dict],
    evaluator_output: dict,
    reflector_a_initial: dict,
    reflector_b_initial: dict,
    initial_reflector_output: dict,
    final_reflector_output: dict,
    finalizer_output: dict,
) -> dict:
    """
    Compute all five metrics for a single pipeline run and return as one dict.

    Args:
        reflector_a_initial: Raw output from Reflector A (first pass, pre-merge).
        reflector_b_initial: Raw output from Reflector B (first pass, pre-merge).
        initial_reflector_output: Merged reflector output from the first pass.
        final_reflector_output: Merged reflector output after retries.
    """
    return {
        "M1_rubric_alignment": m1_rubric_alignment(evaluator_output),
        "M2_evidence_grounding": m2_evidence_grounding(
            verified_clauses, flagged_clauses, evaluator_output
        ),
        "M3_label_stability": None,  # requires multiple runs; computed separately
        "M4_structural_completeness": m4_structural_completeness(
            extractor_output, evaluator_output,
            reflector_a_initial, reflector_b_initial,
            finalizer_output
        ),
        "M5_reflector_correction_rate": m5_reflector_correction_rate(
            initial_reflector_output, final_reflector_output
        ),
    }
