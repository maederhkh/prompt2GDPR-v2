"""
Runs index — a cumulative per-run summary table.

Appends one row per pipeline run to runs_index.md (readable) and runs_index.csv
(Excel/pandas), built from the result dict the pipeline already produces. Pure
stdlib; writing the index must never crash a run.

Replaces the older model_usage_log.md.
"""

import csv
from pathlib import Path

# Field order is shared by build_index_row (dict keys), the CSV header, and the
# Markdown columns. CSV uses these keys verbatim; Markdown uses MD_HEADERS below.
FIELDS = [
    "run_id",
    "policy",
    "policy_sha256",
    "commit",
    "overall_label",
    "confidence",
    "clauses",
    "agreement_rate",
    "retries",
    "disputed",
    "blind",
    "anchoring_a",
    "anchoring_b",
]

MD_HEADERS = [
    "Run ID",
    "Policy",
    "Policy hash",
    "Commit",
    "Overall label",
    "Confidence",
    "Clauses",
    "Agreement",
    "Retries",
    "Disputed",
    "Blind",
    "Anchoring A",
    "Anchoring B",
]

EM_DASH = "—"  # — shown when a value is not applicable (e.g. blind disabled)


def _anchoring(label_panel: dict, side_key: str):
    """Return reflector shift_rate for side_key, or EM_DASH if unavailable."""
    summary = label_panel.get("anchoring_summary")
    if not isinstance(summary, dict):
        return EM_DASH
    side = summary.get(side_key)
    if not isinstance(side, dict):
        return EM_DASH
    rate = side.get("shift_rate")
    return rate if rate is not None else EM_DASH


def build_index_row(result: dict) -> dict:
    """
    Map a pipeline result dict to an ordered dict of the 13 index fields.

    Defensive throughout: every field falls back to a safe default so a missing
    key (older or empty-result runs) never raises.
    """
    rm = result.get("run_metadata", {}) or {}
    fin = result.get("finalizer_output", {}) or {}
    refl = result.get("final_reflector_output", {}) or {}
    lp = result.get("label_panel", {}) or {}
    gc = rm.get("git_commit", {}) or {}

    sha = gc.get("sha", "unknown")
    commit = f"{sha} (dirty)" if gc.get("dirty") else sha

    return {
        "run_id": rm.get("run_id", "N/A"),
        "policy": rm.get("policy_file") or result.get("policy_name", "N/A"),
        "policy_sha256": rm.get("policy_sha256", "N/A"),
        "commit": commit,
        "overall_label": fin.get("overall_label", "N/A"),
        "confidence": fin.get("confidence", "N/A"),
        "clauses": rm.get("clause_count", len(result.get("verified_clauses", []))),
        "agreement_rate": refl.get("agreement_rate", "N/A"),
        "retries": result.get("retry_count", 0),
        "disputed": lp.get("disputed_count", 0),
        "blind": "on" if rm.get("blind_enabled") else "off",
        "anchoring_a": _anchoring(lp, "reflector_a"),
        "anchoring_b": _anchoring(lp, "reflector_b"),
    }


def _append_md(path: Path, values: list) -> None:
    """Append one Markdown table row; write the header block if the file is new."""
    new = not path.exists()
    with path.open("a", encoding="utf-8") as f:
        if new:
            f.write("# Runs Index\n\n")
            f.write("One row per pipeline run. Newest at the bottom.\n\n")
            f.write("| " + " | ".join(MD_HEADERS) + " |\n")
            f.write("|" + "|".join(["---"] * len(MD_HEADERS)) + "|\n")
        f.write("| " + " | ".join(str(v) for v in values) + " |\n")


def _append_csv(path: Path, values: list) -> None:
    """Append one CSV row; write the header row if the file is new."""
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new:
            writer.writerow(FIELDS)
        writer.writerow(values)


def append_run_to_index(result: dict, output_dir: Path) -> None:
    """
    Append this run's summary row to runs_index.md and runs_index.csv under
    output_dir, creating each (with header) on first write.

    Never raises: a failure to write the index must not crash a pipeline run —
    the per-run JSON and report remain the source of truth.
    """
    try:
        row = build_index_row(result)
        values = [row[field] for field in FIELDS]
        output_dir.mkdir(parents=True, exist_ok=True)
        _append_md(output_dir / "runs_index.md", values)
        _append_csv(output_dir / "runs_index.csv", values)
        print(f"Runs index updated: {output_dir / 'runs_index.csv'}")
    except Exception as exc:  # index is a convenience aggregate; never fatal
        print(f"  [runs_index] WARNING: could not update index: {exc}")
