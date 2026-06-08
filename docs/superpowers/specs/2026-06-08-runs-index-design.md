# Runs Index — Design Spec

**Date:** 2026-06-08
**Status:** Approved for planning
**Scope:** Small, self-contained usability step. No pipeline-logic changes.

---

## 1. Goal

Give the project a **cumulative history of every pipeline run** — one row per run — so runs can be compared at a glance and loaded into Excel/pandas for analysis, instead of being inspected one scattered output file at a time.

The history is emitted in two synchronized views built from the same row data:

- `runs_index.md` — a readable Markdown table (quick glance in-editor / on GitHub).
- `runs_index.csv` — the same rows as CSV (opens directly in Excel; loads in pandas).

This replaces the existing primitive per-run log (`output/results/model_usage_log.md`), which predates run-metadata, the label panel, and the anchoring measurement.

This is a deliberately small step. It is post-processing only: it reads the result dict the pipeline already produces and appends a row. No LLM calls, no changes to agents, prompts, or the retry loop.

---

## 2. Background — current behavior

- `main.py` defines `_append_model_usage_log(result, output_dir, run_index)`, called from `save_result`. It appends one row to `output/results/model_usage_log.md` with columns: `Run | Date | Policy | Scout | Extractor | Evaluator | Reflector A | Reflector B | Finalizer | Clauses | Label | Retries`.
- Limitations that motivate the replacement:
  - Its `Run` column is the `run_index` from the `--runs` loop, which **resets to 1 every invocation** (the same overwrite-class bug that run-metadata's `run_id` fixed for filenames).
  - It has **no** `run_id`, `git_commit`, `agreement_rate`, anchoring shift, or dispute count.
  - It spends six columns on model slugs that rarely change between runs and are already stored per-run in `result["agent_models"]`.
- The result dict already contains everything the new index needs:
  - `result["run_metadata"]` → `run_id`, `policy_file`, `policy_sha256`, `git_commit{sha,dirty}`, `clause_count`, `blind_enabled`.
  - `result["finalizer_output"]` → `overall_label`, `confidence`.
  - `result["final_reflector_output"]` → `agreement_rate`.
  - `result["retry_count"]`.
  - `result["label_panel"]` → `disputed_count`, `anchoring_summary.reflector_a.shift_rate`, `anchoring_summary.reflector_b.shift_rate`.

---

## 3. The index row — complete column reference

Each row represents **one completed pipeline run** (one policy taken through the whole pipeline once). Rows are appended in run order; because `run_id` is a UTC timestamp, the table also sorts chronologically.

There are **13 CSV fields** (12 logical columns, with anchoring split into two adjacent fields `anchoring_a` and `anchoring_b` so the CSV holds one value per cell). Both the `.md` and `.csv` use the same 13 fields in the same order:

| # | Column (CSV header) | MD header | Type | Source field | Notes |
|---|---|---|---|---|---|
| 1 | `run_id` | Run ID | str | `run_metadata.run_id` | Primary key; matches the output filename stem. |
| 2 | `policy` | Policy | str | `run_metadata.policy_file` | Falls back to `result.policy_name`. |
| 3 | `policy_sha256` | Policy hash | str | `run_metadata.policy_sha256` | 8-char content fingerprint. |
| 4 | `commit` | Commit | str | `run_metadata.git_commit.sha` | Append ` (dirty)` when `git_commit.dirty` is true. |
| 5 | `overall_label` | Overall label | str | `finalizer_output.overall_label` | The official compliance label. |
| 6 | `confidence` | Confidence | str | `finalizer_output.confidence` | e.g. `low`/`medium`/`high`. |
| 7 | `clauses` | Clauses | int | `run_metadata.clause_count` | Verified clause count. |
| 8 | `agreement_rate` | Agreement | float | `final_reflector_output.agreement_rate` | Inter-reflector agreement (0–1). |
| 9 | `retries` | Retries | int | `retry_count` | Reflector-driven retry passes. |
| 10 | `disputed` | Disputed | int | `label_panel.disputed_count` | Clauses where labelers disagreed. |
| 11 | `blind` | Blind | str | `run_metadata.blind_enabled` | Rendered `on` / `off`. |
| 12a | `anchoring_a` | Anchoring A | float or `—` | `label_panel.anchoring_summary.reflector_a.shift_rate` | `—` when blind disabled / summary absent. |
| 12b | `anchoring_b` | Anchoring B | float or `—` | `label_panel.anchoring_summary.reflector_b.shift_rate` | `—` when blind disabled / summary absent. |

> The two anchoring values are conceptually one group but occupy two columns (`anchoring_a`, `anchoring_b`) so the CSV stays one value per cell.

### 3.1 Deliberately excluded columns
- **Per-agent model slugs** — already in `result["agent_models"]` and each run's JSON; omitting them keeps the table narrow. (The previous log's six model columns are intentionally dropped.)
- **Per-clause detail** — out of scope; that is a separate future per-clause export (one row per clause), not this run-summary index.

