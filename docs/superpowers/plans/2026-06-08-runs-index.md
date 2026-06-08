# Runs Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Append one summary row per pipeline run to a cumulative `runs_index.md` + `runs_index.csv`, replacing the old `model_usage_log.md`, so runs can be compared at a glance and loaded into Excel/pandas.

**Architecture:** A new pure-ish module `utils/runs_index.py` exposes `build_index_row(result)` (maps a result dict to 13 ordered fields, all defensive `.get()`) and `append_run_to_index(result, output_dir)` (creates/append the `.md` and `.csv`, header-once). `main.py`'s `save_result` calls it instead of the removed `_append_model_usage_log`. No pipeline-logic changes.

**Tech Stack:** Python 3.12, stdlib only (`csv`, `pathlib`). No test framework in this repo — tests are standalone `assert` scripts run with `python tests/<file>.py` that print `OK` on success. Python is `python` on PATH. Windows + PowerShell (chain commands with `;`, not `&&`). Git line-ending warnings (LF→CRLF) are cosmetic.

**Spec:** `docs/superpowers/specs/2026-06-08-runs-index-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `utils/runs_index.py` | Create | `build_index_row()` + `append_run_to_index()` (+ small `_` helpers) |
| `tests/test_runs_index.py` | Create | Standalone assert tests for both functions |
| `main.py` | Modify | Call `append_run_to_index`; remove `_append_model_usage_log` and its call |

---

## Task 1: Create `build_index_row` (TDD)

**Files:**
- Create: `utils/runs_index.py`
- Create: `tests/test_runs_index.py`

- [ ] **Step 1: Write the failing tests first**

Create `tests/test_runs_index.py` with EXACTLY this content. It uses the same `sys.path` shim as the other test files so it runs standalone from the project root.

```python
"""Standalone assert tests for the runs index builder."""
import csv as _csv
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.runs_index import build_index_row, append_run_to_index, FIELDS


def _full_result():
    return {
        "policy_name": "policy_short",
        "run_metadata": {
            "run_id": "20260607T143022Z",
            "policy_file": "policy_short.txt",
            "policy_sha256": "a1b2c3d4",
            "git_commit": {"sha": "cac701e", "dirty": True},
            "clause_count": 68,
            "blind_enabled": True,
        },
        "finalizer_output": {"overall_label": "Partially compliant", "confidence": "low"},
        "final_reflector_output": {"agreement_rate": 0.86},
        "retry_count": 1,
        "verified_clauses": [1] * 68,
        "label_panel": {
            "disputed_count": 26,
            "anchoring_summary": {
                "reflector_a": {"shift_rate": 0.35},
                "reflector_b": {"shift_rate": 0.37},
            },
        },
    }


def _empty_result():
    # Mirrors _empty_result() in main.py: no finalizer/label_panel, clause_count 0.
    return {
        "policy_name": "policy_short",
        "run_metadata": {
            "run_id": "20260101T000000Z",
            "policy_file": "policy_short.txt",
            "policy_sha256": "deadbeef",
            "git_commit": {"sha": "abc1234", "dirty": False},
            "clause_count": 0,
            "blind_enabled": False,
        },
        "error": "No verified clauses.",
        "extractor_output": {},
        "flagged_clauses": [],
    }


def test_build_index_row_full():
    row = build_index_row(_full_result())
    # exact field order matches FIELDS
    assert list(row.keys()) == FIELDS, list(row.keys())
    assert row["run_id"] == "20260607T143022Z"
    assert row["policy"] == "policy_short.txt"
    assert row["policy_sha256"] == "a1b2c3d4"
    assert row["commit"] == "cac701e (dirty)"
    assert row["overall_label"] == "Partially compliant"
    assert row["confidence"] == "low"
    assert row["clauses"] == 68
    assert row["agreement_rate"] == 0.86
    assert row["retries"] == 1
    assert row["disputed"] == 26
    assert row["blind"] == "on"
    assert row["anchoring_a"] == 0.35
    assert row["anchoring_b"] == 0.37


def test_build_index_row_empty_result():
    row = build_index_row(_empty_result())
    assert list(row.keys()) == FIELDS
    assert row["run_id"] == "20260101T000000Z"
    assert row["clauses"] == 0
    assert row["overall_label"] == "N/A"
    assert row["confidence"] == "N/A"
    assert row["agreement_rate"] == "N/A"
    assert row["disputed"] == 0
    assert row["blind"] == "off"
    assert row["commit"] == "abc1234"        # no (dirty) suffix
    assert row["anchoring_a"] == "—"     # em dash
    assert row["anchoring_b"] == "—"


