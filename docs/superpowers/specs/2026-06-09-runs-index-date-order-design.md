# Runs Index — Date Column & Newest-First Order — Design Spec

**Date:** 2026-06-09
**Status:** Approved for planning
**Scope:** Small quality-of-life update to the existing runs index. No pipeline-logic changes.

---

## 1. Goal

Make the cumulative runs index easier to read at a glance by:

1. **Adding a human-readable `date` column** next to the cryptic `run_id`.
2. **Ordering rows newest-first** — the most recently written run appears at the top, instead of being appended at the bottom.

Both `runs_index.md` and `runs_index.csv` get these changes. This builds directly on the runs-index feature (`utils/runs_index.py`) shipped on 2026-06-08.

This is post-processing only: it reads the result dict the pipeline already produces. No LLM calls; no changes to agents, prompts, the retry loop, or run filenames. `main.py` is unchanged — `save_result` still calls `append_run_to_index(result, output_dir)`.

---

## 2. Background — current behavior

`utils/runs_index.py` currently:
- `FIELDS` has **13 columns**, starting with `run_id`; no human-readable date.
- `append_run_to_index` **appends** one row to the bottom of each file (oldest-first), writing the header only when the file does not yet exist.

Limitations this update addresses:
- `run_id` (`20260608T090030Z`) is precise but hard to read; there is no friendly timestamp even though `run_metadata.utc_timestamp` is already captured.
- Newest runs are buried at the bottom of a growing file.

---

## 3. Changes

### 3.1 New `date` column (13 → 14 fields)

A new field `date` is inserted as **column 2**, immediately after `run_id`.

- **`FIELDS`** (new, 14 entries, in order):
  `run_id`, `date`, `policy`, `policy_sha256`, `commit`, `overall_label`, `confidence`, `clauses`, `agreement_rate`, `retries`, `disputed`, `blind`, `anchoring_a`, `anchoring_b`
- **`MD_HEADERS`** (matching order): `Run ID`, `Date (UTC)`, `Policy`, `Policy hash`, `Commit`, `Overall label`, `Confidence`, `Clauses`, `Agreement`, `Retries`, `Disputed`, `Blind`, `Anchoring A`, `Anchoring B`

**Value source & format:** derived from `result["run_metadata"]["utc_timestamp"]`, which the pipeline stores as `YYYY-MM-DDTHH:MM:SSZ` (e.g. `2026-06-08T09:00:30Z`). Rendered to **minute precision** as `YYYY-MM-DD HH:MM UTC` (e.g. `2026-06-08 09:00 UTC`). Seconds are dropped (they remain in the `run_id`).

**Derivation (defensive, no datetime parsing required):** a helper `_human_date(run_metadata) -> str`:
- read `ts = run_metadata.get("utc_timestamp")`;
- if `ts` is missing or not a string → return `"N/A"`;
- if `"T"` in `ts`: split on the first `T` into `date_part` and `time_part`; take the first 5 chars of `time_part` (`HH:MM`); return `f"{date_part} {time_part[:5]} UTC"`;
- otherwise (unexpected format) → return `"N/A"`.

`build_index_row` gains the `date` key (placed second) using `_human_date(rm)`. All other fields are unchanged.

### 3.2 Newest-first ordering (append → rewrite)

A file cannot be prepended to without rewriting it, so `append_run_to_index` changes from "append one line" to "rewrite the whole file":

1. Build the new row via `build_index_row` and turn it into `values` (14 entries, in `FIELDS` order).
2. Read existing data rows from **`runs_index.csv`** (the CSV is the single source of truth for prior rows — see §3.3 for the schema-mismatch case).
3. Write `runs_index.csv` fresh: header row (`FIELDS`) + **new row on top** + existing rows below.
4. Write `runs_index.md` fresh from the **same** row set: the `# Runs Index` header block + Markdown column header + new row on top + existing rows below.

"Newest-first" means **most-recently-written run on top** (insertion order, prepended), not a sort on the `date` value. In normal use (runs added chronologically) this is identical to newest-by-date, and it keeps the logic to a simple prepend.

The files hold one row per run (tiny), so rewriting the whole file each run is negligible.

### 3.3 Backward-compatibility — back up old file, start fresh (Choice 1)

An existing on-disk `runs_index.csv` may use the **old 13-column schema** (no `date`). Mixing old and new rows would produce ragged, mis-aligned columns.

