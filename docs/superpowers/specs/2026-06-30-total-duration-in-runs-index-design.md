# Total Run Duration in the Runs Index — Design Spec

**Date:** 2026-06-30
**Status:** Awaiting user review
**Scope:** Add one column to the cumulative runs index (`runs_index.md` / `runs_index.csv`) showing each run's total wall-clock duration, summed from the `run_trace` execution-timeline events the pipeline already records. Single-file change to `utils/runs_index.py` plus its test.

---

## 1. Goal

The runs index (`utils/runs_index.py`) records one row per pipeline run — run id, policy, label, confidence, retries, agreement, etc. — as a cumulative `runs_index.md` / `runs_index.csv` table, newest on top. It does **not** currently show how long each run took.

The recently-shipped execution timeline (`run_trace`, a list of per-stage events each carrying `duration_s`) makes total wall-clock time trivially available on the result dict. This feature surfaces that single number as a new index column, so the cumulative table answers "how long did each run take" at a glance — useful for spotting slow runs and comparing runs over time, alongside the existing retry/agreement columns.

## 2. Background — what already exists (and is reused)

- **`utils/runs_index.py`** builds one row per run from the result dict. Three structures share a single field order: `FIELDS` (dict keys + CSV header), `MD_HEADERS` (Markdown column titles), and `build_index_row(result)` (maps a result to those fields). Today there are **15 fields**.
- **`EM_DASH = "—"`** is the file's existing convention for a not-applicable value (e.g. blind disabled, anchoring unavailable). The new column reuses it for runs without a trace.
- **`build_index_row` is defensive throughout** — every field falls back to a safe default so a missing key (older or empty-result runs) never raises. The new field follows this style.
- **`append_run_to_index`** already performs **schema migration**: when the existing CSV header does not match `FIELDS`, it renames the old index to `<name>.bak` and starts a fresh one (no data deleted). Adding a field changes the header, so this path handles the upgrade automatically — **no new migration code**.
- **`run_trace`** (from `utils/run_trace.py`, wired in `main.py`) is a list of event dicts, each `{"step", "stage", "model", "duration_s", "status", "note"}`. It is attached to the result dict on both return paths (normal and `_empty_result`).
- **Wiring is already in place:** `main.py` calls `append_run_to_index(result, output_dir)` with the full `result` dict (which includes `run_trace`). **No change to `main.py`.**
- **Tests** are standalone assert scripts (`tests/test_*.py`, run as `python tests/<file>.py`, print `OK`, exit non-zero on failure). `tests/test_runs_index.py` already asserts `list(row.keys()) == FIELDS`, so it tracks the new field's presence automatically; only value-specific assertions need updating.

## 3. Feature design

### 3.1 Files

| File | Action | Responsibility |
|---|---|---|
| `utils/runs_index.py` | Modify | Add `duration_s` to `FIELDS` and `MD_HEADERS`; compute the summed duration in `build_index_row`. |
| `tests/test_runs_index.py` | Modify | Add assertions for the new column (summed value with a trace; `—` without); update value-specific assertions for the new field. |

No change to `main.py`, the report generator, the per-run JSON, `run_trace` itself, `runs_summary.py`, or any other column.

### 3.2 The column

- **CSV key / `FIELDS` entry:** `"duration_s"`, appended as the **last** field (16th), after `"anchoring_b"`.
- **Markdown header / `MD_HEADERS` entry:** `"Duration (s)"`, appended last (after `"Anchoring B"`).
- **Value (in `build_index_row`):**
  - Read `result.get("run_trace")`.
  - If it is a non-empty list, the value is `round(sum(e.get("duration_s") or 0 for e in run_trace), 1)` — the total wall-clock seconds across all recorded stages, rounded to **1 decimal place**.
  - If `run_trace` is absent, `None`, or empty, the value is `EM_DASH` — consistent with the file's not-applicable convention. (Older runs and empty-result runs without a trace render `—` rather than a misleading `0.0`.)
- **Defensive:** each event's `duration_s` is coalesced with `or 0` so a malformed event cannot raise; the whole computation sits inside the existing defensive `build_index_row` body.

### 3.3 Placement rationale

- **Last column:** appending at the end leaves the reading order of all 15 existing columns untouched — no consumer of the current table layout is disrupted.
- **1 decimal place:** the index is a scannable at-a-glance overview; `31.7` answers the question without noise. Full 3-dp precision remains available in the per-run JSON's `run_trace` and in the report's Execution Timeline section.
- **`—` for missing:** matches the existing `EM_DASH` convention and avoids implying a real zero-duration run.

### 3.4 Migration

No bespoke migration. The first run after this change writes a 16-field header; `append_run_to_index` detects that the existing 15-field CSV header no longer matches `FIELDS`, backs the old `runs_index.csv`/`runs_index.md` up to `.bak`, and starts a fresh index. Old rows are preserved in the `.bak` files. This is the file's existing, tested behavior (`test_schema_mismatch_backs_up`).

## 4. What it deliberately does NOT do

- No change to the per-run JSON, the human `report.md`, or `run_trace`'s shape.
- No per-stage breakdown in the index (that detail lives in the report's Execution Timeline) — only the single total.
- No change to `runs_summary.py`, `batch_comparison.py`, `run_diff.py`, or any other column.
- No new CLI flag and no change to `main.py` (wiring already passes the full result).

## 5. Testing / verification

Offline, no API key — consistent with the existing suite and CI.

`tests/test_runs_index.py` (standalone assert script):
1. **With a trace:** a result whose `run_trace` has events with known durations produces a row whose `duration_s` field equals the 1-dp sum (e.g. events summing to `31.7` → `31.7`). Assert via `build_index_row`.
2. **Without a trace:** a result with no `run_trace` key produces `EM_DASH` in the `duration_s` field.
3. **Field order intact:** `list(build_index_row(result).keys()) == FIELDS` still holds with the new field present (existing assertion — confirm it still passes with 16 fields).
4. **Header/column counts:** `MD_HEADERS` length equals `FIELDS` length; the written Markdown index has one column per field (covered by existing index-writing tests; update any hard-coded column counts if present).

Each script prints `OK` on success via its `__main__` block; failure raises and exits non-zero. No test invokes `main.py`'s real pipeline or any LLM.

## 6. Out of scope

- Per-stage timing columns in the index.
- Surfacing duration in `runs_summary.md` or the batch comparison.
- Any change to how durations are measured (that is `run_trace`'s job, already shipped).
- Sorting or filtering the index by duration.
