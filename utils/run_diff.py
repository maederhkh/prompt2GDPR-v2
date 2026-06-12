"""
Run diff — clause-level comparison of two pipeline run JSONs.

Loads two run result files, joins each run's verified clauses to their final
labels, matches clauses across the runs by verbatim quote text (clause IDs are
per-run and unstable), and reports label changes, extraction differences, and
per-agent model differences. Prints to the terminal and writes one
diff_<a>_vs_<b>.md next to the runs. Read-only; stdlib + rapidfuzz; zero LLM
calls. The pipeline never invokes this — run on demand with:
    python diff_runs.py <run_a.json> <run_b.json>
"""

import json
from pathlib import Path

from rapidfuzz import fuzz

FUZZY_THRESHOLD = 90          # min rapidfuzz ratio for a cross-run quote match
REQUIRED_KEYS = ("policy_name", "verified_clauses", "finalizer_output")


def _normalize(text) -> str:
    """Lowercase + collapse whitespace, for quote comparison."""
    return " ".join(str(text).lower().split())


def load_run(path) -> dict:
    """
    Read one pipeline run JSON. Raises ValueError (with a readable reason)
    when the file is missing, not valid JSON, or not a run result file.
    """
    p = Path(path)
    if not p.exists():
        raise ValueError(f"file not found: {p}")
    try:
        with p.open(encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid JSON: {p} ({exc})")
    if not isinstance(data, dict) or any(k not in data for k in REQUIRED_KEYS):
        raise ValueError(f"not a pipeline run JSON (missing required keys): {p}")
    return data


def clause_labels(run: dict) -> list:
    """
    Within ONE run, join verified_clauses to finalizer clause_assessments by
    clause_id (IDs are consistent inside a single run). Returns one record per
    verified clause: {"clause_id", "quote", "label"}; clauses with no
    assessment get the label "(unassessed)".
    """
    fin = run.get("finalizer_output", {}) or {}
    labels = {}
    for a in fin.get("clause_assessments", []) or []:
        cid = a.get("clause_id")
        if cid is not None and cid not in labels:
            labels[cid] = a.get("clause_label") or "(unassessed)"
    return [
        {
            "clause_id": c.get("clause_id"),
            "quote": c.get("quote", ""),
            "label": labels.get(c.get("clause_id"), "(unassessed)"),
        }
        for c in run.get("verified_clauses", []) or []
    ]


def match_clauses(records_a: list, records_b: list) -> dict:
    """
    Match clause records across two runs by quote text, never by clause_id.
    Exact normalized match first, then a greedy best-score fuzzy pass
    (rapidfuzz ratio >= FUZZY_THRESHOLD), one-to-one. Returns
    {"pairs": [(rec_a, rec_b), ...], "only_a": [...], "only_b": [...]}.
    """
    pairs = []
    used_b = set()

    # Pass 1: exact normalized match.
    by_norm_b = {}
    for i, rb in enumerate(records_b):
        by_norm_b.setdefault(_normalize(rb["quote"]), []).append(i)
    leftovers_a = []
    for ra in records_a:
        free = [i for i in by_norm_b.get(_normalize(ra["quote"]), []) if i not in used_b]
        if free:
            used_b.add(free[0])
            pairs.append((ra, records_b[free[0]]))
        else:
            leftovers_a.append(ra)

    # Pass 2: fuzzy, greedy best-score-first, one-to-one.
    candidates = []
    for j, ra in enumerate(leftovers_a):
        norm_a = _normalize(ra["quote"])
        for i, rb in enumerate(records_b):
            if i in used_b:
                continue
            score = fuzz.ratio(norm_a, _normalize(rb["quote"]))
            if score >= FUZZY_THRESHOLD:
                candidates.append((score, j, i))
    candidates.sort(key=lambda t: (-t[0], t[1], t[2]))
    matched_a = set()
    for score, j, i in candidates:
        if j in matched_a or i in used_b:
            continue
        matched_a.add(j)
        used_b.add(i)
        pairs.append((leftovers_a[j], records_b[i]))

    only_a = [ra for j, ra in enumerate(leftovers_a) if j not in matched_a]
    only_b = [rb for i, rb in enumerate(records_b) if i not in used_b]
    return {"pairs": pairs, "only_a": only_a, "only_b": only_b}