def test_append_creates_then_appends():
    d = Path(tempfile.mkdtemp())
    try:
        append_run_to_index(_empty_result(), d)   # run_id ...0000Z
        append_run_to_index(_full_result(), d)     # run_id ...3022Z

        csv_path = d / "runs_index.csv"
        md_path = d / "runs_index.md"
        assert csv_path.exists() and md_path.exists()

        with csv_path.open(encoding="utf-8") as f:
            rows = list(_csv.reader(f))
        assert rows[0] == FIELDS                    # one header
        assert len(rows) == 3                        # header + 2 data rows
        assert rows[1][0] == "20260101T000000Z"
        assert rows[2][0] == "20260607T143022Z"

        md = md_path.read_text(encoding="utf-8")
        assert md.count("| Run ID |") == 1          # header table row appears once
        assert "20260101T000000Z" in md and "20260607T143022Z" in md
    finally:
        shutil.rmtree(d)


if __name__ == "__main__":
    test_build_index_row_full()
    test_build_index_row_empty_result()
    test_append_creates_then_appends()
    print("OK")
```

- [ ] **Step 2: Run the tests to confirm they FAIL**

Run: `python tests/test_runs_index.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'utils.runs_index'`.

- [ ] **Step 3: Implement `build_index_row` (and constants) in `utils/runs_index.py`**

Create `utils/runs_index.py` with EXACTLY this content (the append function is added in Task 2; for now the file has the constants + builder):

```python
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
```

- [ ] **Step 4: Verify the builder inline (the full test file can't import yet)**

The test file imports `append_run_to_index` at module top, so running it now raises `ImportError: cannot import name 'append_run_to_index'` before any test executes — that function arrives in Task 2. To confirm the builder itself is correct in this task, run this inline check (imports only what exists):

```bash
python -c "
import sys, os
sys.path.insert(0, '.')
from utils.runs_index import build_index_row, FIELDS
r = {'policy_name':'p','run_metadata':{'run_id':'20260607T143022Z','policy_file':'policy_short.txt','policy_sha256':'a1b2c3d4','git_commit':{'sha':'cac701e','dirty':True},'clause_count':68,'blind_enabled':True},'finalizer_output':{'overall_label':'Partially compliant','confidence':'low'},'final_reflector_output':{'agreement_rate':0.86},'retry_count':1,'verified_clauses':[1]*68,'label_panel':{'disputed_count':26,'anchoring_summary':{'reflector_a':{'shift_rate':0.35},'reflector_b':{'shift_rate':0.37}}}}
row = build_index_row(r)
assert list(row.keys()) == FIELDS
assert row['commit'] == 'cac701e (dirty)' and row['blind'] == 'on'
assert row['anchoring_a'] == 0.35 and row['anchoring_b'] == 0.37 and row['clauses'] == 68
# empty-result safety
e = build_index_row({'policy_name':'p','run_metadata':{'run_id':'x','policy_file':'f','policy_sha256':'h','git_commit':{'sha':'s','dirty':False},'clause_count':0,'blind_enabled':False}})
assert e['overall_label'] == 'N/A' and e['anchoring_a'] == '—' and e['blind'] == 'off'
print('builder OK')
"
```
Expected output: `builder OK`. (The complete `tests/test_runs_index.py` runs green at Task 2 Step 3, once `append_run_to_index` exists.)

- [ ] **Step 5: Commit**

```bash
git add utils/runs_index.py tests/test_runs_index.py
git commit -m "feat: add runs-index row builder (build_index_row)"
```

---

## Task 2: Add `append_run_to_index` (TDD)

**Files:**
- Modify: `utils/runs_index.py`
- Test: `tests/test_runs_index.py` (already written in Task 1; the append test now runs)

- [ ] **Step 1: Confirm the append test currently fails on import**

Run: `python tests/test_runs_index.py`
Expected: `ImportError: cannot import name 'append_run_to_index' from 'utils.runs_index'`.

- [ ] **Step 2: Implement `append_run_to_index` and its helpers**

Append the following to the END of `utils/runs_index.py` (after `build_index_row`):

```python
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
```

- [ ] **Step 3: Run the full test file to confirm all PASS**

Run: `python tests/test_runs_index.py`
Expected output: `OK`

- [ ] **Step 4: Confirm the module imports cleanly**

Run: `python -c "import utils.runs_index; print('OK')"`
Expected output: `OK`

- [ ] **Step 5: Commit**

```bash
git add utils/runs_index.py
git commit -m "feat: append run summary rows to runs_index.md and .csv"
```

---

## Task 3: Wire into `main.py` and remove the old model usage log

**Files:**
- Modify: `main.py`

> Line numbers below are approximate — locate anchors by their code content.

- [ ] **Step 1: Add the import**

In `main.py`, add this import alongside the other `from utils.... import ...` lines near the top (e.g. after `from utils.run_metadata import build_run_metadata`):

```python
from utils.runs_index import append_run_to_index
```

- [ ] **Step 2: Replace the log call inside `save_result`**

In `save_result` (around line 312-313), find:

```python
    # Cumulative model usage log — append one row per run for easy comparison
    _append_model_usage_log(result, output_dir, run_index)
```

Replace those two lines with:

```python
    # Cumulative runs index — append one summary row per run (md + csv)
    append_run_to_index(result, output_dir)
