# Runs Summary (Analysis Helper) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A standalone, offline analyzer (`python analyze_runs.py`) that aggregates `output/results/runs_index.csv` into an Overall + Per-policy statistics summary, printed to the terminal and written to `output/results/runs_summary.md`.

**Architecture:** All logic lives in a new `utils/runs_summary.py` (loader → pure `summarize` → markdown renderer → `main` glue), built in three TDD layers. A ~10-line `analyze_runs.py` runner sits at the project root. The script is read-only with respect to the index, makes zero LLM calls, and is never invoked by the pipeline.

**Tech Stack:** Python 3.12, stdlib only (`csv`, `pathlib`, `collections`). No pytest — tests are standalone `assert` scripts run with `python tests/<file>.py` that print `OK`. Windows + PowerShell (chain with `;`). Git LF→CRLF warnings are cosmetic. `docs/` is gitignored (use `git add -f` only for docs; code/test files stage normally).

**Spec:** `docs/superpowers/specs/2026-06-11-runs-summary-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `utils/runs_summary.py` | Create | All logic: load + validate, summarize (pure), render markdown, `main()` |
| `analyze_runs.py` | Create | Root runner: calls `utils.runs_summary.main()` |
| `tests/test_runs_summary.py` | Create | Standalone assert tests, built up across Tasks 1–3 |

Key facts for the implementer:
- `utils/runs_index.py` exports `FIELDS` — the 15-column schema: `run_id, date, policy, policy_sha256, commit, overall_label, confidence, clauses, coverage, agreement_rate, retries, disputed, blind, anchoring_a, anchoring_b`. Import it; never copy the list.
- Index cells are strings. Sentinels: `N/A` and `—` (em dash). The **denominator rule**: non-numeric cells are excluded from averages/min/max, and every average reports `(from x of N runs)`.
- The `date` column is `YYYY-MM-DD HH:MM UTC` or `N/A`; the fixed format means plain string sorting orders dates correctly — no parsing.
- Do NOT commit `.claude/settings.local.json` (intentionally modified, must stay unstaged). Only `git add` the exact files named in each commit step.

---

## Task 1: Loader + `summarize` (the pure stats core)

**Files:**
- Create: `utils/runs_summary.py`
- Create: `tests/test_runs_summary.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_runs_summary.py` with EXACTLY this content:

```python
"""Standalone assert tests for the runs summary analyzer."""
import csv as _csv
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.runs_index import FIELDS
from utils.runs_summary import load_index_rows, summarize


def _row(**overrides):
    """One synthetic index row (all 15 fields, as strings, like the CSV)."""
    base = {
        "run_id": "20260611T100000Z",
        "date": "2026-06-11 10:00 UTC",
        "policy": "policy_short.txt",
        "policy_sha256": "abcd1234",
        "commit": "bae249d",
        "overall_label": "Compliant",
        "confidence": "high",
        "clauses": "10",
        "coverage": "high",
        "agreement_rate": "0.9",
        "retries": "0",
        "disputed": "0",
        "blind": "on",
        "anchoring_a": "0.2",
        "anchoring_b": "0.3",
    }
    base.update(overrides)
    return base


def test_summarize_counts_and_averages():
    rows = [
        _row(),
        _row(run_id="2", date="2026-06-10 09:00 UTC", overall_label="Non-Compliant",
             confidence="low", clauses="20", coverage="low", agreement_rate="0.7",
             retries="2", disputed="3"),
        _row(run_id="3", date="N/A", overall_label="N/A", confidence="N/A",
             clauses="0", coverage="—", agreement_rate="N/A",
             retries="0", disputed="0", anchoring_a="—", anchoring_b="—"),
    ]
    s = summarize(rows)
    assert s["runs"] == 3
    # N/A date excluded from the range, but the run still counts
    assert s["date_range"] == ("2026-06-10 09:00 UTC", "2026-06-11 10:00 UTC")
    assert s["clauses"]["min"] == 0 and s["clauses"]["max"] == 20
    assert s["clauses"]["n"] == 3
    assert s["coverage"] == {"high": 1, "low": 1, "unknown": 1, "fallback_rate": 0.5}
    assert s["labels"]["Compliant"] == 1 and s["labels"]["N/A"] == 1
    assert s["confidence"]["high"] == 1 and s["confidence"]["low"] == 1
    # denominator rule: the N/A agreement cell is excluded -> avg(0.9, 0.7) over 2 of 3
    assert abs(s["agreement"]["avg"] - 0.8) < 1e-9 and s["agreement"]["n"] == 2
    assert s["retry_runs"] == 1            # only run 2 had retries >= 1
    assert s["disputed_runs"] == 1         # only run 2 had disputed >= 1
    assert abs(s["anchoring_a"]["avg"] - 0.2) < 1e-9 and s["anchoring_a"]["n"] == 2


