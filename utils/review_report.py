"""Pure renderer for reviewer-focused markdown briefs."""
from pathlib import Path


PRIORITY_RANK = {"High": 0, "Medium": 1, "Info": 2}


def render_review_report(result: dict) -> str:
    """Render a saved GDPR pipeline result dict as markdown."""
    result = result or {}

    policy_name = result.get("policy_name", "N/A")
    run_metadata = result.get("run_metadata") or {}
    finalizer_output = result.get("finalizer_output") or {}
    evaluator_output = result.get("evaluator_output") or {}
    final_reflector_output = result.get("final_reflector_output") or {}
    reflector_a_initial = result.get("reflector_a_initial") or {}
    reflector_b_initial = result.get("reflector_b_initial") or {}
    flagged_clauses = result.get("flagged_clauses") or []
    verified_clauses = result.get("verified_clauses") or []
    label_panel = result.get("label_panel") or {}
    agent_models = result.get("agent_models") or {}
    retry_count = result.get("retry_count", 0)
    extractor_output = result.get("extractor_output") or {}

    items = _build_review_items(
        finalizer_output=finalizer_output,
        final_reflector_output=final_reflector_output,
        label_panel=label_panel,
        flagged_clauses=flagged_clauses,
        retry_count=retry_count,
        extractor_output=extractor_output,
    )

    lines = ["# Human Review Brief", ""]
    lines.extend(_render_review_priority(items))
    lines.extend(_render_items_section(items))
    lines.extend(_render_disputed_clauses(label_panel, verified_clauses))
    lines.extend(_render_flagged_evidence(flagged_clauses))
    lines.extend(
        _render_reflector_findings(
            reflector_a_initial=reflector_a_initial,
            reflector_b_initial=reflector_b_initial,
            final_reflector_output=final_reflector_output,
            retry_count=retry_count,
        )
    )
    lines.extend(_render_finalizer_notes(finalizer_output))
    lines.extend(_render_legal_references(evaluator_output))
    lines.extend(
        _render_run_context(
            policy_name=policy_name,
            run_metadata=run_metadata,
            extractor_output=extractor_output,
            agent_models=agent_models,
        )
    )

    return "\n".join(lines).rstrip() + "\n"


