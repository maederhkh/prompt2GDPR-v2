"""
Batch comparison — render a side-by-side survey of one batch (corpus) run.

Pure stdlib; no LLM calls. Given a list of per-run *entries*, produce a
Markdown table and CSV rows. Every metric cell is taken from the entry's
pre-computed index row (utils.runs_index.build_index_row); this module adds no
result-extraction logic of its own.

An entry is a dict:
    {
      "policy": str,            # policy file stem
      "run_index": int,         # 1-based run number for this policy
      "status": "ok" | "empty" | "failed",
      "row": dict | None,       # build_index_row(result), or None when failed
      "error": str | None,
    }
"""

EM_DASH = "—"  # shown when a metric is unavailable (failed entry, or "N/A" cell)

# (column header, build_index_row key) for the metric columns.
_METRIC_COLUMNS = [
    ("Overall label", "overall_label"),
    ("Confidence", "confidence"),
    ("Clauses", "clauses"),
    ("Disputed", "disputed"),
    ("Retries", "retries"),
    ("Agreement", "agreement_rate"),
]

HEADERS = ["Policy", "Run", "Status"] + [h for h, _ in _METRIC_COLUMNS]


def _cells(entry) -> list:
    """Ordered string cells for one entry row: Policy, Run, Status, then metrics."""
    cells = [
        str(entry.get("policy", "")),
        str(entry.get("run_index", "")),
        str(entry.get("status", "")),
    ]
    row = entry.get("row")
    if not row:
        cells += [EM_DASH] * len(_METRIC_COLUMNS)
        return cells
    for _, key in _METRIC_COLUMNS:
        val = row.get(key)
        cells.append(EM_DASH if val in (None, "", "N/A") else str(val))
    return cells


def build_comparison_csv_rows(entries) -> list:
    """Header row followed by one row per entry."""
    return [list(HEADERS)] + [_cells(e) for e in entries]


def build_comparison_md(entries, batch_label: str) -> str:
    """Render the batch comparison as a Markdown document."""
    lines = [
        f"# Batch Comparison — {batch_label}",
        "",
        f"{len(entries)} policy-run(s) in this batch. Each policy's full JSON "
        "and report are saved separately; this table is a side-by-side survey "
        "of just this batch.",
        "",
        "| " + " | ".join(HEADERS) + " |",
        "|" + "|".join(["---"] * len(HEADERS)) + "|",
    ]
    for e in entries:
        lines.append("| " + " | ".join(_cells(e)) + " |")
    return "\n".join(lines) + "\n"
