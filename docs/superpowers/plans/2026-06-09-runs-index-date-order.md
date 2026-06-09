# Runs Index — Date Column & Newest-First Order Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a human-readable `date` column to the runs index and write rows newest-first, backing up any old-schema index file to `.bak` and starting fresh.

**Architecture:** Two changes confined to `utils/runs_index.py` (+ its standalone test). Task 1 adds the `date` field (schema grows 13 → 14) and a `_human_date` helper, leaving the existing append-at-bottom writer in place. Task 2 swaps the append-only writer for a full-rewrite writer that prepends the new row (newest-first) and backs up an old-schema file before starting fresh. `main.py` is unchanged — it still calls `append_run_to_index(result, output_dir)`.

**Tech Stack:** Python 3.12, stdlib only (`csv`, `pathlib`). No test framework — tests are standalone `assert` scripts run with `python tests/<file>.py` that print `OK` on success. Windows + PowerShell (chain commands with `;`, not `&&`). Git LF→CRLF warnings are cosmetic.

**Spec:** `docs/superpowers/specs/2026-06-09-runs-index-date-order-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `utils/runs_index.py` | Modify | Add `date` field + `_human_date`; replace append writer with newest-first rewrite + `.bak` backup |
| `tests/test_runs_index.py` | Modify | Update fixtures/assertions for the 14-field schema, newest-first order, and schema-mismatch backup |

---

## Task 1: Add the `date` column (schema 13 → 14)

**Files:**
- Modify: `utils/runs_index.py`
- Modify: `tests/test_runs_index.py`

In this task the writer is **not** changed yet — it still appends at the bottom. After Task 1 all tests are green with the new 14-field schema; the newest-first behavior arrives in Task 2.

- [ ] **Step 1: Update the test fixture and builder tests (write the failing tests first)**

In `tests/test_runs_index.py`, add a `utc_timestamp` to `_full_result()`'s `run_metadata`. Find this block:

```python
        "run_metadata": {
            "run_id": "20260607T143022Z",
            "policy_file": "policy_short.txt",
            "policy_sha256": "a1b2c3d4",
            "git_commit": {"sha": "cac701e", "dirty": True},
            "clause_count": 68,
            "blind_enabled": True,
        },
```

and replace it with (adds the `utc_timestamp` line):

```python
        "run_metadata": {
            "run_id": "20260607T143022Z",
            "utc_timestamp": "2026-06-07T14:30:22Z",
            "policy_file": "policy_short.txt",
            "policy_sha256": "a1b2c3d4",
            "git_commit": {"sha": "cac701e", "dirty": True},
            "clause_count": 68,
            "blind_enabled": True,
        },
```

Leave `_empty_result()` as-is — it deliberately has no `utc_timestamp` so we can test the `N/A` fallback.

Then add one assertion to `test_build_index_row_full` (right after the `assert row["run_id"] == "20260607T143022Z"` line):

```python
    assert row["date"] == "2026-06-07 14:30 UTC"
```

And add one assertion to `test_build_index_row_empty_result` (right after the `assert row["run_id"] == "20260101T000000Z"` line):

```python
    assert row["date"] == "N/A"