### 3.2 Example row (Markdown)

```
| 20260607T143022Z | policy_short | a1b2c3d4 | cac701e | Partially compliant | low | 68 | 0.86 | 1 | 26 | on | 0.35 | 0.37 |
```

When blind is disabled the last two cells render `—` and `blind` renders `off`.

---

## 4. Components and responsibilities

### 4.1 New file: `utils/runs_index.py`
A small, mostly-pure module.

- `build_index_row(result: dict) -> dict`
  - Pure function. Maps a result dict to an ordered dict of the 13 field values (keys = CSV headers in §3).
  - Uses defensive `.get(...)` with fallbacks throughout — never raises on a missing key.
  - `commit`: `sha` plus ` (dirty)` suffix when dirty is true; `sha` defaults to `unknown`.
  - `blind`: `on`/`off` from `blind_enabled`.
  - `anchoring_a`/`anchoring_b`: the two `shift_rate` values, or `—` when `anchoring_summary` is absent/`None` (blind disabled).
- `append_run_to_index(result: dict, output_dir: Path) -> None`
  - Builds the row via `build_index_row` (13 ordered fields).
  - Appends to `runs_index.md` and `runs_index.csv` under `output_dir`, creating each with a header on first write and appending one data row thereafter.
  - CSV is written via Python's `csv` module (defensive quoting) so a stray comma in any value cannot break a row.
  - Markdown is appended as a single `| ... |` line; the header (column row + `|---|` separator) is written only when the file does not yet exist.

### 4.2 Modified: `main.py`
- Remove `_append_model_usage_log` and its call in `save_result`.
- Import and call `append_run_to_index(result, output_dir)` from `save_result` in its place.
- No other behavior in `save_result` (filenames, report generation, prints) changes.

---

## 5. Data flow

```
run completes
  → save_result(result, output_dir, run_index)
      → writes {stem}.json and {stem}_report.md   (unchanged)
      → append_run_to_index(result, output_dir)
            → build_index_row(result)  → 12 fields
                → append row to runs_index.md   (header if new)
                → append row to runs_index.csv  (header if new)
```

---

## 6. Error handling

- **Missing `run_metadata`** (older/degenerate results): every field falls back to `N/A` (or `run_index`-style default for the id) — the row is still written; no crash.
- **Empty-result runs** (no verified clauses): still get a row. `overall_label` falls back to `N/A` (or the result's `error`), `clauses` is `0`, anchoring is `—`. Failed runs stay visible in the history rather than silently missing.
- **Index writing must never crash a run.** A failure to write the index is non-fatal — the per-run JSON and report are the source of truth; the index is a convenience aggregate.
- **Backward compatibility:** the old `model_usage_log.md` is no longer written. Any existing `model_usage_log.md` on disk is left untouched (not deleted); it simply stops growing.

---

## 7. Testing

This repo has no pytest; tests are standalone `assert` scripts run as `python tests/<file>.py`, printing `OK` on success, using the `sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))` shim.

`tests/test_runs_index.py`:
- `build_index_row` maps a synthetic **full** result (with run_metadata, finalizer, reflector, label_panel incl. anchoring) to all 13 fields with correct values (commit shows `(dirty)` when dirty; `blind` is `on`; anchoring shows the two rates).
- `build_index_row` on a synthetic **empty-result** (no verified clauses, no label_panel) yields a valid row with safe fallbacks (`clauses == 0`, anchoring `—`, no exception).
- `append_run_to_index` on a fresh temp dir creates both `runs_index.md` and `runs_index.csv`, each with exactly one header and one data row; a second call appends a second data row **without** a second header (so 2 data rows, 1 header in each file).

---

## 8. Out of scope (keeping this a little step)

- No per-clause export (one row per clause) — separate future feature.
- No cross-run diff/comparison report.
- No batch `--all` runner.
- No true `.xlsx` workbook (CSV opens in Excel and needs no dependency).
- No deletion or migration of the existing `model_usage_log.md`.
- No pipeline-logic, prompt, or agent changes.