```

- [ ] **Step 3: Update the `save_result` docstring**

In `save_result` (around line 290-291), change the docstring:

```python
    """Save a run result to a JSON file, a markdown report, and the cumulative
    model usage log. Returns the JSON path."""
```

to:

```python
    """Save a run result to a JSON file, a markdown report, and the cumulative
    runs index (md + csv). Returns the JSON path."""
```

- [ ] **Step 4: Remove the now-unused `_append_model_usage_log` function**

In `main.py`, delete the ENTIRE `_append_model_usage_log` function definition (it begins with `def _append_model_usage_log(result: dict, output_dir: Path, run_index: int) -> None:` around line 320 and ends with its final `print(f"Model log updated: {log_path}")` line, roughly line 358). Remove the function body and the surrounding blank lines so no dangling references remain.

> After this, `grep`-confirm there are no remaining references: `_append_model_usage_log` must appear nowhere in `main.py`.

- [ ] **Step 5: Confirm no stale references and that main imports cleanly**

Run: `python -c "import main; print('OK')"`
Expected output: `OK`

Run: `grep -c "_append_model_usage_log" main.py`
Expected output: `0`

- [ ] **Step 6: Commit**

```bash
git add main.py
git commit -m "feat: use runs_index in save_result; remove old model usage log"
```

---

## Task 4: End-to-end (offline) verification

**Files:** none (verification only)

This avoids live API cost by driving the real `save_result` with two synthetic results, exactly like the run-metadata feature's offline check.

- [ ] **Step 1: Drive `save_result` twice and assert the index files**

Run:

```bash
python -c "
import os, glob, csv
from pathlib import Path
import main

d = Path('output/_idxcheck'); os.makedirs(d, exist_ok=True)
base = {'agent_models':{},'extractor_output':{},'verified_clauses':[1,2,3],'flagged_clauses':[],'evaluator_output':{},'final_reflector_output':{'agreement_rate':0.9},'finalizer_output':{'overall_label':'Compliant','confidence':'high'},'label_panel':{'disputed_count':2,'anchoring_summary':{'reflector_a':{'shift_rate':0.1},'reflector_b':{'shift_rate':0.2}}},'retry_count':0,'policy_name':'demo'}
for rid in ('20260608T090000Z','20260608T090030Z'):
    r = dict(base); r['run_metadata']={'run_id':rid,'policy_file':'policy_short.txt','policy_sha256':'cafef00d','git_commit':{'sha':'bae249d','dirty':False},'clause_count':3,'blind_enabled':True}
    main.save_result(r, d, run_index=1)

with (d/'runs_index.csv').open(encoding='utf-8') as f:
    rows = list(csv.reader(f))
print('csv rows (incl header):', len(rows))
print('header:', rows[0])
print('data run_ids:', rows[1][0], rows[2][0])
assert len(rows) == 3, 'expected header + 2 data rows'
md = (d/'runs_index.md').read_text(encoding='utf-8')
assert md.count('| Run ID |') == 1, 'header should appear once'
assert '20260608T090000Z' in md and '20260608T090030Z' in md
print('PASS: runs_index.md + .csv accumulate one row per run, single header')
"
```
Expected: `csv rows (incl header): 3`, both run_ids printed, and `PASS: ...`.

- [ ] **Step 2: Confirm the old log is no longer written**

Run:

```bash
python -c "
import glob
print('model_usage_log in idxcheck dir:', glob.glob('output/_idxcheck/model_usage_log.md'))
assert glob.glob('output/_idxcheck/model_usage_log.md') == [], 'old log should NOT be created'
print('OK - model_usage_log.md no longer produced')
"
```
Expected: empty list and `OK - model_usage_log.md no longer produced`.

- [ ] **Step 3: Clean up the throwaway dir (output/ is gitignored)**

```bash
python -c "import shutil; shutil.rmtree('output/_idxcheck', ignore_errors=True); print('cleaned')"
```

- [ ] **Step 4: Final commit (marker, allow empty)**

```bash
git add -A
git commit -m "test: verify runs index accumulates rows end-to-end (offline)" --allow-empty
```

> `output/` is gitignored, so `git add -A` should stage nothing from it. If it would stage any unexpected non-output file (e.g. `.claude/settings.local.json`), do NOT commit that file — unstage it with `git restore --staged <file>` first, then commit empty.

---

## Notes for the implementer

- **No pytest in this repo.** Run test files directly with `python tests/<file>.py`; they print `OK` on success.
- **The index must never crash a run.** `append_run_to_index` swallows all exceptions and prints a warning. Do not remove that guard.
- **Do not touch pipeline logic, prompts, agents, the retry loop, or run filenames.** This feature is post-processing only.
- **`FIELDS` is the single source of column order** — `build_index_row` keys, the CSV header, and (positionally) `MD_HEADERS` all follow it. Keep them aligned.
- **The old `model_usage_log.md`** is intentionally NOT deleted from disk — it just stops being written.