```

- [ ] **Step 2: Run the tests to confirm they FAIL**

Run: `python tests/test_runs_index.py`
Expected: FAIL — `AssertionError` on `list(row.keys()) == FIELDS` (the builder has no `date` key yet, so the key list won't match once `FIELDS` is updated) or a `KeyError`/assertion on `row["date"]`.

- [ ] **Step 3: Add `date` to `FIELDS` and `MD_HEADERS`**

In `utils/runs_index.py`, replace the entire `FIELDS = [...]` list with (inserts `"date"` second):

```python
FIELDS = [
    "run_id",
    "date",
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
```

Replace the entire `MD_HEADERS = [...]` list with (inserts `"Date (UTC)"` second):

```python
MD_HEADERS = [
    "Run ID",
    "Date (UTC)",
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
```

- [ ] **Step 4: Add the `_human_date` helper**

In `utils/runs_index.py`, add this function immediately **above** `def _anchoring(`:

```python
def _human_date(run_metadata: dict) -> str:
    """Render run_metadata['utc_timestamp'] (YYYY-MM-DDTHH:MM:SSZ) as
    'YYYY-MM-DD HH:MM UTC' (minute precision). Returns 'N/A' if absent/malformed."""
    ts = run_metadata.get("utc_timestamp")
    if not isinstance(ts, str) or "T" not in ts:
        return "N/A"
    date_part, _, time_part = ts.partition("T")
    return f"{date_part} {time_part[:5]} UTC"
```

- [ ] **Step 5: Add the `date` key to `build_index_row`**

In `utils/runs_index.py`, inside the dict returned by `build_index_row`, insert the `date` entry immediately after the `run_id` entry. Find:

```python
    return {
        "run_id": rm.get("run_id", "N/A"),
        "policy": rm.get("policy_file") or result.get("policy_name", "N/A"),
```

and replace with:

```python
    return {
        "run_id": rm.get("run_id", "N/A"),
        "date": _human_date(rm),
        "policy": rm.get("policy_file") or result.get("policy_name", "N/A"),
```

- [ ] **Step 6: Run the full test file to confirm all PASS**

Run: `python tests/test_runs_index.py`
Expected output: `OK`

(`test_append_creates_then_appends` still passes here: the writer still appends at the bottom, and the 14-column header now equals the updated `FIELDS`.)

- [ ] **Step 7: Commit**

```bash
git add utils/runs_index.py tests/test_runs_index.py
git commit -m "feat: add human-readable date column to runs index"
```

---

## Task 2: Newest-first ordering + backup-on-schema-mismatch

**Files:**
- Modify: `utils/runs_index.py`
- Modify: `tests/test_runs_index.py`

This task replaces the append-only writer (`_append_md`, `_append_csv`) with a full-rewrite writer that prepends the new row, and backs up an old-schema file before starting fresh.

- [ ] **Step 1: Update the ordering test and add the schema-mismatch test (write the failing tests first)**

In `tests/test_runs_index.py`, replace the whole `test_append_creates_then_appends` function with the two functions below (the first is the renamed/flipped ordering test; the second is new):

```python
def test_append_newest_first():
    d = Path(tempfile.mkdtemp())
    try:
        append_run_to_index(_empty_result(), d)   # run_id ...0000Z (appended first)
        append_run_to_index(_full_result(), d)     # run_id ...3022Z (appended last)

        csv_path = d / "runs_index.csv"
        md_path = d / "runs_index.md"
        assert csv_path.exists() and md_path.exists()

        with csv_path.open(encoding="utf-8") as f:
            rows = list(_csv.reader(f))
        assert rows[0] == FIELDS                    # one header
        assert len(rows) == 3                        # header + 2 data rows
        assert rows[1][0] == "20260607T143022Z"     # newest (last appended) on top
        assert rows[2][0] == "20260101T000000Z"     # older below

        md = md_path.read_text(encoding="utf-8")
        assert md.count("| Run ID |") == 1          # header table row appears once
        assert "20260101T000000Z" in md and "20260607T143022Z" in md
    finally:
        shutil.rmtree(d)


def test_schema_mismatch_backs_up():
    d = Path(tempfile.mkdtemp())
    try:
        csv_path = d / "runs_index.csv"
        md_path = d / "runs_index.md"
        # Pre-create an OLD-schema index whose header != current FIELDS.
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(["run_id", "policy", "overall_label"])      # old 3-col header
            w.writerow(["20250101T000000Z", "old.txt", "Compliant"])
        md_path.write_text("# Old index\n", encoding="utf-8")

        append_run_to_index(_full_result(), d)

        # Old files were backed up, not lost.
        assert (d / "runs_index.csv.bak").exists()
        assert (d / "runs_index.md.bak").exists()

        # New CSV uses the current schema and contains only the new run.
        with csv_path.open(encoding="utf-8") as f:
            rows = list(_csv.reader(f))
        assert rows[0] == FIELDS
        assert len(rows) == 2                         # header + 1 new row
        assert rows[1][0] == "20260607T143022Z"
        assert "20250101T000000Z" not in [r[0] for r in rows[1:]]  # old row not carried over
    finally:
        shutil.rmtree(d)
```

Then update the `__main__` block at the bottom of the file. Replace:

```python
if __name__ == "__main__":
    test_build_index_row_full()
    test_build_index_row_empty_result()
    test_append_creates_then_appends()
    print("OK")
```

with:

```python
if __name__ == "__main__":
    test_build_index_row_full()
    test_build_index_row_empty_result()
    test_append_newest_first()
    test_schema_mismatch_backs_up()
    print("OK")
```

- [ ] **Step 2: Run the tests to confirm they FAIL**

Run: `python tests/test_runs_index.py`
Expected: FAIL — `test_append_newest_first` fails on `rows[1][0] == "20260607T143022Z"` (current writer appends oldest-first, so `rows[1]` is still `...0000Z`).

- [ ] **Step 3: Replace the append writer with rewrite + backup helpers**

In `utils/runs_index.py`, **delete** the two existing append helpers `_append_md` and `_append_csv` entirely, and **replace** the existing `append_run_to_index` function. After this step the bottom of the file (everything from `def _append_md` onward) should read EXACTLY:

```python
def _backup(path: Path) -> None:
    """If path exists, rename it to '<name>.bak', replacing any existing backup."""
    if path.exists():
        bak = path.with_name(path.name + ".bak")
        if bak.exists():
            bak.unlink()
        path.rename(bak)


def _write_csv(path: Path, rows: list) -> None:
    """Write the CSV fresh: FIELDS header followed by every row (newest first)."""
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(FIELDS)
        writer.writerows(rows)


def _write_md(path: Path, rows: list) -> None:
    """Write the Markdown index fresh: header block + column header + every row."""
    with path.open("w", encoding="utf-8") as f:
        f.write("# Runs Index\n\n")
        f.write("One row per pipeline run. Newest at the top.\n\n")
        f.write("| " + " | ".join(MD_HEADERS) + " |\n")
        f.write("|" + "|".join(["---"] * len(MD_HEADERS)) + "|\n")
        for values in rows:
            f.write("| " + " | ".join(str(v) for v in values) + " |\n")


def append_run_to_index(result: dict, output_dir: Path) -> None:
    """
    Prepend this run's summary row to runs_index.md and runs_index.csv under
    output_dir, so the most recently written run appears on top. Creates the
    files on first write.

    If an existing index uses an older column schema (its CSV header does not
    match FIELDS), it is renamed to '<name>.bak' and a fresh index is started —
    no data is deleted, the old rows are preserved in the .bak file.

    Never raises: a failure to write the index must not crash a pipeline run —
    the per-run JSON and report remain the source of truth.
    """
    try:
        row = build_index_row(result)
        values = [row[field] for field in FIELDS]
        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = output_dir / "runs_index.csv"
        md_path = output_dir / "runs_index.md"

        existing = []
        if csv_path.exists():
            with csv_path.open(encoding="utf-8", newline="") as f:
                rows = list(csv.reader(f))
            if rows and rows[0] == FIELDS:
                existing = rows[1:]          # current schema — keep prior rows
            else:
                _backup(csv_path)            # old/unknown schema — start fresh
                _backup(md_path)
                existing = []

        all_rows = [values] + existing       # newest row on top
        _write_csv(csv_path, all_rows)
        _write_md(md_path, all_rows)
        print(f"Runs index updated: {csv_path}")
    except Exception as exc:  # index is a convenience aggregate; never fatal
        print(f"  [runs_index] WARNING: could not update index: {exc}")
```

- [ ] **Step 4: Run the full test file to confirm all PASS**

Run: `python tests/test_runs_index.py`
Expected output: `OK`

- [ ] **Step 5: Confirm the module imports cleanly and no stale helper remains**

Run: `python -c "import utils.runs_index; print('OK')"`
Expected output: `OK`

Run: `grep -c "_append_md\|_append_csv" utils/runs_index.py`
Expected output: `0`

- [ ] **Step 6: Commit**

```bash
git add utils/runs_index.py tests/test_runs_index.py
git commit -m "feat: write runs index newest-first; back up old-schema index"
```

---

## Task 3: End-to-end (offline) verification

**Files:** none (verification only)

Drives the real `save_result` (via `main.py`) with two synthetic results to confirm the new behavior end-to-end without any API cost, then confirms the old-schema backup path.

- [ ] **Step 1: Drive `save_result` twice and assert newest-first + date column**

Run (single line):

```bash
python -c "import os, csv; from pathlib import Path; import main; d=Path('output/_idxcheck2'); os.makedirs(d, exist_ok=True); base={'agent_models':{},'extractor_output':{},'verified_clauses':[1,2,3],'flagged_clauses':[],'evaluator_output':{},'final_reflector_output':{'agreement_rate':0.9},'finalizer_output':{'overall_label':'Compliant','confidence':'high'},'label_panel':{'disputed_count':2,'anchoring_summary':{'reflector_a':{'shift_rate':0.1},'reflector_b':{'shift_rate':0.2}}},'retry_count':0,'policy_name':'demo'}; ts={'20260609T090000Z':'2026-06-09T09:00:00Z','20260609T093000Z':'2026-06-09T09:30:00Z'}; [main.save_result({**base,'run_metadata':{'run_id':rid,'utc_timestamp':ts[rid],'policy_file':'policy_short.txt','policy_sha256':'cafef00d','git_commit':{'sha':'bae249d','dirty':False},'clause_count':3,'blind_enabled':True}}, d, run_index=1) for rid in ('20260609T090000Z','20260609T093000Z')]; rows=list(csv.reader(open(d/'runs_index.csv',encoding='utf-8'))); print('rows:',len(rows)); print('header[1]:',rows[0][1]); print('top run:',rows[1][0],'date:',rows[1][1]); assert len(rows)==3; assert rows[0][1]=='date'; assert rows[1][0]=='20260609T093000Z'; assert rows[1][1]=='2026-06-09 09:30 UTC'; assert rows[2][0]=='20260609T090000Z'; print('PASS: newest-first with readable date')"
```

Expected: `rows: 3`, `header[1]: date`, top run is `20260609T093000Z` with date `2026-06-09 09:30 UTC`, and `PASS: newest-first with readable date`.

- [ ] **Step 2: Confirm old-schema files are backed up, not corrupted**

Run (single line):

```bash
python -c "import os, csv; from pathlib import Path; import main; d=Path('output/_idxcheck3'); os.makedirs(d, exist_ok=True); cp=d/'runs_index.csv'; w=csv.writer(open(cp,'w',newline='',encoding='utf-8')); w.writerow(['run_id','policy','overall_label']); w.writerow(['20250101T000000Z','old.txt','Compliant']); open(d/'runs_index.md','w',encoding='utf-8').write('# Old index\n'); base={'agent_models':{},'extractor_output':{},'verified_clauses':[1],'flagged_clauses':[],'evaluator_output':{},'final_reflector_output':{'agreement_rate':0.9},'finalizer_output':{'overall_label':'Compliant','confidence':'high'},'label_panel':{'disputed_count':0,'anchoring_summary':None},'retry_count':0,'policy_name':'demo','run_metadata':{'run_id':'20260609T100000Z','utc_timestamp':'2026-06-09T10:00:00Z','policy_file':'p.txt','policy_sha256':'abcd1234','git_commit':{'sha':'bae249d','dirty':False},'clause_count':1,'blind_enabled':False}}; main.save_result(base, d, run_index=1); assert (d/'runs_index.csv.bak').exists(); assert (d/'runs_index.md.bak').exists(); rows=list(csv.reader(open(cp,encoding='utf-8'))); assert rows[0][1]=='date' and len(rows)==2 and rows[1][0]=='20260609T100000Z'; print('PASS: old-schema index backed up, fresh index started')"
```

Expected: `PASS: old-schema index backed up, fresh index started`.

- [ ] **Step 3: Clean up the throwaway dirs (output/ is gitignored)**

```bash
python -c "import shutil; [shutil.rmtree(p, ignore_errors=True) for p in ('output/_idxcheck2','output/_idxcheck3')]; print('cleaned')"
```

- [ ] **Step 4: Final commit (marker, allow empty)**

```bash
git add -A
git commit -m "test: verify runs index date column + newest-first end-to-end (offline)" --allow-empty
```

> `output/` is gitignored, so `git add -A` should stage nothing from it. If it would stage any unexpected non-output file (e.g. `.claude/settings.local.json`), do NOT commit that file — unstage it with `git restore --staged <file>` first, then commit empty.

---

## Notes for the implementer

- **No pytest in this repo.** Run test files directly with `python tests/<file>.py`; they print `OK` on success.
- **The index must never crash a run.** `append_run_to_index` swallows all exceptions and prints a warning. Do not remove that guard.
- **Do not touch pipeline logic, prompts, agents, the retry loop, run filenames, or `main.py`.** This feature is post-processing only.
- **`FIELDS` is the single source of column order** — `build_index_row` keys, the CSV header, and (positionally) `MD_HEADERS` all follow it. Keep them aligned (all now 14 entries).
- **"Newest-first" means insertion order** (the last run written goes on top), not a sort on the `date` value.
- **Old `.bak` files** are overwritten on a repeat schema change; that is intentional and acceptable for these gitignored local aggregates.
