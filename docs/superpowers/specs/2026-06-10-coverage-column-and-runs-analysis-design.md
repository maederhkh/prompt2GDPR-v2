# Coverage Column + Runs Analysis Helper — Design Spec

**Date:** 2026-06-10
**Status:** Approved for planning
**Scope:** Two small, related post-processing features around the runs index. No pipeline-logic changes.

---

## 1. Goal

Two complementary additions that make the cumulative runs history more informative:

- **Feature A — Coverage column.** Surface each run's extraction-coverage status (`full` / `partial`) as a new column in `runs_index.md` / `.csv`, so partial-coverage runs are obvious across the whole history (today it is only visible in the per-run markdown report).
- **Feature B — Runs analysis helper.** A standalone, read-only command that loads `runs_index.csv` and prints aggregate statistics across all runs (label distribution, average agreement, average anchoring shift, total disputed clauses, partial-coverage count). Turns the raw log into thesis-ready findings.

Both are post-processing only: they read data the pipeline already produces. No LLM calls; no changes to agents, prompts, the retry loop, or run filenames. Feature B depends on Feature A (it reports the coverage aggregate), so A is built first.

---

## 2. Background — current behavior

- `utils/runs_index.py` writes a **14-field** index (since the 2026-06-09 date/newest-first change). `FIELDS` order today: `run_id, date, policy, policy_sha256, commit, overall_label, confidence, clauses, agreement_rate, retries, disputed, blind, anchoring_a, anchoring_b`.
- `append_run_to_index` already rewrites the file newest-first and, when the on-disk CSV header does not equal the current `FIELDS`, **backs the old files up to `.bak` and starts fresh**. This means a schema change (14 → 15 fields) needs **no new migration code** — the existing backup path handles it.
- The extraction-coverage flag already exists: `result["extractor_output"]["coverage_complete"]` (bool, defaults `True`). `utils/report_generator.py` already renders it per-run as "Coverage: Complete / Incomplete". It is **not** in the runs index.
- There is no tool to summarise the index across runs.

---

## 3. Feature A — Coverage column

### 3.1 Schema change (14 → 15 fields)

Insert a new field **`coverage`** immediately **after `clauses`** (both relate to extraction):

- **`FIELDS`** (15, in order): `run_id, date, policy, policy_sha256, commit, overall_label, confidence, clauses, coverage, agreement_rate, retries, disputed, blind, anchoring_a, anchoring_b`.
- **`MD_HEADERS`** (matching order): `Run ID, Date (UTC), Policy, Policy hash, Commit, Overall label, Confidence, Clauses, Coverage, Agreement, Retries, Disputed, Blind, Anchoring A, Anchoring B`.

### 3.2 Value source & rendering

`build_index_row` gains a `coverage` key (placed after `clauses`):

```
extractor_output = result.get("extractor_output", {}) or {}
coverage = "full" if extractor_output.get("coverage_complete", True) else "partial"
```

