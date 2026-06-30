# Total Run Duration in the Runs Index — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `Duration (s)` column to the cumulative runs index, showing each run's total wall-clock time summed from the `run_trace` execution-timeline events the pipeline already records.

**Architecture:** A single-file change to `utils/runs_index.py`: append `"duration_s"` to the shared `FIELDS` list and `"Duration (s)"` to `MD_HEADERS`, and compute the summed duration in `build_index_row`. The existing schema-migration logic in `append_run_to_index` upgrades old indexes automatically, and `main.py` already passes the full result dict (including `run_trace`), so no wiring changes.

**Tech Stack:** Python 3.12, standard library only. Tests are standalone assert scripts. Dev machine is Windows + PowerShell (chain with `;`, never `&&`).

## Global Constraints

- **Offline only.** No LLM/network/API key in any automated test. Do NOT run `main.py`'s real pipeline (it needs `OPENROUTER_API_KEY`).
- Tests are **standalone assert scripts** (NOT pytest): each `tests/test_*.py` adds the repo root to `sys.path`, defines `test_*()` functions, and a `__main__` block that calls them and prints `OK`; any failure raises and exits non-zero. Run a suite with `python tests/<file>.py`.
- **Single new column only.** The change adds exactly one field (`duration_s`) to the runs index. No other index column changes; no change to the per-run JSON, the report, `run_trace`, `runs_summary.py`, `batch_comparison.py`, `run_diff.py`, or `main.py`.
- **Missing trace renders `—`** (the file's existing `EM_DASH` value), never `0.0`. The summed value is rounded to **1 decimal place**.
- `docs/` is gitignored. `utils/`, `tests/` are NOT gitignored and stage normally.
- Do NOT commit `.claude/settings.local.json` or anything under `.superpowers/`. Only `git add` the exact files named in the commit step (never `git add -A`).

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `utils/runs_index.py` | Modify | Add `duration_s` to `FIELDS` and `Duration (s)` to `MD_HEADERS`; compute the summed run duration in `build_index_row`. |
| `tests/test_runs_index.py` | Modify | Add a `run_trace` to the full-result fixture; assert the summed `duration_s` (with trace) and `—` (without); assert `MD_HEADERS` and `FIELDS` stay the same length. |

**`run_trace` event shape** (already produced by the pipeline; this feature only reads `duration_s`):

```python
{"step": int, "stage": str, "model": str | None, "duration_s": float, "status": str, "note": str}
```

---

## Task 1: Add the duration column to the runs index

**Files:**
- Modify: `utils/runs_index.py`
- Test: `tests/test_runs_index.py`

**Interfaces:**
- Consumes: `result["run_trace"]` — a list of event dicts each carrying a `duration_s` float (or absent/empty on older / empty-result runs).
- Produces: `build_index_row(result)` returns a dict that now ends with a `"duration_s"` key — `round(sum of durations, 1)` when a trace is present, else `EM_DASH`. `FIELDS` and `MD_HEADERS` each gain one trailing entry.

- [ ] **Step 1: Update the test to add the failing assertions**

In `tests/test_runs_index.py`, make three edits.

(a) Change the import line (line 11) to also import `MD_HEADERS`:

```python
from utils.runs_index import build_index_row, append_run_to_index, FIELDS, MD_HEADERS
```

(b) In `_full_result()`, add a `run_trace` entry as the last key of the returned dict. The dict currently ends:

```python
        "extractor_output": {"extraction_mode": "two_pass"},
    }
```

Change it to:

```python
        "extractor_output": {"extraction_mode": "two_pass"},
        "run_trace": [
            {"step": 1, "stage": "extractor", "model": "m1", "duration_s": 16.8, "status": "ok", "note": ""},
            {"step": 2, "stage": "verifier", "model": None, "duration_s": 0.3, "status": "ok", "note": ""},
            {"step": 3, "stage": "evaluator", "model": "m2", "duration_s": 14.6, "status": "ok", "note": ""},
        ],
    }
```

(c) Add a `duration_s` assertion at the end of `test_build_index_row_full` (after the `anchoring_b` assertion on line 77):

```python
    assert row["duration_s"] == 31.7   # 16.8 + 0.3 + 14.6, rounded to 1 dp
```

(d) Add a `duration_s` assertion at the end of `test_build_index_row_empty_result` (after the `anchoring_b` assertion on line 94):

```python
    assert row["duration_s"] == "—"    # no run_trace -> em dash
```

(e) Add a new test function (after `test_build_index_row_single_pass_coverage`, before `test_append_newest_first`) that guards the two parallel lists staying in sync:

```python
def test_headers_align_with_fields():
    # MD_HEADERS and FIELDS must stay the same length: one Markdown column per field.
    assert len(MD_HEADERS) == len(FIELDS), (len(MD_HEADERS), len(FIELDS))
```

(f) Register the new test in the `__main__` block (after the `test_build_index_row_single_pass_coverage()` call):

```python
    test_headers_align_with_fields()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_runs_index.py`
Expected: FAIL — `test_build_index_row_full` raises `KeyError: 'duration_s'` (the field does not exist yet), or the field-order assertion fails. Either way, a non-zero exit, no `OK`.

- [ ] **Step 3: Implement the column in `utils/runs_index.py`**

(a) Append `"duration_s"` to the `FIELDS` list. The list currently ends:

```python
    "anchoring_a",
    "anchoring_b",
]
```

Change it to:

```python
    "anchoring_a",
    "anchoring_b",
    "duration_s",
]
```

(b) Append `"Duration (s)"` to the `MD_HEADERS` list. It currently ends:

```python
    "Anchoring A",
    "Anchoring B",
]
```

Change it to:

```python
    "Anchoring A",
    "Anchoring B",
    "Duration (s)",
]
```

(c) In `build_index_row`, compute the duration just before the `return {` statement. The function body currently ends with the assembly of `sha`/`commit` and then the return dict:

```python
    sha = gc.get("sha", "unknown")
    commit = f"{sha} (dirty)" if gc.get("dirty") else sha

    return {
```

Change it to:

```python
    sha = gc.get("sha", "unknown")
    commit = f"{sha} (dirty)" if gc.get("dirty") else sha

    run_trace = result.get("run_trace") or []
    duration_s = round(sum(e.get("duration_s") or 0 for e in run_trace), 1) if run_trace else EM_DASH

    return {
```

(d) Add the `duration_s` entry as the **last** key of the returned dict. It currently ends:

```python
        "anchoring_a": _anchoring(lp, "reflector_a"),
        "anchoring_b": _anchoring(lp, "reflector_b"),
    }
```

Change it to:

```python
        "anchoring_a": _anchoring(lp, "reflector_a"),
        "anchoring_b": _anchoring(lp, "reflector_b"),
        "duration_s": duration_s,
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python tests/test_runs_index.py`
Expected: `OK`.

- [ ] **Step 5: Run the full offline suite**

```powershell
Get-ChildItem tests/test_*.py | ForEach-Object { Write-Host "=== $($_.Name) ==="; python $_.FullName; if ($LASTEXITCODE -ne 0) { throw "FAILED: $($_.Name)" } }
```
Expected: every suite prints `OK`; no `FAILED:` thrown.

- [ ] **Step 6: Commit**

```bash
git add utils/runs_index.py tests/test_runs_index.py
git commit -m "feat: add total run duration column to the runs index"
```

Then run `git status --short` and confirm no unintended files are staged (only `utils/runs_index.py` and `tests/test_runs_index.py`; `.claude/settings.local.json` and `.superpowers/` must NOT appear as staged).

---

## Notes for the implementer

- **No pytest.** Run a suite directly: `python tests/<file>.py`; success prints `OK`, failure exits non-zero.
- **Offline only.** No network/LLM call; never invoke the real pipeline (`main()` / `run_pipeline`).
- **The sum coalesces each `duration_s` with `or 0`** so a malformed event can't raise; the whole computation sits inside the already-defensive `build_index_row`.
- **`EM_DASH` is already defined** in `utils/runs_index.py` (the `"—"` constant) — reuse it, do not introduce a new literal.
- **The schema migration is automatic.** A 16-field header no longer matches an existing 15-field `runs_index.csv`, so `append_run_to_index` backs the old files up to `.bak` and starts fresh — this is the file's existing, tested behavior (`test_schema_mismatch_backs_up`). No new migration code, and that test still passes because it asserts `rows[0] == FIELDS` dynamically.
- **Float note:** `16.8 + 0.3 + 14.6` is `31.700000000000003` in float; `round(..., 1)` yields exactly `31.7`, so the equality assertion holds.
