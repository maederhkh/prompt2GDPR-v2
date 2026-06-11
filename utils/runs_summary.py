"""
Runs summary — an on-demand aggregate view over runs_index.csv.

Reads the cumulative runs index, computes Overall and Per-policy statistics
(volume & coverage, compliance outcomes, reliability), prints the summary to
the terminal, and writes runs_summary.md next to the index. Read-only with
respect to the index; pure stdlib; zero LLM calls. The pipeline never invokes
this — regenerate on demand with:  python analyze_runs.py
"""

import csv
from collections import Counter
from pathlib import Path

from utils.runs_index import FIELDS


def _numeric(value):
    """float(value), or None when the cell is non-numeric (N/A, —, empty)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _num_stats(rows, field):
    """avg/min/max/n over the numeric cells of a column, or None if none."""
    vals = [v for v in (_numeric(r.get(field)) for r in rows) if v is not None]
    if not vals:
        return None
    return {
        "avg": sum(vals) / len(vals),
        "min": min(vals),
        "max": max(vals),
        "n": len(vals),
    }


def _count_ge1(rows, field):
    """How many rows have a numeric value >= 1 in this column."""
    return sum(1 for r in rows if (_numeric(r.get(field)) or 0) >= 1)


def load_index_rows(csv_path) -> list:
    """
    Read runs_index.csv into a list of per-run dicts keyed by FIELDS.

    Raises FileNotFoundError when the file is missing and ValueError when the
    header does not match the current FIELDS schema (older index files).
    """
    with Path(csv_path).open(encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    if not rows or rows[0] != FIELDS:
        raise ValueError(
            "runs_index.csv uses an older or unknown column schema; "
            "run the pipeline once to refresh the index, then try again."
        )
    return [dict(zip(FIELDS, r)) for r in rows[1:]]


def summarize(rows: list) -> dict:
    """
    Compute one stats block (volume & coverage, outcomes, reliability) from a
    list of index-row dicts. Pure function; sentinel cells (N/A, —) are
    excluded from numeric stats per the denominator rule.
    """
    n = len(rows)
    dates = sorted(d for d in (r.get("date", "") for r in rows) if d not in ("", "N/A"))

    coverage = Counter()
    for r in rows:
        c = r.get("coverage")
        coverage[c if c in ("high", "low") else "unknown"] += 1
    judged = coverage["high"] + coverage["low"]

    return {
        "runs": n,
        "date_range": (dates[0], dates[-1]) if dates else None,
        "clauses": _num_stats(rows, "clauses"),
        "coverage": {
            "high": coverage["high"],
            "low": coverage["low"],
            "unknown": coverage["unknown"],
            "fallback_rate": (coverage["low"] / judged) if judged else None,
        },
        "labels": Counter(r.get("overall_label", "N/A") for r in rows),
        "confidence": Counter(r.get("confidence", "N/A") for r in rows),
        "agreement": _num_stats(rows, "agreement_rate"),
        "retries": _num_stats(rows, "retries"),
        "retry_runs": _count_ge1(rows, "retries"),
        "disputed": _num_stats(rows, "disputed"),
        "disputed_runs": _count_ge1(rows, "disputed"),
        "anchoring_a": _num_stats(rows, "anchoring_a"),
        "anchoring_b": _num_stats(rows, "anchoring_b"),
    }


def _fmt(x: float) -> str:
    """Format a number compactly: 68.0 -> '68', 0.875 -> '0.88'."""
    return f"{x:.2f}".rstrip("0").rstrip(".")


def _pct(part: int, total: int) -> str:
    """'part of total' as a whole percent, e.g. '33%'. '0%' when total is 0."""
    return f"{100 * part / total:.0f}%" if total else "0%"


def _avg_with_denominator(stats, total: int) -> str:
    """'0.88 (from 5 of 7 runs)', or 'n/a (0 of 7 runs)' when no numeric cells."""
    if stats is None:
        return f"n/a (0 of {total} runs)"
    return f"{_fmt(stats['avg'])} (from {stats['n']} of {total} runs)"


def _dist_line(counter, total: int) -> str:
    """'Compliant 3 (60%), Non-Compliant 2 (40%)' — labels sorted alphabetically."""
    parts = [
        f"{label} {count} ({_pct(count, total)})"
        for label, count in sorted(counter.items())
    ]
    return ", ".join(parts) if parts else "n/a"


def _render_block(s: dict, h: str) -> list:
    """Render one stats block as markdown lines; h is the heading prefix
    ('###' under Overall, '####' under a per-policy section)."""
    n = s["runs"]
    lines = [f"{h} Volume & coverage"]
    lines.append(f"- Runs: {n}")
    dr = s["date_range"]
    lines.append(f"- Date range: {dr[0]} → {dr[1]}" if dr else "- Date range: n/a")
    cl = s["clauses"]
    if cl:
        lines.append(
            f"- Clauses: avg {_fmt(cl['avg'])} (min {_fmt(cl['min'])}, "
            f"max {_fmt(cl['max'])}; from {cl['n']} of {n} runs)"
        )
    else:
        lines.append(f"- Clauses: n/a (0 of {n} runs)")
    cov = s["coverage"]
    cov_line = f"- Coverage: {cov['high']} high / {cov['low']} low / {cov['unknown']} unknown"
    if cov["fallback_rate"] is not None:
        cov_line += f" — fallback rate {100 * cov['fallback_rate']:.0f}%"
    lines.append(cov_line)
    lines.append("")
    lines.append(f"{h} Compliance outcomes")
    lines.append(f"- Overall label: {_dist_line(s['labels'], n)}")
    lines.append(f"- Confidence: {_dist_line(s['confidence'], n)}")
    lines.append("")
    lines.append(f"{h} Reliability")
    lines.append(f"- Avg agreement: {_avg_with_denominator(s['agreement'], n)}")
    lines.append(
        f"- Retries: avg {_avg_with_denominator(s['retries'], n)} — "
        f"{_pct(s['retry_runs'], n)} of runs needed ≥1 retry"
    )
    lines.append(
        f"- Disputed: avg {_avg_with_denominator(s['disputed'], n)} — "
        f"{_pct(s['disputed_runs'], n)} of runs had ≥1 dispute"
    )
    lines.append(
        f"- Anchoring shift: A {_avg_with_denominator(s['anchoring_a'], n)}, "
        f"B {_avg_with_denominator(s['anchoring_b'], n)}"
    )
    return lines


def build_summary_md(all_rows: list) -> str:
    """Render the full summary: Overall block, then one block per policy."""
    lines = [
        "# Runs Summary",
        "",
        f"Generated from runs_index.csv — {len(all_rows)} run(s). "
        "Regenerate with `python analyze_runs.py`.",
        "",
        "## Overall",
        "",
    ]
    lines.extend(_render_block(summarize(all_rows), "###"))
    lines.append("")
    lines.append("## Per-policy")
    policies = sorted({r.get("policy", "N/A") for r in all_rows})
    if not policies:
        lines.append("")
        lines.append("_No runs recorded yet._")
    for p in policies:
        lines.append("")
        lines.append(f"### {p}")
        lines.append("")
        rows_p = [r for r in all_rows if r.get("policy", "N/A") == p]
        lines.extend(_render_block(summarize(rows_p), "####"))
    return "\n".join(lines) + "\n"