def test_summarize_all_na_column_is_none():
    rows = [_row(agreement_rate="N/A"), _row(run_id="2", agreement_rate="—")]
    s = summarize(rows)
    assert s["agreement"] is None


def test_fallback_rate_none_when_no_judged_runs():
    s = summarize([_row(coverage="—")])
    assert s["coverage"]["fallback_rate"] is None


def test_summarize_empty():
    s = summarize([])
    assert s["runs"] == 0 and s["date_range"] is None and s["clauses"] is None


def test_load_rejects_old_schema():
    d = Path(tempfile.mkdtemp())
    try:
        p = d / "runs_index.csv"
        with p.open("w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(["run_id", "policy"])          # old/unknown header
            w.writerow(["x", "y"])
        try:
            load_index_rows(p)
            assert False, "expected ValueError for old schema"
        except ValueError:
            pass
    finally:
        shutil.rmtree(d)


def test_load_well_formed_csv():
    d = Path(tempfile.mkdtemp())
    try:
        p = d / "runs_index.csv"
        r = _row()
        with p.open("w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(FIELDS)
            w.writerow([r[k] for k in FIELDS])
        rows = load_index_rows(p)
        assert len(rows) == 1
        assert rows[0]["run_id"] == "20260611T100000Z"
        assert rows[0]["coverage"] == "high"
    finally:
        shutil.rmtree(d)


if __name__ == "__main__":
    test_summarize_counts_and_averages()
    test_summarize_all_na_column_is_none()
    test_fallback_rate_none_when_no_judged_runs()
    test_summarize_empty()
    test_load_rejects_old_schema()
    test_load_well_formed_csv()
    print("OK")
```

- [ ] **Step 2: Run the tests to confirm they FAIL**

Run: `python tests/test_runs_summary.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'utils.runs_summary'`.

- [ ] **Step 3: Create `utils/runs_summary.py` (loader + stats core)**

Create `utils/runs_summary.py` with EXACTLY this content:

```python
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
```

- [ ] **Step 4: Run the tests to confirm they PASS**

Run: `python tests/test_runs_summary.py`
Expected output: `OK`

- [ ] **Step 5: Commit**

```bash
git add utils/runs_summary.py tests/test_runs_summary.py
git commit -m "feat: add runs-summary loader + summarize stats core"
```

---

## Task 2: Markdown rendering (`build_summary_md`)

**Files:**
- Modify: `utils/runs_summary.py` (append render functions)
- Modify: `tests/test_runs_summary.py` (add render tests)

- [ ] **Step 1: Add the failing render tests**

In `tests/test_runs_summary.py`, change the import line from:

```python
from utils.runs_summary import load_index_rows, summarize
```

to:

```python
from utils.runs_summary import load_index_rows, summarize, build_summary_md
```

Then add these two tests right after `test_load_well_formed_csv` (before the `__main__` block):

```python
def test_build_summary_md_per_policy():
    rows = [
        _row(policy="b_policy.txt"),
        _row(run_id="2", policy="a_policy.txt", coverage="low"),
    ]
    md = build_summary_md(rows)
    assert md.startswith("# Runs Summary")
    assert "## Overall" in md and "## Per-policy" in md
    # one section per distinct policy, alphabetical order
    ia = md.index("### a_policy.txt")
    ib = md.index("### b_policy.txt")
    assert ia < ib
    # denominator rendered on averages; fallback rate from 1 high / 1 low
    assert "(from 2 of 2 runs)" in md
    assert "fallback rate 50%" in md


def test_build_summary_md_empty():
    md = build_summary_md([])
    assert "0 run(s)" in md
    assert "## Overall" in md
    assert "_No runs recorded yet._" in md
```

And register both in the `__main__` block — change it to:

```python
if __name__ == "__main__":
    test_summarize_counts_and_averages()
    test_summarize_all_na_column_is_none()
    test_fallback_rate_none_when_no_judged_runs()
    test_summarize_empty()
    test_load_rejects_old_schema()
    test_load_well_formed_csv()
    test_build_summary_md_per_policy()
    test_build_summary_md_empty()
    print("OK")
```

- [ ] **Step 2: Run the tests to confirm they FAIL**

Run: `python tests/test_runs_summary.py`
Expected: FAIL — `ImportError: cannot import name 'build_summary_md'`.

- [ ] **Step 3: Append the render functions to `utils/runs_summary.py`**

Add EXACTLY this code at the end of `utils/runs_summary.py`:

```python
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
```

- [ ] **Step 4: Run the tests to confirm they PASS**

Run: `python tests/test_runs_summary.py`
Expected output: `OK`

- [ ] **Step 5: Commit**

```bash
git add utils/runs_summary.py tests/test_runs_summary.py
git commit -m "feat: render runs summary markdown (overall + per-policy blocks)"
```

---

## Task 3: `main()` glue + root runner

**Files:**
- Modify: `utils/runs_summary.py` (append `main`)
- Create: `analyze_runs.py`
- Modify: `tests/test_runs_summary.py` (add end-to-end tests)

- [ ] **Step 1: Add the failing end-to-end tests**

In `tests/test_runs_summary.py`, change the import line to:

```python
from utils.runs_summary import load_index_rows, summarize, build_summary_md, main
```

Add these three tests right after `test_build_summary_md_empty`:

```python
def test_main_end_to_end():
    d = Path(tempfile.mkdtemp())
    try:
        p = d / "runs_index.csv"
        with p.open("w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(FIELDS)
            for r in (_row(), _row(run_id="2", coverage="low", policy="other.txt")):
                w.writerow([r[k] for k in FIELDS])
        rc = main(output_dir=d)
        assert rc == 0
        out = (d / "runs_summary.md").read_text(encoding="utf-8")
        assert "## Overall" in out and "### other.txt" in out
    finally:
        shutil.rmtree(d)


def test_main_missing_index_writes_nothing():
    d = Path(tempfile.mkdtemp())
    try:
        rc = main(output_dir=d)
        assert rc == 0
        assert not (d / "runs_summary.md").exists()
    finally:
        shutil.rmtree(d)


def test_main_old_schema_writes_nothing():
    d = Path(tempfile.mkdtemp())
    try:
        p = d / "runs_index.csv"
        with p.open("w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(["run_id", "policy"])          # old header
        rc = main(output_dir=d)
        assert rc == 0
        assert not (d / "runs_summary.md").exists()
    finally:
        shutil.rmtree(d)
```

Register them in the `__main__` block — change it to:

```python
if __name__ == "__main__":
    test_summarize_counts_and_averages()
    test_summarize_all_na_column_is_none()
    test_fallback_rate_none_when_no_judged_runs()
    test_summarize_empty()
    test_load_rejects_old_schema()
    test_load_well_formed_csv()
    test_build_summary_md_per_policy()
    test_build_summary_md_empty()
    test_main_end_to_end()
    test_main_missing_index_writes_nothing()
    test_main_old_schema_writes_nothing()
    print("OK")
```

- [ ] **Step 2: Run the tests to confirm they FAIL**

Run: `python tests/test_runs_summary.py`
Expected: FAIL — `ImportError: cannot import name 'main'`.

- [ ] **Step 3: Append `main()` to `utils/runs_summary.py`**

First, add `import sys` to the imports at the top of `utils/runs_summary.py` — the import block becomes:

```python
import csv
import sys
from collections import Counter
from pathlib import Path

from utils.runs_index import FIELDS
```

Then add EXACTLY this at the end of the file:

```python
def main(output_dir="output/results") -> int:
    """
    Load the index from output_dir, print the summary to the terminal, and
    write runs_summary.md next to the index. Returns a process exit code
    (always 0 — a missing or outdated index is reported, not an error).
    """
    # Windows consoles/pipes may not be UTF-8; degrade gracefully instead of
    # crashing on em dashes/arrows when output is redirected.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    output_dir = Path(output_dir)
    csv_path = output_dir / "runs_index.csv"
    if not csv_path.exists():
        print(f"No runs index found at {csv_path} — run the pipeline first.")
        return 0
    try:
        rows = load_index_rows(csv_path)
    except ValueError as exc:
        print(f"Cannot summarize: {exc}")
        return 0

    md = build_summary_md(rows)
    print(md)
    out_path = output_dir / "runs_summary.md"
    out_path.write_text(md, encoding="utf-8")
    print(f"Summary written to {out_path}")
    return 0
```

- [ ] **Step 4: Create `analyze_runs.py` at the project root**

Create `analyze_runs.py` with EXACTLY this content:

```python
"""Print and write an aggregate summary of all pipeline runs.

Usage:  python analyze_runs.py
Reads output/results/runs_index.csv and writes output/results/runs_summary.md.
The runs index itself is never modified.
"""
import sys

from utils.runs_summary import main

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests to confirm they PASS**

Run: `python tests/test_runs_summary.py`
Expected output: `OK`

- [ ] **Step 6: Commit**

```bash
git add utils/runs_summary.py tests/test_runs_summary.py analyze_runs.py
git commit -m "feat: add analyze_runs entry point (terminal + runs_summary.md)"
```

---

## Task 4: Verification against the real index

**Files:** none (verification only)

- [ ] **Step 1: Run the real command**

Run: `python analyze_runs.py`

Expected: the full summary prints to the terminal (an `## Overall` block plus `## Per-policy` sections for each policy in the real index), followed by `Summary written to output\results\runs_summary.md`. If no real index exists on this machine, it prints `No runs index found at ... — run the pipeline first.` — that is also a PASS for this step (then verify with the offline end-to-end test from Task 3 instead).

- [ ] **Step 2: Sanity-check the written file**

Run: `python -c "from pathlib import Path; p = Path('output/results/runs_summary.md'); print(p.read_text(encoding='utf-8')[:400] if p.exists() else 'no summary file (no real index on this machine)')"`

Expected: the file starts with `# Runs Summary` and the `Generated from runs_index.csv — N run(s)` line (or the no-index message).

- [ ] **Step 3: Confirm the index was not modified**

Run: `git status --short`
Expected: no change to anything under `output/` tracked by git (output/ is gitignored anyway), and the ONLY modified tracked file is `.claude/settings.local.json` (pre-existing; do NOT stage or commit it).

- [ ] **Step 4: Final marker commit (allow empty)**

```bash
git commit --allow-empty -m "test: verify runs summary end-to-end against real index (offline)"
```

> Do NOT `git add` anything in this step. The commit is an empty marker. If you accidentally staged a file, unstage it with `git restore --staged <file>` before committing.

---

## Notes for the implementer

- **No pytest.** Run the test file directly: `python tests/test_runs_summary.py`; it prints `OK` on success.
- **Import `FIELDS` from `utils.runs_index`** — never duplicate the column list. The loader's header check is what keeps the summary honest if the schema changes again.
- **Denominator rule is the heart of the feature:** `N/A` and `—` cells are excluded from averages/min/max, and every average renders `(from x of N runs)`. Percent-of-runs metrics (retry rate, dispute rate, label distribution) always use the full run count `N`.
- **String-sorted dates are correct** because the `date` column has the fixed format `YYYY-MM-DD HH:MM UTC`; `N/A` dates are excluded from the range but the rows still count toward `runs`.
- **`main()` returns 0 in all handled cases** (missing index, old schema, success) — this is a reporting convenience tool; it should never fail a shell pipeline.
- **The pipeline is untouched.** Do not modify `main.py`, `utils/runs_index.py`, agents, or prompts.
- **Do not commit `.claude/settings.local.json`.** Only `git add` the exact files listed in each commit step.
