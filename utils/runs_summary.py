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
