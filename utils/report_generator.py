"""
Human-readable markdown report generator.

Produces a .md file alongside the JSON output for each run,
summarising the compliance assessment in a readable format.
"""

from pathlib import Path


def generate_report(result: dict, out_path: Path) -> None:
    """
    Generate a human-readable markdown report from a pipeline result dict
    and write it to out_path.
    """
    finalizer = result.get("finalizer_output", {})
    evaluator = result.get("evaluator_output", {})
    extractor = result.get("extractor_output", {})
    merged_reflector = result.get("final_reflector_output", {})
    agent_models = result.get("agent_models", {})
    verified = result.get("verified_clauses", [])
    flagged = result.get("flagged_clauses", [])

    label_panel = result.get("label_panel", {})
    run_metadata = result.get("run_metadata", {})

    policy_name = result.get("policy_name", "unknown")
    assessment_date = finalizer.get("assessment_date", "N/A")
    overall_label = finalizer.get("overall_label", "N/A")
    confidence = finalizer.get("confidence", "N/A")

    lines = []

    # -----------------------------------------------------------------------
    # Header
    # -----------------------------------------------------------------------
    lines.append(f"# GDPR Purpose Limitation Assessment Report")
    lines.append(f"")
    lines.append(f"| Field | Value |")
    lines.append(f"|---|---|")
    lines.append(f"| **Policy** | {policy_name} |")
    lines.append(f"| **Date** | {assessment_date} |")
    lines.append(f"| **Principle** | Article 5(1)(b) — Purpose Limitation |")
    lines.append(f"| **Overall Label** | **{overall_label}** |")
    lines.append(f"| **Confidence** | {confidence} |")
    lines.append(f"| **Human Review Required** | Yes |")
    lines.append(f"")

    # -----------------------------------------------------------------------
    # Run Metadata (provenance)
    # -----------------------------------------------------------------------
    if run_metadata:
        gc = run_metadata.get("git_commit", {})
        sha = gc.get("sha", "unknown")
        commit_str = f"{sha} (dirty)" if gc.get("dirty") else sha
        lines.append(f"## Run Metadata")
        lines.append(f"")
        lines.append(f"| Field | Value |")
        lines.append(f"|---|---|")
        lines.append(f"| **Run ID** | {run_metadata.get('run_id', 'N/A')} |")
        lines.append(f"| **Timestamp (UTC)** | {run_metadata.get('utc_timestamp', 'N/A')} |")
        lines.append(f"| **Code commit** | `{commit_str}` |")
        lines.append(f"| **Policy file** | {run_metadata.get('policy_file', 'N/A')} |")
        lines.append(f"| **Policy SHA-256** | `{run_metadata.get('policy_sha256', 'N/A')}` |")
        lines.append(f"| **Temperature** | {run_metadata.get('temperature', 'N/A')} |")
        lines.append(f"| **Blind labeler** | {'enabled' if run_metadata.get('blind_enabled') else 'disabled'} |")
        lines.append(f"| **Clause count** | {run_metadata.get('clause_count', 'N/A')} |")
        lines.append(f"")

    # -----------------------------------------------------------------------
    # Clause extraction summary
    # -----------------------------------------------------------------------
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## Clause Extraction")
    lines.append(f"")
    _mode = extractor.get("extraction_mode")
    _mode_label = {"two_pass": "two-pass", "single_pass": "single-pass (fallback)"}.get(_mode, "unknown")
    _coverage_conf = {"two_pass": "high", "single_pass": "low"}.get(_mode, "unknown")
    lines.append(f"- Verified clauses: **{len(verified)}**")
    lines.append(f"- Flagged clauses (failed verification): **{len(flagged)}**")
    lines.append(f"- Extraction mode: {_mode_label}")
    lines.append(f"- Coverage confidence: {_coverage_conf}")
    if extractor.get("extraction_notes"):
        lines.append(f"- Extractor notes: {extractor['extraction_notes']}")
    lines.append(f"")

    # -----------------------------------------------------------------------
    # Per-clause assessment table
    # -----------------------------------------------------------------------
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## Clause Assessments")
    lines.append(f"")

    evaluations = evaluator.get("evaluations", [])
    if evaluations:
        lines.append(f"| Clause | Relevance Type | Label | Stage 2 | Art. 89 |")
        lines.append(f"|---|---|---|---|---|")
        for ev in evaluations:
            cid = ev.get("clause_id", "?")
            label = ev.get("clause_label", "?")
            stage2 = "Yes" if ev.get("stage_2_applicable") else "No"
            art89 = "Yes" if ev.get("article_89_exception") else "No"
            # Find relevance type from verified clauses
            rel_type = next(
                (c.get("relevance_type", "?") for c in verified if c.get("clause_id") == cid),
                "?"
            )
            lines.append(f"| {cid} | {rel_type} | **{label}** | {stage2} | {art89} |")
        lines.append(f"")

        # Per-clause detail
        lines.append(f"### Clause Detail")
        lines.append(f"")
        for ev in evaluations:
            cid = ev.get("clause_id", "?")
            label = ev.get("clause_label", "?")
            justification = ev.get("justification", "")

            # Find the quote
            quote = next(
                (c.get("quote", "") for c in verified if c.get("clause_id") == cid),
                ""
            )

            lines.append(f"#### {cid} — {label}")
            if quote:
                lines.append(f"")
                lines.append(f"> {quote[:300]}{'...' if len(quote) > 300 else ''}")
            lines.append(f"")

            # Stage 1
            stage1 = ev.get("stage_1", {})
            if stage1:
                lines.append(f"**Stage 1 — Purpose Specification:**")
                lines.append(f"- Specific: {stage1.get('specific', '?')}")
                lines.append(f"- Explicit: {stage1.get('explicit', '?')}")
                lines.append(f"- Legitimate: {stage1.get('legitimate', '?')}")
                lines.append(f"- Determined at collection: {stage1.get('determined_at_collection', '?')}")
                lines.append(f"")

            # Stage 2
            if ev.get("stage_2_applicable"):
                stage2 = ev.get("stage_2", {})
                lines.append(f"**Stage 2 — Compatibility Assessment:**")
                lines.append(f"- Purpose link: {stage2.get('purpose_link', '?')}")
                lines.append(f"- Context consistent: {stage2.get('context_consistent', '?')}")
                lines.append(f"- Data nature considered: {stage2.get('data_nature_considered', '?')}")
                lines.append(f"- Impact assessed: {stage2.get('impact_assessed', '?')}")
                lines.append(f"- Safeguards present: {stage2.get('safeguards_present', '?')}")
                lines.append(f"")

            # Article 89
            if ev.get("article_89_exception"):
                art89 = ev.get("article_89_assessment", {})
                lines.append(f"**Article 89 Exception:**")
                lines.append(f"- Exception explicitly claimed: {art89.get('exception_explicitly_claimed', '?')}")
                lines.append(f"- Safeguards stated: {art89.get('safeguards_stated', '?')}")
                lines.append(f"- Purpose genuine: {art89.get('purpose_genuine', '?')}")
                lines.append(f"")

            if justification:
                lines.append(f"**Justification:** {justification}")
            lines.append(f"")
    else:
        lines.append(f"No evaluations available.")
        lines.append(f"")

    # -----------------------------------------------------------------------
    # Overall justification
    # -----------------------------------------------------------------------
    overall_just = evaluator.get("overall_justification", "")
    if overall_just:
        lines.append(f"---")
        lines.append(f"")
        lines.append(f"## Overall Justification")
        lines.append(f"")
        lines.append(overall_just)
        lines.append(f"")

    # -----------------------------------------------------------------------
    # Key findings and gaps
    # -----------------------------------------------------------------------
    key_findings = finalizer.get("key_findings", [])
    identified_gaps = finalizer.get("identified_gaps", [])

    if key_findings or identified_gaps:
        lines.append(f"---")
        lines.append(f"")
        lines.append(f"## Finalizer Summary")
        lines.append(f"")

    if key_findings:
        lines.append(f"### Key Findings")
        for f in key_findings:
            lines.append(f"- {f}")
        lines.append(f"")

    if identified_gaps:
        lines.append(f"### Identified Gaps")
        for g in identified_gaps:
            lines.append(f"- {g}")
        lines.append(f"")

    # -----------------------------------------------------------------------
    # Unresolved flags
    # -----------------------------------------------------------------------
    unresolved = finalizer.get("unresolved_flags", [])
    if unresolved:
        lines.append(f"### Unresolved Flags")
        for u in unresolved:
            lines.append(f"- {u}")
        lines.append(f"")

    # -----------------------------------------------------------------------
    # Human review notes
    # -----------------------------------------------------------------------
    review_notes = finalizer.get("human_review_notes", "")
    if review_notes:
        lines.append(f"---")
        lines.append(f"")
        lines.append(f"## Human Review Notes")
        lines.append(f"")
        lines.append(review_notes)
        lines.append(f"")

    # -----------------------------------------------------------------------
    # Reflector audit summary
    # -----------------------------------------------------------------------
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## Reflector Audit")
    lines.append(f"")
    lines.append(f"| | Reflector A | Reflector B | Merged |")
    lines.append(f"|---|---|---|---|")

    ra = result.get("reflector_a_initial", {})
    rb = result.get("reflector_b_initial", {})
    lines.append(
        f"| Status | {ra.get('review_status', '?')} | {rb.get('review_status', '?')} "
        f"| {merged_reflector.get('review_status', '?')} |"
    )
    lines.append(
        f"| Errors found | {len(ra.get('errors', []))} | {len(rb.get('errors', []))} "
        f"| {len(merged_reflector.get('errors', []))} unique |"
    )
    lines.append(f"")

    agreement = merged_reflector.get("agreement_rate", 1.0)
    both = merged_reflector.get("both_flagged_count", 0)
    a_only = merged_reflector.get("a_only_count", 0)
    b_only = merged_reflector.get("b_only_count", 0)
    lines.append(f"- Inter-reflector agreement: **{agreement:.0%}**")
    lines.append(f"- Flagged by both: {both} | A only: {a_only} | B only: {b_only}")
    lines.append(f"- Retries: {result.get('retry_count', 0)}")
    lines.append(f"")

    # -----------------------------------------------------------------------
    # Legal references used
    # -----------------------------------------------------------------------
    refs_used = evaluator.get("references_used", [])
    tools_called = evaluator.get("tools_called", [])
    ref_list = refs_used or tools_called

    if ref_list:
        lines.append(f"---")
        lines.append(f"")
        lines.append(f"## Legal References Consulted")
        lines.append(f"")
        lines.append(f"| Reference | Type | Purpose |")
        lines.append(f"|---|---|---|")
        seen = set()
        for r in ref_list:
            rid = r.get("reference_id", "?")
            if rid in seen:
                continue
            seen.add(rid)
            rtype = r.get("source_type", "?")
            used_for = r.get("used_for", r.get("reason", ""))[:80]
            lines.append(f"| {rid} | {rtype} | {used_for} |")
        lines.append(f"")

    # -----------------------------------------------------------------------
    # Models used
    # -----------------------------------------------------------------------
    if agent_models:
        lines.append(f"---")
        lines.append(f"")
        lines.append(f"## Models Used")
        lines.append(f"")
        lines.append(f"| Agent | Role | Model |")
        lines.append(f"|---|---|---|")
        role_labels = {
            "scout":       "Pass 1 — Section Scout + Pass 3 Gap Judge",
            "extractor":   "Pass 2 — Deep Extractor + Pass 3 Re-extraction",
            "evaluator":   "Agent 2 — GDPR Rubric Evaluator",
            "reflector_a": "Agent 3A — Independent Auditor",
            "reflector_b": "Agent 3B — Independent Auditor",
            "finalizer":   "Agent 4 — Finalizer",
        }
        for agent, model in agent_models.items():
            role = role_labels.get(agent, agent)
            lines.append(f"| {agent} | {role} | `{model}` |")
        lines.append(f"")

    # -----------------------------------------------------------------------
    # Label Panel
    # -----------------------------------------------------------------------
    if label_panel and label_panel.get("per_clause"):
        lines.append(f"---")
        lines.append(f"")
        lines.append(f"## Label Panel")
        lines.append(f"")
        blind_on = label_panel.get("blind_labeler_enabled", False)

        # Model legend
        first = label_panel["per_clause"][0]
        def _model_of(cell):
            return cell.get("model") if isinstance(cell, dict) else "n/a"
        lines.append(f"**Models:** "
                     f"Evaluator = `{_model_of(first.get('evaluator'))}` | "
                     f"Reflector A = `{_model_of(first.get('reflector_a'))}` | "
                     f"Reflector B = `{_model_of(first.get('reflector_b'))}`"
                     + (f" | Blind A = `{_model_of(first.get('blind_a'))}` | "
                        f"Blind B = `{_model_of(first.get('blind_b'))}`" if blind_on else ""))
        lines.append(f"")

        def _lab(cell):
            return cell.get("label") if isinstance(cell, dict) else "—"

        if blind_on:
            lines.append(f"| Clause | Evaluator | Reflector A | Reflector B | Blind A | Blind B | Status |")
            lines.append(f"|---|---|---|---|---|---|---|")
            for row in label_panel["per_clause"]:
                status = "⚠️ Disputed" if row.get("disputed") else "✅ Agreed"
                lines.append(
                    f"| {row.get('clause_id', '?')} | {_lab(row.get('evaluator'))} | "
                    f"{_lab(row.get('reflector_a'))} | {_lab(row.get('reflector_b'))} | "
                    f"{_lab(row.get('blind_a'))} | {_lab(row.get('blind_b'))} | {status} |"
                )
        else:
            lines.append(f"| Clause | Evaluator | Reflector A | Reflector B | Status |")
            lines.append(f"|---|---|---|---|---|")
            for row in label_panel["per_clause"]:
                status = "⚠️ Disputed" if row.get("disputed") else "✅ Agreed"
                lines.append(
                    f"| {row.get('clause_id', '?')} | {_lab(row.get('evaluator'))} | "
                    f"{_lab(row.get('reflector_a'))} | {_lab(row.get('reflector_b'))} | {status} |"
                )
        lines.append(f"")
        lines.append(f"- Disputed clauses: **{label_panel.get('disputed_count', 0)}**")

        # Anchoring summary
        summary = label_panel.get("anchoring_summary")
        if blind_on and summary:
            lines.append(f"")
            lines.append(f"### Anchoring Summary")
            lines.append(f"")
            for ref_key, label in (("reflector_a", "Reflector A"), ("reflector_b", "Reflector B")):
                s = summary.get(ref_key, {})
                rate = s.get("shift_rate")
                rate_str = f"{rate:.0%}" if rate is not None else "n/a"
                lines.append(
                    f"- {label} (`{s.get('model')}`): changed its label on "
                    f"**{s.get('clauses_changed', 0)}/{s.get('total', 0)}** clause(s) "
                    f"after seeing the Evaluator — anchoring shift **{rate_str}**."
                )
        elif not blind_on:
            lines.append(f"")
            lines.append(f"_Blind labeling disabled for this run — anchoring not measured._")
        lines.append(f"")

    # -----------------------------------------------------------------------
    # Write file
    # -----------------------------------------------------------------------
    out_path.write_text("\n".join(lines), encoding="utf-8")