- Renders `full` when the flag is `True` or absent (mirrors `report_generator`'s default-True behavior).
- Renders `partial` when the flag is `False`.

### 3.3 Backward-compatibility (reuse existing mechanism)

No new code. When the new 15-field writer first runs against an existing 14-field `runs_index.csv`, its header will not equal the new `FIELDS`, so `append_run_to_index` renames the old `runs_index.csv` / `.md` to `.bak` and starts a fresh 15-column index. Old rows are preserved in the `.bak` files. (Same behavior the 2026-06-09 change introduced.)

---

## 4. Feature B — Runs analysis helper

### 4.1 Components

**New module `utils/runs_analysis.py`** (pure, testable):

- `load_index_rows(csv_path: Path) -> list[dict]`
  - Reads the CSV with `csv.DictReader`; returns a list of row dicts (keys = CSV header). Returns `[]` if the file does not exist.
- `summarize(rows: list[dict]) -> dict`
  - Computes, defensively (tolerant of `"N/A"`, `"—"`, blanks, and a missing `coverage` column from older files):
    - `runs`: `len(rows)`
    - `label_distribution`: ordered count of `overall_label` values (a plain `dict`, insertion-ordered by first appearance)
    - `avg_agreement_rate`: mean of numeric `agreement_rate` values, or `None` if none are numeric
    - `avg_anchoring_a`, `avg_anchoring_b`: mean of numeric `anchoring_a` / `anchoring_b` values, or `None`
    - `total_disputed`: sum of numeric `disputed` values (non-numeric counted as 0)
    - `partial_coverage`: count of rows whose `coverage` equals `"partial"`
    - `blind_on`: count of rows whose `blind` equals `"on"`
  - Helpers: `_to_float(v)` → `float` or `None`; `_to_int(v)` → `int` or `0`. Both treat `"N/A"`, `"—"`, `""`, and unparseable values as non-numeric.
- `format_summary(summary: dict) -> str`
  - Renders a human-readable multi-line block (see §4.3). Averages print to 2 decimals, or `n/a` when `None`. With `runs == 0`, returns a single line: `No runs found in index.`

**New CLI script `analyze_runs.py`** (project root, mirrors `main.py`'s placement):

- `argparse` with one option: `--index PATH` (default `output/results/runs_index.csv`).
- Loads rows via `load_index_rows`, summarises, prints `format_summary(...)`.
- If the index file is absent, prints `No runs index found at <path>.` and exits 0 (not an error — there may simply be no runs yet).

### 4.2 Data flow

```
python analyze_runs.py [--index output/results/runs_index.csv]
   → load_index_rows(path)   → list[dict]  (or [] if missing)
   → summarize(rows)         → aggregates dict
   → format_summary(summary) → text
   → print
```

### 4.3 Example output

```
Runs analyzed: 14

Label distribution:
  Compliant            5
  Partially compliant  7
  Non-compliant        2

Average agreement rate:  0.84
Average anchoring shift:  A = 0.31   B = 0.29
Total disputed clauses:  38
Partial-coverage runs:   3
Runs with blind labeler on: 11
```

---

## 5. Error handling

- **Missing `extractor_output` / coverage flag** → `coverage` is `full` (default-True, matches report). Row always written.
- **Missing index file (Feature B)** → `load_index_rows` returns `[]`; the CLI prints a friendly "no index/no runs" line and exits 0.
- **Non-numeric cells (`N/A`, `—`, blanks)** → skipped from averages, counted as 0 for sums; never raise.
- **Empty index (header only)** → `summarize` returns zero/empty aggregates; `format_summary` prints `No runs found in index.`
- Feature A's index writing remains wrapped in the existing `try/except` guard (never crashes a run).

---

## 6. Testing

Standalone assert scripts (no pytest; run `python tests/<file>.py`, prints `OK`; use the `sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))` shim).

**Feature A — extend `tests/test_runs_index.py`:**
- `FIELDS` now has 15 entries in the documented order; `coverage` sits immediately after `clauses`.
- `build_index_row` on a result with `extractor_output={"coverage_complete": False}` yields `row["coverage"] == "partial"`.
- `build_index_row` on a result with no `extractor_output` (or `coverage_complete` True) yields `row["coverage"] == "full"`.
- Existing append/newest-first/backup tests updated for the 15-field header.

**Feature B — new `tests/test_runs_analysis.py`:**
- `summarize` over a synthetic list of row dicts returns the expected `label_distribution`, `avg_agreement_rate` (mean of numeric values), `avg_anchoring_a/b`, `total_disputed`, `partial_coverage`, and `blind_on`.
- Non-numeric cells (`"N/A"`, `"—"`) are excluded from averages and do not raise.
- `summarize([])` returns `runs == 0`; `format_summary` of it is `No runs found in index.`
- `load_index_rows` on a missing path returns `[]`.
- `load_index_rows` round-trips a written CSV (write rows via `append_run_to_index` into a temp dir, then load and summarise).

---

## 7. Out of scope

- No per-clause export, cross-run diff, batch `--all` runner, or `.xlsx` (separate future options D/E/F/G).
- No charts/plots — text output only.
- No new third-party dependencies (stdlib `csv` only).
- No pipeline-logic, prompt, agent, or run-filename changes.
- Feature A does not change the per-run markdown report (it already shows coverage); it only adds the index column.
