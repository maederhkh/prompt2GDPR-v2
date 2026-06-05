"""
Label Panel builder (pure Python, no LLM).

Assembles, per clause, the compliance labels from the Evaluator, both Reflectors
(anchored), and both Blind Labelers (unanchored). Flags disagreement and computes
the per-model anchoring shift (blind vs anchored). Also annotates the Finalizer
output with disputed clauses (non-destructive — the evaluator label stays official).
"""


def _index_evaluator(evaluator_output: dict) -> dict:
    """clause_id -> label from the evaluator's evaluations list."""
    out = {}
    for ev in evaluator_output.get("evaluations", []):
        cid = ev.get("clause_id")
        if cid:
            out[str(cid)] = ev.get("clause_label")
    return out


def _index_labels(output: dict, key: str) -> dict:
    """clause_id -> label from a list under `key` ('clause_labels' or 'labels')."""
    out = {}
    if not isinstance(output, dict):
        return out
    for item in output.get(key, []) or []:
        if isinstance(item, dict) and item.get("clause_id"):
            out[str(item["clause_id"])] = item.get("label")
    return out


def _cell(label, model):
    """Build a {label, model} cell, or None if no label is available."""
    if label is None:
        return None
    return {"label": label, "model": model}


def build_label_panel(
    evaluator_output: dict,
    reflector_a: dict,
    reflector_b: dict,
    blind_a: dict | None,
    blind_b: dict | None,
    models: dict,
    blind_enabled: bool,
) -> dict:
    """
    Build the label panel.

    Args:
        evaluator_output: Agent 2 output (uses "evaluations"[].clause_label).
        reflector_a / reflector_b: Reflector outputs (use "clause_labels").
        blind_a / blind_b: Blind labeler outputs (use "labels"); None if disabled.
        models: dict with keys evaluator, reflector_a, reflector_b, blind_a, blind_b.
        blind_enabled: whether the blind labeler tier ran.

    Returns:
        {"per_clause": [...], "anchoring_summary": {...},
         "disputed_count": int, "blind_labeler_enabled": bool}
    """
    eval_labels = _index_evaluator(evaluator_output)
    ra_labels = _index_labels(reflector_a, "clause_labels")
    rb_labels = _index_labels(reflector_b, "clause_labels")
    ba_labels = _index_labels(blind_a, "labels") if blind_enabled else {}
    bb_labels = _index_labels(blind_b, "labels") if blind_enabled else {}

    per_clause = []
    a_changed = a_total = 0
    b_changed = b_total = 0
    disputed_count = 0

    for cid in eval_labels:  # iterate in evaluator order
        ev_label = eval_labels.get(cid)
        ra_label = ra_labels.get(cid)
        rb_label = rb_labels.get(cid)
        ba_label = ba_labels.get(cid) if blind_enabled else None
        bb_label = bb_labels.get(cid) if blind_enabled else None

        row = {
            "clause_id": cid,
            "evaluator":   _cell(ev_label, models.get("evaluator")),
            "reflector_a": _cell(ra_label, models.get("reflector_a")),
            "reflector_b": _cell(rb_label, models.get("reflector_b")),
            "blind_a":     _cell(ba_label, models.get("blind_a")) if blind_enabled else None,
            "blind_b":     _cell(bb_label, models.get("blind_b")) if blind_enabled else None,
        }

        # Dispute = any disagreement among the labels that are PRESENT (non-null)
        present = [l for l in (ev_label, ra_label, rb_label, ba_label, bb_label) if l is not None]
        row["disputed"] = len(set(present)) > 1
        if row["disputed"]:
            disputed_count += 1

        # Anchoring shift (only when blind tier ran)
        if blind_enabled:
            shift = {}
            if ra_label is not None and ba_label is not None:
                a_total += 1
                changed = ra_label != ba_label
                if changed:
                    a_changed += 1
                shift["reflector_a_vs_blind_a"] = "changed" if changed else "no_change"
            else:
                shift["reflector_a_vs_blind_a"] = "unavailable"
            if rb_label is not None and bb_label is not None:
                b_total += 1
                changed = rb_label != bb_label
                if changed:
                    b_changed += 1
                shift["reflector_b_vs_blind_b"] = "changed" if changed else "no_change"
            else:
                shift["reflector_b_vs_blind_b"] = "unavailable"
            row["anchoring_shift"] = shift
        else:
            row["anchoring_shift"] = "not measured (blind labeler disabled)"

        per_clause.append(row)

    if blind_enabled:
        anchoring_summary = {
            "reflector_a": {
                "model": models.get("reflector_a"),
                "clauses_changed": a_changed,
                "total": a_total,
                "shift_rate": round(a_changed / a_total, 4) if a_total else None,
            },
            "reflector_b": {
                "model": models.get("reflector_b"),
                "clauses_changed": b_changed,
                "total": b_total,
                "shift_rate": round(b_changed / b_total, 4) if b_total else None,
            },
        }
    else:
        anchoring_summary = None

    return {
        "per_clause": per_clause,
        "anchoring_summary": anchoring_summary,
        "disputed_count": disputed_count,
        "blind_labeler_enabled": blind_enabled,
    }


def annotate_finalizer_with_disputes(finalizer_output: dict, label_panel: dict) -> None:
    """
    Non-destructive: append disputed clause IDs to the finalizer's unresolved_flags
    and downgrade confidence to 'low' if any clause is disputed. Mutates in place.
    """
    disputed_ids = [
        row["clause_id"] for row in label_panel.get("per_clause", [])
        if row.get("disputed")
    ]
    if not disputed_ids:
        return
    flag = (
        f"Label disputed on {len(disputed_ids)} clause(s) "
        f"({', '.join(disputed_ids)}): independent labelers did not agree. "
        f"Human reviewer should check these clauses. The Evaluator's label is retained as official."
    )
    finalizer_output.setdefault("unresolved_flags", [])
    if flag not in finalizer_output["unresolved_flags"]:
        finalizer_output["unresolved_flags"].append(flag)
    finalizer_output["confidence"] = "low"
