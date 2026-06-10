"""
Runs index — a cumulative per-run summary table.

Records one row per pipeline run in runs_index.md (readable) and runs_index.csv
(Excel/pandas), newest on top, built from the result dict the pipeline already
produces. Pure stdlib; writing the index must never crash a run.

Replaces the older model_usage_log.md.
"""

import csv
from pathlib import Path

# Field order is shared by build_index_row (dict keys), the CSV header, and the
# Markdown columns. CSV uses these keys verbatim; Markdown uses MD_HEADERS below.
FIELDS = [
    "run_id",
    "date",
    "policy",
    "policy_sha256",
    "commit",
    "overall_label",
    "confidence",
    "clauses",
    "coverage",
    "agreement_rate",
    "retries",
    "disputed",
    "blind",
    "anchoring_a",
    "anchoring_b",
]

MD_HEADERS = [
    "Run ID",
    "Date (UTC)",
    "Policy",
    "Policy hash",
    "Commit",
    "Overall label",
    "Confidence",
    "Clauses",
    "Coverage",
    "Agreement",
    "Retries",
    "Disputed",
    "Blind",
    "Anchoring A",
    "Anchoring B",
]

EM_DASH = "—"  # — shown when a value is not applicable (e.g. blind disabled)


def _human_date(run_metadata: dict) -> str:
    """Render run_metadata['utc_timestamp'] (YYYY-MM-DDTHH:MM:SSZ) as
    'YYYY-MM-DD HH:MM UTC' (minute precision). Returns 'N/A' if absent/malformed."""
    ts = run_metadata.get("utc_timestamp")
    if not isinstance(ts, str) or "T" not in ts:
        return "N/A"
    date_part, _, time_part = ts.partition("T")
    return f"{date_part} {time_part[:5]} UTC"


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
    Map a pipeline result dict to an ordered dict of the 15 index fields.

    Defensive throughout: every field falls back to a safe default so a missing
    key (older or empty-result runs) never raises.
    """
    rm = result.get("run_metadata", {}) or {}
    fin = result.get("finalizer_output", {}) or {}
    refl = result.get("final_reflector_output", {}) or {}
    lp = result.get("label_panel", {}) or {}
    gc = rm.get("git_commit", {}) or {}
    eo = result.get("extractor_output", {}) or {}
    coverage = {"two_pass": "high", "single_pass": "low"}.get(eo.get("extraction_mode"), EM_DASH)

    sha = gc.get("sha", "unknown")
    commit = f"{sha} (dirty)" if gc.get("dirty") else sha

    return {
        "run_id": rm.get("run_id", "N/A"),
        "date": _human_date(rm),
        "policy": rm.get("policy_file") or result.get("policy_name", "N/A"),
        "policy_sha256": rm.get("policy_sha256", "N/A"),
        "commit": commit,
        "overall_label": fin.get("overall_label", "N/A"),
        "confidence": fin.get("confidence", "N/A"),
        "clauses": rm.get("clause_count", len(result.get("verified_clauses", []))),
        "coverage": coverage,
        "agreement_rate": refl.get("agreement_rate", "N/A"),
        "retries": result.get("retry_count", 0),
        "disputed": lp.get("disputed_count", 0),
        "blind": "on" if rm.get("blind_enabled") else "off",
        "anchoring_a": _anchoring(lp, "reflector_a"),
        "anchoring_b": _anchoring(lp, "reflector_b"),
    }


def _backup(path: Path) -> None:
    """If path exists, rename it to '<name>.bak', replacing any existing backup."""
    if path.exists():
        bak = path.with_name(path.name + ".bak")
        if bak.exists():
            bak.unlink()
        path.rename(bak)


def _write_csv(path: Path, rows: list) -> None:
    """Write the CSV fresh: FIELDS header followed by every row (newest first)."""
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(FIELDS)
        writer.writerows(rows)


def _write_md(path: Path, rows: list) -> None:
    """Write the Markdown index fresh: header block + column header + every row."""
    with path.open("w", encoding="utf-8") as f:
        f.write("# Runs Index\n\n")
        f.write("One row per pipeline run. Newest at the top.\n\n")
        f.write("| " + " | ".join(MD_HEADERS) + " |\n")
        f.write("|" + "|".join(["---"] * len(MD_HEADERS)) + "|\n")
        for values in rows:
            f.write("| " + " | ".join(str(v) for v in values) + " |\n")


def append_run_to_index(result: dict, output_dir: Path) -> None:
    """
    Prepend this run's summary row to runs_index.md and runs_index.csv under
    output_dir, so the most recently written run appears on top. Creates the
    files on first write.

    If an existing index uses an older column schema (its CSV header does not
    match FIELDS), it is renamed to '<name>.bak' and a fresh index is started —
    no data is deleted, the old rows are preserved in the .bak file.

    Never raises: a failure to write the index must not crash a pipeline run —
    the per-run JSON and report remain the source of truth.
    """
    try:
        row = build_index_row(result)
        values = [row[field] for field in FIELDS]
        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = output_dir / "runs_index.csv"
        md_path = output_dir / "runs_index.md"

        existing = []
        if csv_path.exists():
            with csv_path.open(encoding="utf-8", newline="") as f:
                rows = list(csv.reader(f))
            if rows and rows[0] == FIELDS:
                existing = rows[1:]          # current schema — keep prior rows
            else:
                _backup(csv_path)            # old/unknown schema — start fresh
                _backup(md_path)
                existing = []

        all_rows = [values] + existing       # newest row on top
        _write_csv(csv_path, all_rows)
        _write_md(md_path, all_rows)
        print(f"Runs index updated: {csv_path}")
    except Exception as exc:  # index is a convenience aggregate; never fatal
        print(f"  [runs_index] WARNING: could not update index: {exc}")