Behavior when writing:
- If `runs_index.csv` exists and its header row **equals the new `FIELDS`** → it is current; take its data rows (everything after the header) as the existing rows.
- If it exists but the header **does not equal `FIELDS`** (old schema, or no/garbled header) → **rename `runs_index.csv` to `runs_index.csv.bak` and `runs_index.md` to `runs_index.md.bak`** (whichever exist), then start fresh with **no** existing rows. The new files contain only the header + the new run's row.
- If neither file exists → create fresh (as today).

No data is deleted — old rows are preserved in the `.bak` files. If a `.bak` already exists from a prior schema change, it is overwritten (acceptable: these are gitignored local convenience aggregates, and the per-run JSON/report remain the authoritative record).

---

## 4. Components and responsibilities

All changes are confined to **`utils/runs_index.py`** (+ its test). New/changed pieces:

- `FIELDS` / `MD_HEADERS` — extended to 14 entries (§3.1).
- `_human_date(run_metadata: dict) -> str` — new helper (§3.1).
- `build_index_row(result)` — adds the `date` key in second position; all other keys unchanged.
- `_backup(path: Path) -> None` — new helper: if `path` exists, rename it to `path` + `.bak` (replacing any existing `.bak`).
- `_write_csv(path, rows)` / `_write_md(path, rows)` — rewrite helpers that write the full file (header + all `rows`) from scratch. `rows` is the ordered list of value-lists, newest first. (These replace the old append-only `_append_csv` / `_append_md`.)
- `append_run_to_index(result, output_dir)` — orchestrates: build row → read/validate existing CSV rows (backup on mismatch) → rewrite both files newest-first. Still wrapped in `try/except` so a failure to write the index **never crashes a run** (prints a warning).

---

## 5. Data flow

```
run completes
  → save_result(result, output_dir, run_index)            (unchanged in main.py)
      → append_run_to_index(result, output_dir)
            → build_index_row(result)            → 14 fields (incl. date)
            → read runs_index.csv rows
                 · header == FIELDS  → reuse existing rows
                 · header != FIELDS  → back up .csv/.md → start fresh
            → write runs_index.csv:  header + NEW row + existing rows
            → write runs_index.md:   block + header + NEW row + existing rows
```

---

## 6. Error handling

- **Missing `utc_timestamp`** → `date` is `"N/A"` (row still written).
- **Index write failure** → swallowed with a printed warning; the run's JSON and report remain the source of truth (unchanged guarantee).
- **Old-schema or unreadable existing file** → backed up to `.bak`, fresh index started (§3.3).

---

## 7. Testing

Standalone assert script `tests/test_runs_index.py` (run as `python tests/test_runs_index.py`, prints `OK`). Updates:

- **Fixtures:** `_full_result()` gains `run_metadata["utc_timestamp"] = "2026-06-07T14:30:22Z"`; `_empty_result()` deliberately omits `utc_timestamp` (to exercise the `N/A` fallback).
- **`test_build_index_row_full`:** `FIELDS` has 14 entries in the documented order; `row["date"] == "2026-06-07 14:30 UTC"`; all previously-asserted fields still pass.
- **`test_build_index_row_empty_result`:** `row["date"] == "N/A"`.
- **`test_append_creates_then_appends` (renamed/clarified as newest-first):** append `_empty_result` then `_full_result`; assert one header, header `== FIELDS`, and that the **last-appended** run is on top: `rows[1][0] == "20260607T143022Z"` (full, newest), `rows[2][0] == "20260101T000000Z"` (empty, older). Markdown header `| Run ID |` appears exactly once; both run_ids present.
- **New `test_schema_mismatch_backs_up`:** pre-create `runs_index.csv` with an old-style header (not equal to `FIELDS`) plus one data row; call `append_run_to_index`; assert `runs_index.csv.bak` now exists, the new `runs_index.csv` header `== FIELDS`, and it contains exactly the header + the one new row (old row not carried forward into the live file).

---

## 8. Out of scope

- No sorting by the `date` value (insertion-order prepend only).
- No migration of old rows into the new schema (Choice 2 was declined).
- No new CLI flags; `main.py` unchanged.
- No per-clause export, cross-run diff, or `.xlsx` (still out of scope from the original runs-index spec).
- No pipeline-logic, prompt, or agent changes.
