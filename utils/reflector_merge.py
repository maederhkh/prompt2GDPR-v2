"""
Merge the outputs of two independent Reflector agents (A and B).

Deduplication key: (error_type, clause_id, responsible_agent).
- Errors matched by both reflectors → flagged_by = ["A", "B"], agreement = "both"
- Errors from Reflector A only     → flagged_by = ["A"], agreement = "reflector_a_only"
- Errors from Reflector B only     → flagged_by = ["B"], agreement = "reflector_b_only"

The merged review_status is "clean" only when BOTH reflectors report clean.
Agreement rate = errors caught by both / total unique errors.
"""


def merge_reflector_outputs(output_a: dict, output_b: dict) -> dict:
    """
    Merge two independent Reflector outputs into a single consolidated report.

    Args:
        output_a: Parsed output from Reflector A.
        output_b: Parsed output from Reflector B.

    Returns:
        Merged dict with all errors annotated by which reflector(s) caught them,
        plus inter-reflector agreement statistics.
    """
    errors_a = output_a.get("errors", [])
    errors_b = output_b.get("errors", [])
    status_a = output_a.get("review_status", "clean")
    status_b = output_b.get("review_status", "clean")

    # Merged status: "clean" only if both are clean
    merged_status = (
        "clean" if status_a == "clean" and status_b == "clean"
        else "errors_found"
    )

    # Deduplicate by (error_type, clause_id, responsible_agent)
    def _key(e: dict) -> tuple:
        return (
            e.get("error_type", ""),
            str(e.get("clause_id", "")),
            str(e.get("responsible_agent", "")),
        )

    merged: dict[tuple, dict] = {}

    for err in errors_a:
        key = _key(err)
        merged[key] = {**err, "flagged_by": ["A"], "agreement": "reflector_a_only"}

    for err in errors_b:
        key = _key(err)
        if key in merged:
            merged[key]["flagged_by"] = ["A", "B"]
            merged[key]["agreement"] = "both"
        else:
            merged[key] = {**err, "flagged_by": ["B"], "agreement": "reflector_b_only"}

    errors_list = list(merged.values())

    # Agreement statistics
    both_count = sum(1 for e in errors_list if e["agreement"] == "both")
    a_only_count = sum(1 for e in errors_list if e["agreement"] == "reflector_a_only")
    b_only_count = sum(1 for e in errors_list if e["agreement"] == "reflector_b_only")
    total_unique = len(errors_list)
    agreement_rate = both_count / total_unique if total_unique > 0 else 1.0

    # Combine notes
    notes_a = output_a.get("reflector_notes") or ""
    notes_b = output_b.get("reflector_notes") or ""
    merged_notes = f"[Reflector A] {notes_a} | [Reflector B] {notes_b}".strip(" |")

    return {
        "review_status": merged_status,
        "errors": errors_list,
        "reflector_a_status": status_a,
        "reflector_b_status": status_b,
        "agreement_rate": round(agreement_rate, 4),
        "both_flagged_count": both_count,
        "a_only_count": a_only_count,
        "b_only_count": b_only_count,
        "retry_count": 0,
        "reflector_notes": merged_notes,
    }
