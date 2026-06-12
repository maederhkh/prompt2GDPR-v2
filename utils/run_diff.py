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
import sys
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


SNIPPET_LEN = 60


def _snippet(quote) -> str:
    """First ~60 chars of a quote (whitespace-collapsed), with an ellipsis."""
    q = " ".join(str(quote).split())
    return q if len(q) <= SNIPPET_LEN else q[:SNIPPET_LEN] + "…"


def build_diff(run_a: dict, run_b: dict, name_a: str, name_b: str) -> dict:
    """Pure function: two run dicts -> one diff structure (see render_diff_md)."""
    fin_a = run_a.get("finalizer_output", {}) or {}
    fin_b = run_b.get("finalizer_output", {}) or {}
    matched = match_clauses(clause_labels(run_a), clause_labels(run_b))
    changed = [(ra, rb) for ra, rb in matched["pairs"] if ra["label"] != rb["label"]]

    models_a = run_a.get("agent_models", {}) or {}
    models_b = run_b.get("agent_models", {}) or {}
    models = [
        {
            "agent": agent,
            "a": models_a.get(agent, "N/A"),
            "b": models_b.get(agent, "N/A"),
            "changed": models_a.get(agent, "N/A") != models_b.get(agent, "N/A"),
        }
        for agent in sorted(set(models_a) | set(models_b))
    ]

    return {
        "name_a": name_a,
        "name_b": name_b,
        "policy_a": run_a.get("policy_name", "N/A"),
        "policy_b": run_b.get("policy_name", "N/A"),
        "same_policy": run_a.get("policy_name") == run_b.get("policy_name"),
        "overall": {"a": fin_a.get("overall_label", "N/A"), "b": fin_b.get("overall_label", "N/A")},
        "confidence": {"a": fin_a.get("confidence", "N/A"), "b": fin_b.get("confidence", "N/A")},
        "models": models,
        "models_changed": [m["agent"] for m in models if m["changed"]],
        "changed": changed,
        "unchanged_count": len(matched["pairs"]) - len(changed),
        "only_a": matched["only_a"],
        "only_b": matched["only_b"],
        "clause_counts": (len(run_a.get("verified_clauses", []) or []),
                          len(run_b.get("verified_clauses", []) or [])),
    }


def _verdict(a, b) -> str:
    return "same" if a == b else "⚠ changed"


def _only_section(title: str, records: list) -> list:
    """Render one 'Only in <run>' section as markdown lines."""
    lines = [f"## Only in {title} ({len(records)})"]
    if records:
        lines.extend(f'- "{_snippet(r["quote"])}" — {r["label"]}' for r in records)
    else:
        lines.append("_None._")
    return lines


def render_diff_md(diff: dict) -> str:
    """Render the diff structure as the markdown document."""
    na, nb = diff["name_a"], diff["name_b"]
    lines = [f"# Run Diff: {na} vs {nb}", ""]
    if diff["same_policy"]:
        lines.append(f"Policy: {diff['policy_a']}")
    else:
        lines.append(
            f"⚠ WARNING: these runs are for DIFFERENT policies "
            f"({diff['policy_a']} vs {diff['policy_b']})"
        )
    o, c = diff["overall"], diff["confidence"]
    lines.append(f"Overall label: {o['a']} → {o['b']} ({_verdict(o['a'], o['b'])})")
    lines.append(f"Confidence: {c['a']} → {c['b']} ({_verdict(c['a'], c['b'])})")
    counts = diff["clause_counts"]
    lines.append(f"Clauses: {counts[0]} vs {counts[1]}")
    mc = diff["models_changed"]
    lines.append(
        "Models: identical" if not mc
        else f"Models: ⚠ {len(mc)} agent(s) differ ({', '.join(mc)})"
    )
    lines.append("")

    lines.append("## Models")
    if diff["models"]:
        lines.append(f"| Agent | {na} | {nb} | |")
        lines.append("|---|---|---|---|")
        for m in diff["models"]:
            mark = "⚠ changed" if m["changed"] else "same"
            lines.append(f"| {m['agent']} | {m['a']} | {m['b']} | {mark} |")
    else:
        lines.append("_No model information in either run._")
    lines.append("")

    lines.append(f"## Label changes ({len(diff['changed'])})")
    if diff["changed"]:
        lines.append(f"| Clause (start of quote) | {na} | {nb} |")
        lines.append("|---|---|---|")
        for ra, rb in diff["changed"]:
            lines.append(f'| "{_snippet(ra["quote"])}" | {ra["label"]} | {rb["label"]} |')
    else:
        lines.append("_None._")
    lines.append("")

    lines.extend(_only_section(na, diff["only_a"]))
    lines.append("")
    lines.extend(_only_section(nb, diff["only_b"]))
    lines.append("")

    lines.append("## Unchanged")
    lines.append(f"{diff['unchanged_count']} clause(s) had the same label in both runs.")
    return "\n".join(lines) + "\n"


def main(path_a, path_b, output_dir="output/results") -> int:
    """
    Diff two run JSONs: print the comparison to the terminal and write
    diff_<a>_vs_<b>.md into output_dir. Returns a process exit code (always
    0 — bad input is reported, not an error; this tool must never fail a
    shell pipeline).
    """
    # Windows consoles/pipes may not be UTF-8; degrade gracefully instead of
    # crashing on em dashes/arrows when output is redirected.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    try:
        run_a = load_run(path_a)
        run_b = load_run(path_b)
    except ValueError as exc:
        print(f"Cannot diff: {exc}")
        return 0

    name_a, name_b = Path(path_a).stem, Path(path_b).stem
    md = render_diff_md(build_diff(run_a, run_b, name_a, name_b))
    print(md)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"diff_{name_a}_vs_{name_b}.md"
    out_path.write_text(md, encoding="utf-8")
    print(f"Diff written to {out_path}")
    return 0