def write_review_report(result: dict, out_path: Path) -> None:
    """Write the rendered review brief to disk."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_review_report(result), encoding="utf-8")


def _build_review_items(
    *,
    finalizer_output: dict,
    final_reflector_output: dict,
    label_panel: dict,
    flagged_clauses: list[dict],
    retry_count: int,
    extractor_output: dict,
) -> list[dict]:
    items: list[dict] = []

    final_confidence = finalizer_output.get("confidence")
    overall_label = finalizer_output.get("overall_label")
    unresolved_flags = finalizer_output.get("unresolved_flags") or []
    reflector_status = final_reflector_output.get("review_status")
    agreement_rate = final_reflector_output.get("agreement_rate")
    blind_enabled = label_panel.get("blind_labeler_enabled")
    extraction_mode = extractor_output.get("extraction_mode")

    for row in label_panel.get("per_clause", []) or []:
        if row.get("disputed"):
            items.append({
                "priority": "High",
                "source": "label_panel",
                "clause": row.get("clause_id", "N/A"),
                "reason": "Disputed clause needs human review.",
            })

    for clause in flagged_clauses:
        items.append({
            "priority": "High",
            "source": "flagged_clauses",
            "clause": clause.get("clause_id", "N/A"),
            "reason": "Clause quote failed string-match verification.",
        })

    if unresolved_flags:
        items.append({
            "priority": "High",
            "source": "finalizer",
            "clause": "finalizer",
            "reason": "Finalizer has unresolved flags.",
        })

    if reflector_status == "errors_found":
        items.append({
            "priority": "High",
            "source": "reflector",
            "clause": "-",
            "reason": "Reflector errors remain after retries.",
        })

    if agreement_rate is not None and _as_float(agreement_rate) < 0.8:
        items.append({
            "priority": "Medium",
            "source": "reflector",
            "clause": "-",
            "reason": "Inter-reflector agreement below 80%.",
        })

    if retry_count and retry_count > 0:
        items.append({
            "priority": "Medium",
            "source": "reflector",
            "clause": "-",
            "reason": f"Retry count is {retry_count}.",
        })

    if blind_enabled is False:
        items.append({
            "priority": "Medium",
            "source": "label_panel",
            "clause": "-",
            "reason": "Blind labeler disabled; anchoring was not measured.",
        })

    if extraction_mode == "single_pass":
        items.append({
            "priority": "Medium",
            "source": "extractor",
            "clause": "-",
            "reason": "Extraction mode fell back to single_pass.",
        })

    if final_confidence == "low":
        items.append({
            "priority": "High",
            "source": "finalizer",
            "clause": "-",
            "reason": "Final confidence is low.",
        })
    elif final_confidence == "medium":
        items.append({
            "priority": "Medium",
            "source": "finalizer",
            "clause": "-",
            "reason": "Final confidence is medium.",
        })

    if overall_label is not None:
        items.append({
            "priority": "Info",
            "source": "finalizer",
            "clause": "-",
            "reason": f"Overall label: {overall_label}.",
        })

    return sorted(
        items,
        key=lambda item: (
            PRIORITY_RANK[item["priority"]],
            item["source"],
            str(item["clause"]),
            item["reason"],
        ),
    )


def _render_review_priority(items: list[dict]) -> list[str]:
    lines = ["## Review Priority", ""]
    if not items:
        lines.append("_None._")
        lines.append("")
        return lines

    counts = {"High": 0, "Medium": 0, "Info": 0}
    for item in items:
        counts[item["priority"]] += 1
    lines.append(
        f"- High: {counts['High']} | Medium: {counts['Medium']} | Info: {counts['Info']}"
    )
    lines.append("")
    return lines


def _render_items_section(items: list[dict]) -> list[str]:
    lines = ["## Items Needing Review", ""]
    if not items:
        lines.append("_None._")
        lines.append("")
        return lines

    lines.append("| Priority | Source | Clause | Reason |")
    lines.append("|---|---|---|---|")
    for item in items:
        lines.append(
            f"| {item['priority']} | {_cell(item['source'])} | "
            f"{_cell(item['clause'])} | {_cell(item['reason'])} |"
        )
    lines.append("")
    return lines


def _render_disputed_clauses(label_panel: dict, verified_clauses: list[dict]) -> list[str]:
    lines = ["## Disputed Clauses", ""]
    rows = [row for row in label_panel.get("per_clause", []) or [] if row.get("disputed")]
    if not rows:
        lines.append("_None._")
        lines.append("")
        return lines

    blind_enabled = label_panel.get("blind_labeler_enabled")
    if blind_enabled:
        lines.append("| Clause | Evaluator | Reflector A | Reflector B | Blind A | Blind B | Quote |")
        lines.append("|---|---|---|---|---|---|---|")
    else:
        lines.append(
            "_Blind labeling disabled for this run; anchoring was not measured._"
        )
        lines.append("| Clause | Evaluator | Reflector A | Reflector B | Quote |")
        lines.append("|---|---|---|---|---|")

    quote_by_clause = {str(clause.get("clause_id")): clause.get("quote", "") for clause in verified_clauses}
    for row in rows:
        clause_id = row.get("clause_id", "N/A")
        quote = quote_by_clause.get(str(clause_id), "")
        if blind_enabled:
            lines.append(
                f"| {_cell(clause_id)} | {_label_cell(row.get('evaluator'))} | "
                f"{_label_cell(row.get('reflector_a'))} | {_label_cell(row.get('reflector_b'))} | "
                f"{_label_cell(row.get('blind_a'))} | {_label_cell(row.get('blind_b'))} | "
                f"{_cell(quote)} |"
            )
        else:
            lines.append(
                f"| {_cell(clause_id)} | {_label_cell(row.get('evaluator'))} | "
                f"{_label_cell(row.get('reflector_a'))} | {_label_cell(row.get('reflector_b'))} | "
                f"{_cell(quote)} |"
            )
    lines.append("")
    return lines


def _render_flagged_evidence(flagged_clauses: list[dict]) -> list[str]:
    lines = ["## Flagged Evidence", ""]
    if not flagged_clauses:
        lines.append("_None._")
        lines.append("")
        return lines

    lines.append("| Clause | Verification Note | Quote |")
    lines.append("|---|---|---|")
    for clause in flagged_clauses:
        lines.append(
            f"| {_cell(clause.get('clause_id', 'N/A'))} | "
            f"{_cell(clause.get('verification_note', ''))} | "
            f"{_cell(clause.get('quote', ''))} |"
        )
    lines.append("")
    return lines


def _render_reflector_findings(
    *,
    reflector_a_initial: dict,
    reflector_b_initial: dict,
    final_reflector_output: dict,
    retry_count: int,
) -> list[str]:
    lines = ["## Reflector Findings", ""]
    lines.append(f"- Reflector A initial status: {_text_or_na(reflector_a_initial.get('review_status'))}")
    lines.append(f"- Reflector B initial status: {_text_or_na(reflector_b_initial.get('review_status'))}")
    lines.append(
        f"- Final merged status: **{_text_or_na(final_reflector_output.get('review_status'))}**"
    )
    agreement_rate = final_reflector_output.get("agreement_rate")
    lines.append(f"- Agreement rate: {_format_rate(agreement_rate)}")
    lines.append(f"- Retry count: {_text_or_na(retry_count)}")
    retries_exhausted = final_reflector_output.get("_retries_exhausted")
    if retries_exhausted is True:
        retries_text = "yes"
    elif retries_exhausted is False:
        retries_text = "no"
    else:
        retries_text = "N/A"
    lines.append(f"- Retries exhausted: **{retries_text}**")

    errors = final_reflector_output.get("errors") or []
    if errors:
        lines.append("")
        lines.append("| Agent | Clause | Type | Severity | Description | Recommendation |")
        lines.append("|---|---|---|---|---|---|")
        for error in errors:
            error_type = error.get("error_type", error.get("type", "N/A"))
            lines.append(
                f"| {_cell(error.get('agent', 'N/A'))} | {_cell(error.get('clause_id', 'N/A'))} | "
                f"{_cell(error_type)} | {_cell(error.get('severity', 'N/A'))} | "
                f"{_cell(error.get('description', ''))} | {_cell(error.get('recommendation', ''))} |"
            )
    lines.append("")
    return lines


def _render_finalizer_notes(finalizer_output: dict) -> list[str]:
    lines = ["## Finalizer Review Notes", ""]
    lines.append(f"- Overall label: {_text_or_na(finalizer_output.get('overall_label'))}")
    lines.append(f"- Confidence: {_text_or_na(finalizer_output.get('confidence'))}")

    unresolved_flags = finalizer_output.get("unresolved_flags") or []
    if unresolved_flags:
        lines.append("- Unresolved flags:")
        for flag in unresolved_flags:
            lines.append(f"  - {_cell(flag)}")
    else:
        lines.append("- Unresolved flags: _None._")

    human_review_notes = finalizer_output.get("human_review_notes")
    if human_review_notes:
        lines.append(f"- Human review notes: {_cell(human_review_notes)}")
    else:
        lines.append("- Human review notes: N/A")

    identified_gaps = finalizer_output.get("identified_gaps") or []
    if identified_gaps:
        lines.append("- Identified gaps:")
        for gap in identified_gaps:
            lines.append(f"  - {_cell(gap)}")
    else:
        lines.append("- Identified gaps: _None._")

    key_findings = finalizer_output.get("key_findings") or []
    if key_findings:
        lines.append("- Key findings:")
        for finding in key_findings:
            lines.append(f"  - {_cell(finding)}")
    else:
        lines.append("- Key findings: _None._")

    lines.append("")
    return lines


def _render_legal_references(evaluator_output: dict) -> list[str]:
    lines = ["## Legal References Used", ""]
    references = evaluator_output.get("references_used") or evaluator_output.get("tools_called") or []
    if not references:
        lines.append("_None._")
        lines.append("")
        return lines

    lines.append("| Reference | Source | Used For |")
    lines.append("|---|---|---|")
    seen: set[str] = set()
    for ref in references:
        ref_id = str(ref.get("reference_id") or ref.get("tool_name") or ref.get("name") or "N/A")
        source = str(ref.get("source_type") or ref.get("tool_name") or ref.get("name") or "N/A")
        dedupe_key = ref_id if ref_id != "N/A" else source
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        used_for = ref.get("used_for") or ref.get("reason") or ""
        lines.append(f"| {_cell(ref_id)} | {_cell(source)} | {_cell(used_for)} |")
    lines.append("")
    return lines


def _render_run_context(
    *,
    policy_name: str,
    run_metadata: dict,
    extractor_output: dict,
    agent_models: dict,
) -> list[str]:
    lines = ["## Run Context", ""]
    lines.append("| Field | Value |")
    lines.append("|---|---|")

    git_commit = run_metadata.get("git_commit")
    if isinstance(git_commit, dict):
        commit = git_commit.get("sha", "N/A")
        if git_commit.get("dirty") is True:
            commit = f"{commit} (dirty)"
    else:
        commit = git_commit if isinstance(git_commit, str) and git_commit and git_commit != "N/A" else "N/A"

    lines.append(f"| Policy | {_cell(policy_name)} |")
    lines.append(f"| Run ID | {_cell(run_metadata.get('run_id', 'N/A'))} |")
    lines.append(f"| UTC Timestamp | {_cell(run_metadata.get('utc_timestamp', 'N/A'))} |")
    lines.append(f"| Code commit | {_cell(commit)} |")
    lines.append(f"| Policy file | {_cell(run_metadata.get('policy_file', 'N/A'))} |")
    lines.append(f"| Policy SHA-256 | {_cell(run_metadata.get('policy_sha256', 'N/A'))} |")
    lines.append(f"| Clause count | {_cell(run_metadata.get('clause_count', 'N/A'))} |")
    lines.append(f"| Blind labeler | {_blind_labeler_state(run_metadata)} |")
    lines.append(f"| Extraction mode | {_cell(extractor_output.get('extraction_mode', 'N/A'))} |")
    lines.append(f"| Models used | {_render_models_used(agent_models)} |")
    lines.append("")
    return lines


def _render_models_used(agent_models: dict) -> str:
    if not agent_models:
        return "N/A"
    order = ["extractor", "evaluator", "reflector_a", "reflector_b", "blind_a", "blind_b", "finalizer"]
    parts = []
    for key in order:
        if key in agent_models and agent_models[key]:
            parts.append(f"{key}={agent_models[key]}")
    remaining = [key for key in agent_models if key not in order and agent_models[key]]
    for key in sorted(remaining):
        parts.append(f"{key}={agent_models[key]}")
    return _cell(", ".join(parts)) if parts else "N/A"


def _blind_labeler_state(run_metadata: dict) -> str:
    if "blind_enabled" not in run_metadata:
        return "N/A"
    return "enabled" if run_metadata.get("blind_enabled") else "disabled"


def _label_cell(cell) -> str:
    if not isinstance(cell, dict):
        return "N/A"
    return _cell(cell.get("label", "N/A"))


def _cell(value) -> str:
    if value is None:
        return "N/A"
    text = str(value)
    text = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    return text.replace("|", "\\|")


def _text_or_na(value) -> str:
    if value is None or value == "":
        return "N/A"
    return _cell(value)


def _format_rate(value) -> str:
    if value is None:
        return "N/A"
    rate = _as_float(value)
    return f"{rate:.0%}"


def _as_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
