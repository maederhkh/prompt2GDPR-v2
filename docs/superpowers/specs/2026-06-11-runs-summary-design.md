# Runs Summary (Analysis Helper) — Design Spec

**Date:** 2026-06-11
**Status:** Approved for planning
**Scope:** A standalone, offline analyzer that aggregates `runs_index.csv` into a human-readable summary (terminal + `runs_summary.md`). Zero LLM calls, zero pipeline coupling. This is "Feature B," deferred from the 2026-06-10 extraction-mode spec.

---

## 1. Goal

The runs index records one row per pipeline run but never *summarizes*. Questions like "how often is the verdict Compliant?", "what is my average reflector agreement?", or "how often does extraction fall back to single-pass?" currently require manual Excel/pandas work.

This feature adds an on-demand command:

```
python analyze_runs.py
```

that reads `output/results/runs_index.csv`, computes aggregate statistics, **prints the summary to the terminal**, and **writes `output/results/runs_summary.md`**.

Key properties:

- **Separate artifact.** The summary is a derived view. It never modifies the index. It is rebuilt from scratch on every invocation (no syncing logic; safe to delete anytime).
- **Manual refresh.** The summary updates only when the user runs the script. Pipeline runs (`main.py`) do not touch it.
- **Offline.** Reads a local CSV; makes no API calls.

## 2. Background — current behavior

- `utils/runs_index.py` defines the 15-field schema (`FIELDS`) and appends one row per run to `runs_index.csv` / `runs_index.md`, newest on top.
- Columns: `run_id, date, policy, policy_sha256, commit, overall_label, confidence, clauses, coverage, agreement_rate, retries, disputed, blind, anchoring_a, anchoring_b`.
- Cells are text. Some hold sentinels rather than numbers: `N/A` (e.g. agreement on failed runs) and `—` (EM_DASH; e.g. anchoring when blind is off, coverage on pre-flag runs).
- There is no aggregation anywhere in the repo.

## 3. Feature design

### 3.1 Files

| File | Action | Responsibility |
|---|---|---|
| `utils/runs_summary.py` | Create | All logic: load, summarize, render, write |
| `analyze_runs.py` (project root) | Create | ~10-line runner that calls `utils.runs_summary.main()` |
| `tests/test_runs_summary.py` | Create | Standalone assert tests over synthetic rows |

Output: `output/results/runs_summary.md` (same directory as the index).

### 3.2 `utils/runs_summary.py` — public functions

- **`load_index_rows(csv_path) -> list[dict]`**
  Reads the CSV. Validates that the header equals `runs_index.FIELDS` (imported, so the schema can never drift). Returns each data row as a `dict` keyed by field name.

- **`summarize(rows) -> dict`**
  Pure function: list of row-dicts → one stats block (see 3.3). No I/O.

- **`build_summary_md(all_rows) -> str`**
  Renders the full markdown document: an **Overall** section (`summarize(all_rows)`), then a **Per-policy** section with one block per distinct `policy` value (rows grouped by exact `policy` string, sections ordered alphabetically).

- **`main(output_dir=Path("output/results"))`**
  Glue: load → build → `print()` the markdown to the terminal → write `runs_summary.md` into `output_dir`.

### 3.3 Summary content (one block; appears once Overall, once per policy)

**Volume & coverage**
- Run count
- Date range: oldest → newest (from the `date` column; rows with `N/A` dates excluded from the range, but still counted as runs)
- Clauses: average / min / max
- Coverage: counts of `high` / `low` / `—`(unknown), plus **fallback rate** = low ÷ (high + low), shown as `%` (omitted when high + low = 0)

**Compliance outcomes**
- `overall_label`: count and % per distinct value (including `N/A` as its own bucket)
- `confidence`: count and % per distinct value

**Reliability**
- Average `agreement_rate`
- Average `retries` and % of runs with ≥ 1 retry
- Average `disputed` and % of runs with ≥ 1 disputed clause
- Average `anchoring_a`, average `anchoring_b`

### 3.4 Numeric hygiene (the "denominator rule")

CSV cells are strings; sentinel values must never distort statistics:

- A cell is **numeric** if `float(value)` succeeds. `N/A`, `—`, and empty cells are non-numeric.
- Averages (and min/max) are computed **only over numeric cells**, and every average **reports its denominator**: e.g. `Avg agreement: 0.88 (from 5 of 7 runs)`.
- If a column has zero numeric cells, the line renders `n/a (0 of N runs)`.
- Percent-of-runs metrics (retry rate, dispute rate, label distribution) use the full run count as denominator; non-numeric `retries`/`disputed` cells count as not-≥1.

### 3.5 Output format (`runs_summary.md`)

```markdown
# Runs Summary

Generated from runs_index.csv — <N> run(s). Regenerate with `python analyze_runs.py`.

## Overall

### Volume & coverage
- Runs: ...
- Date range: ... → ...
- Clauses: avg ... (min ..., max ...)
- Coverage: ... high / ... low / ... unknown — fallback rate ...%

### Compliance outcomes
- Overall label: Compliant ... (..%), Partially compliant ... (..%), ...
- Confidence: high ... (..%), low ... (..%), ...

### Reliability
- Avg agreement: ... (from x of N runs)
- Retries: avg ... — ..% of runs needed ≥1 retry
- Disputed: avg ... — ..% of runs had ≥1 dispute
- Anchoring shift: A ... (from x of N), B ... (from x of N)

## Per-policy

### <policy_file_1>
(same block)

### <policy_file_2>
(same block)
```

The exact wording may be polished at implementation time; the structure (Overall block + identical per-policy blocks; denominators on every average) is fixed.

## 4. Error handling

| Condition | Behavior |
|---|---|
| `runs_index.csv` missing | Print "No runs index found at <path> — run the pipeline first." Exit code 0; nothing written. |
| Header ≠ current `FIELDS` | Print that the index uses an older/unknown schema and cannot be summarized. Exit code 0; nothing written. (The pipeline's own `.bak` migration will refresh the index on its next run.) |
| Empty index (header only) | Report "0 runs"; write a minimal summary saying so. |
| Sentinel cells (`N/A`, `—`) | Excluded from numeric stats per 3.4; never crash. |

The script is read-only with respect to the index; the only file it writes is `runs_summary.md`.

## 5. Testing

Standalone assert script (`python tests/test_runs_summary.py`, prints `OK`; `sys.path` shim like the others). No pytest.

- `summarize`: counts, label/confidence distributions, fallback rate, averages with mixed numeric + `N/A`/`—` cells (denominator rule verified exactly), zero-numeric column → `n/a`.
- `build_summary_md`: Overall + one section per distinct policy; alphabetical policy order; denominators rendered.
- `load_index_rows`: schema-mismatch header rejected; well-formed file loads as dicts.
- End-to-end offline: write a temp CSV with the real `FIELDS` header + synthetic rows → run `main(output_dir=tmp)` → assert `runs_summary.md` exists and contains expected lines.

## 6. Out of scope

- Auto-refresh from `main.py` after each run (possible later upgrade; explicitly decoupled for now).
- Plots/charts, `.xlsx`/HTML output, cross-run clause-level diffs.
- New third-party dependencies (stdlib only: `csv`, `pathlib`, `collections`).
- Any change to `runs_index.py`, the pipeline, prompts, or agents.
