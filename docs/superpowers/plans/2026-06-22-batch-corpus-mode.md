# Batch (Corpus) Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--policy-dir <folder>` batch mode that runs every supported policy in a folder and writes one batch-scoped side-by-side comparison file, leaving the existing single-policy `--policy` run unchanged.

**Architecture:** Two new pure, offline-testable units — `discover_policy_files()` (folder → sorted list of supported files) and a `batch_comparison` renderer (list of per-run entries → Markdown table + CSV rows, every metric cell taken from the existing `build_index_row()`). Then `main.py` gains a mutually-exclusive `--policy` / `--policy-dir` group and a loop that runs each policy through the *unchanged* `run_pipeline` + `save_result` path, collects an entry per run, and writes the comparison file at the end.

**Tech Stack:** Python 3.12, standard library only for the new code (`pathlib`, `csv`); reuses `utils.policy_loader.SUPPORTED_EXTENSIONS`, `utils.runs_index.build_index_row`. Tests are standalone assert scripts. Dev machine is Windows + PowerShell (chain with `;`, never `&&`).

## Global Constraints

- **Offline only.** The new logic (discovery, comparison rendering) makes no LLM/network call and needs no API key. Do NOT run `main.py`'s real pipeline in any automated test.
- Tests are **standalone assert scripts** (NOT pytest): each `tests/test_*.py` adds the repo root to `sys.path`, defines `test_*()` functions, and a `__main__` block that calls them and prints `OK`; any failure raises and exits non-zero.
- **Single-policy mode must not change behavior.** `--policy <file>` keeps its current outputs, error messages, and exit codes.
- The comparison table introduces **no new result-extraction logic** — every metric cell comes from `build_index_row(result)`.
- **No recursion** into subfolders; **no parallelism**; **no batch-scoped aggregate stats** (out of scope per the spec).
- `docs/` is gitignored (not touched by these tasks). `utils/`, `tests/`, `main.py` are NOT gitignored and stage normally.
- Do NOT commit `.claude/settings.local.json` (intentionally modified, must stay unstaged). Only `git add` the exact files named in each commit step.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `utils/policy_loader.py` | Modify | Add `discover_policy_files(directory)` |
| `tests/test_policy_discovery.py` | Create | Tests for `discover_policy_files` |
| `utils/batch_comparison.py` | Create | `build_comparison_csv_rows` + `build_comparison_md` (pure renderers) |
| `tests/test_batch_comparison.py` | Create | Tests for the comparison renderers |
| `main.py` | Modify | `--policy`/`--policy-dir` mutually-exclusive group; batch loop; write comparison files |

Repo facts for the implementer (verified):
- `utils/policy_loader.py` defines `SUPPORTED_EXTENSIONS = {".txt", ".md", ".html", ".htm", ".pdf", ".docx"}` and `load_policy_text(path)`.
- `utils/runs_index.py` defines `build_index_row(result) -> dict` whose keys include `run_id`, `overall_label`, `confidence`, `clauses`, `disputed`, `retries`, `agreement_rate` (full list in `FIELDS`). For an empty result, `overall_label`/`confidence`/`agreement_rate` are the string `"N/A"`; `clauses`/`disputed`/`retries` are numbers (often `0`).
- `main.py` defines `run_pipeline(client, policy_path, agent_models, blind_enabled) -> dict`, `save_result(result, output_dir, run_index) -> Path`, and `_empty_result(...)` (a result carrying an `"error"` key and no `finalizer_output`). `main()` currently makes `--policy` `required=True`, validates the path + extension, checks `OPENROUTER_API_KEY`, builds the client, resolves `agent_models`, then loops `for run_i in range(1, args.runs + 1)`.
- The data folder `data/policies/` holds `policy_short.txt`, `policy_medium.txt`, `policy_long.txt` (three distinct policies).

---

## Task 1: Discover supported policy files in a directory

**Files:**
- Modify: `utils/policy_loader.py`
- Test: `tests/test_policy_discovery.py`

**Interfaces:**
- Consumes: `SUPPORTED_EXTENSIONS` (already in the module).
- Produces: `discover_policy_files(directory) -> list[Path]` — used by `main.py` in Task 3.

- [ ] **Step 1: Write the failing test**

Create `tests/test_policy_discovery.py`:

```python
"""Standalone assert tests for discover_policy_files."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.policy_loader import discover_policy_files


def _touch(d: Path, name: str):
    (d / name).write_text("x", encoding="utf-8")


def test_finds_supported_sorted_case_insensitive():
    d = Path(tempfile.mkdtemp())
    try:
        _touch(d, "Bravo.txt")
        _touch(d, "alpha.PDF")        # uppercase extension still supported
        _touch(d, "charlie.docx")
        _touch(d, "notes.xyz")        # unsupported -> skipped
        _touch(d, "image.png")        # unsupported -> skipped
        names = [p.name for p in discover_policy_files(d)]
        # alpha.PDF, Bravo.txt, charlie.docx — case-insensitive name sort
        assert names == ["alpha.PDF", "Bravo.txt", "charlie.docx"], names
    finally:
        shutil.rmtree(d)


def test_non_recursive_skips_subfolders():
    d = Path(tempfile.mkdtemp())
    try:
        _touch(d, "top.txt")
        sub = d / "nested"
        sub.mkdir()
        _touch(sub, "deep.txt")       # in a subfolder -> not discovered
        names = [p.name for p in discover_policy_files(d)]
        assert names == ["top.txt"], names
    finally:
        shutil.rmtree(d)


def test_empty_or_all_unsupported_returns_empty_list():
    d = Path(tempfile.mkdtemp())
    try:
        _touch(d, "readme.xyz")
        assert discover_policy_files(d) == []
    finally:
        shutil.rmtree(d)


if __name__ == "__main__":
    test_finds_supported_sorted_case_insensitive()
    test_non_recursive_skips_subfolders()
    test_empty_or_all_unsupported_returns_empty_list()
    print("OK")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_policy_discovery.py`
Expected: FAIL with `ImportError: cannot import name 'discover_policy_files'`.

- [ ] **Step 3: Implement `discover_policy_files`**

In `utils/policy_loader.py`, add this function (e.g. directly after `load_policy_text`):

```python
def discover_policy_files(directory) -> list:
    """
    Return the supported policy files directly inside `directory`
    (non-recursive), sorted by filename case-insensitively. Files whose
    extension is not in SUPPORTED_EXTENSIONS are skipped. Returns [] when none
    match; does not raise for an empty result — the caller decides what to do.

    Raises (via Path.iterdir) if `directory` does not exist; callers validate
    the directory exists before calling.
    """
    d = Path(directory)
    files = [
        p for p in d.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    return sorted(files, key=lambda p: p.name.lower())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python tests/test_policy_discovery.py`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add utils/policy_loader.py tests/test_policy_discovery.py
git commit -m "feat: discover supported policy files in a directory"
```

Then run `git status --short` and confirm the only listed file is ` M .claude/settings.local.json`.

---

## Task 2: Render the batch comparison table

**Files:**
- Create: `utils/batch_comparison.py`
- Test: `tests/test_batch_comparison.py`

**Interfaces:**
- Consumes: per-run **entry** dicts shaped as
  `{"policy": str, "run_index": int, "status": "ok"|"empty"|"failed", "row": dict|None, "error": str|None}`,
  where `row` (when present) is the output of `utils.runs_index.build_index_row`.
- Produces:
  - `build_comparison_csv_rows(entries) -> list[list[str]]` — header row + one row per entry.
  - `build_comparison_md(entries, batch_label: str) -> str` — a Markdown document with a title referencing `batch_label` and the comparison table.
  - module constant `HEADERS: list[str]`.
  These are consumed by `main.py` in Task 3.

- [ ] **Step 1: Write the failing test**

Create `tests/test_batch_comparison.py`:

```python
"""Standalone assert tests for the batch comparison renderers."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.batch_comparison import (
    build_comparison_csv_rows,
    build_comparison_md,
    HEADERS,
)


def _ok_entry():
    return {
        "policy": "policy_short",
        "run_index": 1,
        "status": "ok",
        "row": {
            "run_id": "20260622T101500Z",
            "overall_label": "Compliant",
            "confidence": "high",
            "clauses": 6,
            "disputed": 1,
            "retries": 0,
            "agreement_rate": 0.9,
        },
        "error": None,
    }


def _empty_entry():
    # build_index_row on an empty result: labels are "N/A", counts are numbers.
    return {
        "policy": "policy_blank",
        "run_index": 1,
        "status": "empty",
        "row": {
            "run_id": "20260622T101600Z",
            "overall_label": "N/A",
            "confidence": "N/A",
            "clauses": 0,
            "disputed": 0,
            "retries": 0,
            "agreement_rate": "N/A",
        },
        "error": "No verified clauses.",
    }


def _failed_entry():
    return {
        "policy": "policy_broken",
        "run_index": 1,
        "status": "failed",
        "row": None,
        "error": "could not read PDF",
    }


def test_csv_rows_header_and_count():
    entries = [_ok_entry(), _empty_entry(), _failed_entry()]
    rows = build_comparison_csv_rows(entries)
    assert rows[0] == HEADERS, rows[0]
    assert len(rows) == 1 + 3            # header + one row per entry
    # ok row: policy, run, status, then metrics
    assert rows[1][:3] == ["policy_short", "1", "ok"], rows[1]
    assert "Compliant" in rows[1]
    assert "0.9" in rows[1]


def test_missing_metrics_render_em_dash():
    rows = build_comparison_csv_rows([_empty_entry(), _failed_entry()])
    empty_row, failed_row = rows[1], rows[2]
    # "N/A" label/confidence/agreement become em dash; numeric 0 stays "0".
    assert "—" in empty_row                       # from N/A cells
    assert "0" in empty_row                        # clauses/disputed/retries = 0
    assert empty_row[3] == "—"                     # overall_label column
    # failed entry has no row -> all metric cells are em dash
    assert failed_row[:3] == ["policy_broken", "1", "failed"], failed_row
    assert failed_row[3:] == ["—"] * (len(HEADERS) - 3), failed_row


def test_md_has_title_label_and_one_row_per_entry():
    entries = [_ok_entry(), _empty_entry(), _failed_entry()]
    md = build_comparison_md(entries, batch_label="20260622T101500Z")
    assert "20260622T101500Z" in md                # batch label in the title
    assert "| " + " | ".join(HEADERS) + " |" in md  # header row present
    # one data row per entry (count the policy names)
    assert md.count("policy_short") == 1
    assert md.count("policy_blank") == 1
    assert md.count("policy_broken") == 1


if __name__ == "__main__":
    test_csv_rows_header_and_count()
    test_missing_metrics_render_em_dash()
    test_md_has_title_label_and_one_row_per_entry()
    print("OK")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_batch_comparison.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'utils.batch_comparison'`.

- [ ] **Step 3: Implement the renderers**

Create `utils/batch_comparison.py`:

```python
"""
Batch comparison — render a side-by-side survey of one batch (corpus) run.

Pure stdlib; no LLM calls. Given a list of per-run *entries*, produce a
Markdown table and CSV rows. Every metric cell is taken from the entry's
pre-computed index row (utils.runs_index.build_index_row); this module adds no
result-extraction logic of its own.

An entry is a dict:
    {
      "policy": str,            # policy file stem
      "run_index": int,         # 1-based run number for this policy
      "status": "ok" | "empty" | "failed",
      "row": dict | None,       # build_index_row(result), or None when failed
      "error": str | None,
    }
"""

EM_DASH = "—"  # shown when a metric is unavailable (failed entry, or "N/A" cell)

# (column header, build_index_row key) for the metric columns.
_METRIC_COLUMNS = [
    ("Overall label", "overall_label"),
    ("Confidence", "confidence"),
    ("Clauses", "clauses"),
    ("Disputed", "disputed"),
    ("Retries", "retries"),
    ("Agreement", "agreement_rate"),
]

HEADERS = ["Policy", "Run", "Status"] + [h for h, _ in _METRIC_COLUMNS]


def _cells(entry) -> list:
    """Ordered string cells for one entry row: Policy, Run, Status, then metrics."""
    cells = [
        str(entry.get("policy", "")),
        str(entry.get("run_index", "")),
        str(entry.get("status", "")),
    ]
    row = entry.get("row")
    if not row:
        cells += [EM_DASH] * len(_METRIC_COLUMNS)
        return cells
    for _, key in _METRIC_COLUMNS:
        val = row.get(key)
        cells.append(EM_DASH if val in (None, "", "N/A") else str(val))
    return cells


def build_comparison_csv_rows(entries) -> list:
    """Header row followed by one row per entry."""
    return [list(HEADERS)] + [_cells(e) for e in entries]


def build_comparison_md(entries, batch_label: str) -> str:
    """Render the batch comparison as a Markdown document."""
    lines = [
        f"# Batch Comparison — {batch_label}",
        "",
        f"{len(entries)} policy-run(s) in this batch. Each policy's full JSON "
        "and report are saved separately; this table is a side-by-side survey "
        "of just this batch.",
        "",
        "| " + " | ".join(HEADERS) + " |",
        "|" + "|".join(["---"] * len(HEADERS)) + "|",
    ]
    for e in entries:
        lines.append("| " + " | ".join(_cells(e)) + " |")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python tests/test_batch_comparison.py`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add utils/batch_comparison.py tests/test_batch_comparison.py
git commit -m "feat: render batch comparison table (md + csv)"
```

Then run `git status --short` and confirm the only listed file is ` M .claude/settings.local.json`.

---

## Task 3: Wire batch mode into the CLI

**Files:**
- Modify: `main.py`

**Interfaces:**
- Consumes: `discover_policy_files` (Task 1), `build_comparison_md` / `build_comparison_csv_rows` (Task 2), and the existing `run_pipeline`, `save_result`, `build_index_row`.
- Produces: the `--policy-dir` CLI behavior and the `comparison_<batch_label>.{md,csv}` files. No downstream consumer.

This task has no unit test (it orchestrates the real LLM pipeline, which is offline-forbidden in CI). It is verified by (a) the argument/validation checks below, which run with **no API key**, and (b) the spec/code reviewer reading it. A real corpus run is optional and done by the user (costs money).

- [ ] **Step 1: Update imports**

In `main.py`, add `import csv` to the stdlib imports, and update the existing import lines so they read:

```python
from utils.runs_index import append_run_to_index, build_index_row
from utils.policy_loader import load_policy_text, SUPPORTED_EXTENSIONS, discover_policy_files
from utils.batch_comparison import build_comparison_md, build_comparison_csv_rows
```

(`append_run_to_index` and `load_policy_text, SUPPORTED_EXTENSIONS` are already imported; add the new names to those lines. Add the `batch_comparison` import next to the other `utils` imports.)

- [ ] **Step 2: Add a comparison-writer helper**

Add this module-level function to `main.py` (e.g. just after `_empty_result`):

```python
def _write_batch_comparison(entries: list, output_dir: Path) -> None:
    """Write comparison_<batch_label>.md and .csv for one batch run.

    batch_label is the run_id of the first entry that has a row (ok or empty);
    "failed" if every policy failed. Never fatal — the per-policy JSON/report
    and the cumulative runs index remain the source of truth.
    """
    try:
        batch_label = next(
            (e["row"]["run_id"] for e in entries if e.get("row")), "failed"
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        md_path = output_dir / f"comparison_{batch_label}.md"
        csv_path = output_dir / f"comparison_{batch_label}.csv"
        md_path.write_text(build_comparison_md(entries, batch_label), encoding="utf-8")
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(build_comparison_csv_rows(entries))
        print(f"\nBatch comparison (md):  {md_path}")
        print(f"Batch comparison (csv): {csv_path}")
    except Exception as exc:  # comparison is a convenience aggregate; never fatal
        print(f"  [batch] WARNING: could not write comparison: {exc}")
```

- [ ] **Step 3: Make `--policy` / `--policy-dir` a mutually-exclusive required group**

In `main()`, replace the current `--policy` argument definition:

```python
    parser.add_argument(
        "--policy",
        required=True,
        help="Path to the privacy policy file (.txt/.md/.html/.htm/.pdf/.docx)",
    )
```

with:

```python
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--policy",
        help="Path to a single privacy policy file (.txt/.md/.html/.htm/.pdf/.docx).",
    )
    source.add_argument(
        "--policy-dir",
        help="Path to a folder; runs every supported policy file inside it "
             "(batch/corpus mode). Mutually exclusive with --policy.",
    )
```

- [ ] **Step 4: Resolve the policy file list and mode (before the API-key check)**

Replace the current single-file validation block:

```python
    policy_path = Path(args.policy)
    if not policy_path.exists():
        print(f"ERROR: Policy file not found: {policy_path}", file=sys.stderr)
        sys.exit(1)

    if policy_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        print(
            f"ERROR: unsupported policy format '{policy_path.suffix}'; "
            f"supported: {' '.join(sorted(SUPPORTED_EXTENSIONS))}",
            file=sys.stderr,
        )
        sys.exit(1)
```

with a block that builds a unified `policy_files` list and a `batch_mode` flag (this runs before the `OPENROUTER_API_KEY` check, so the validation errors below need no API key):

```python
    if args.policy_dir:
        batch_mode = True
        policy_dir = Path(args.policy_dir)
        if not policy_dir.is_dir():
            print(f"ERROR: policy directory not found: {policy_dir}", file=sys.stderr)
            sys.exit(1)
        policy_files = discover_policy_files(policy_dir)
        if not policy_files:
            print(
                f"ERROR: no supported policy files "
                f"({' '.join(sorted(SUPPORTED_EXTENSIONS))}) found in {policy_dir}",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"Batch mode: {len(policy_files)} policy file(s) in {policy_dir}")
    else:
        batch_mode = False
        policy_path = Path(args.policy)
        if not policy_path.exists():
            print(f"ERROR: Policy file not found: {policy_path}", file=sys.stderr)
            sys.exit(1)
        if policy_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            print(
                f"ERROR: unsupported policy format '{policy_path.suffix}'; "
                f"supported: {' '.join(sorted(SUPPORTED_EXTENSIONS))}",
                file=sys.stderr,
            )
            sys.exit(1)
        policy_files = [policy_path]
```

(Leave the `OPENROUTER_API_KEY` check, `client = OpenAI(...)`, `output_dir`, and `agent_models` resolution exactly as they are, immediately after this block.)

- [ ] **Step 5: Replace the run loop with the policy × runs loop that collects entries**

Replace the current loop:

```python
    all_results = []
    for run_i in range(1, args.runs + 1):
        if args.runs > 1:
            print(f"\n{'#'*60}")
            print(f"# Run {run_i} of {args.runs}")
            print(f"{'#'*60}")

        blind_enabled = ENABLE_BLIND_LABELER and not args.no_blind_labeler
        try:
            result = run_pipeline(
                client, policy_path, agent_models=agent_models, blind_enabled=blind_enabled
            )
        except ValueError as exc:
            print(f"ERROR: could not read policy: {exc}", file=sys.stderr)
            sys.exit(1)
        save_result(result, output_dir, run_index=run_i)
        all_results.append(result)
```

with:

```python
    blind_enabled = ENABLE_BLIND_LABELER and not args.no_blind_labeler
    entries = []
    for policy_path in policy_files:
        if batch_mode:
            print(f"\n{'#'*60}")
            print(f"# Policy: {policy_path.name}")
            print(f"{'#'*60}")
        for run_i in range(1, args.runs + 1):
            if args.runs > 1:
                # Preserve the original single-mode run banner verbatim.
                print(f"\n{'#'*60}")
                print(f"# Run {run_i} of {args.runs}")
                print(f"{'#'*60}")
            try:
                result = run_pipeline(
                    client, policy_path,
                    agent_models=agent_models, blind_enabled=blind_enabled,
                )
            except Exception as exc:
                # Single mode preserves prior behavior: report and exit non-zero.
                if not batch_mode:
                    print(f"ERROR: could not read policy: {exc}", file=sys.stderr)
                    sys.exit(1)
                # Batch mode: record the failure and keep going with the rest.
                print(f"  [batch] ERROR: {policy_path.name} failed: {exc} — continuing.",
                      file=sys.stderr)
                entries.append({
                    "policy": policy_path.stem, "run_index": run_i,
                    "status": "failed", "row": None, "error": str(exc),
                })
                continue

            save_result(result, output_dir, run_index=run_i)
            entries.append({
                "policy": policy_path.stem,
                "run_index": run_i,
                "status": "empty" if result.get("error") else "ok",
                "row": build_index_row(result),
                "error": result.get("error"),
            })

    if batch_mode:
        _write_batch_comparison(entries, output_dir)
```

- [ ] **Step 6: Verify single-mode behavior is unchanged (no API key needed for these checks)**

Run each and confirm the error/exit behavior. On PowerShell, `$LASTEXITCODE` holds the exit code.

Mutually-exclusive group is required — neither flag:
```powershell
python main.py; $LASTEXITCODE
```
Expected: argparse usage error mentioning `one of the arguments --policy --policy-dir is required`; exit code `2`.

Both flags rejected:
```powershell
python main.py --policy data/policies/policy_short.txt --policy-dir data/policies; $LASTEXITCODE
```
Expected: argparse error `argument --policy-dir: not allowed with argument --policy`; exit code `2`.

Missing directory:
```powershell
python main.py --policy-dir does_not_exist_dir; $LASTEXITCODE
```
Expected: `ERROR: policy directory not found: does_not_exist_dir`; exit code `1`.

Empty directory (no supported files):
```powershell
$tmp = New-Item -ItemType Directory -Path (Join-Path $env:TEMP ("emptybatch_" + [System.Guid]::NewGuid())); python main.py --policy-dir $tmp.FullName; $LASTEXITCODE; Remove-Item $tmp -Recurse -Force
```
Expected: `ERROR: no supported policy files (...) found in <tmp>`; exit code `1`.

(These all return before the `OPENROUTER_API_KEY` check, so they pass without a key. Do NOT run a real `--policy`/`--policy-dir` pipeline here — that needs the key and costs money.)

- [ ] **Step 7: Re-run the offline test suites to confirm nothing regressed**

```powershell
Get-ChildItem tests/test_*.py | ForEach-Object { Write-Host "=== $($_.Name) ==="; python $_.FullName; if ($LASTEXITCODE -ne 0) { throw "FAILED: $($_.Name)" } }
```
Expected: every suite prints `OK`; no `FAILED:` thrown.

- [ ] **Step 8: Commit**

```bash
git add main.py
git commit -m "feat: add --policy-dir batch mode with comparison output"
```

Then run `git status --short` and confirm the only listed file is ` M .claude/settings.local.json`.

---

## Task 4: Update the README usage (optional, post-merge or inline)

**Files:**
- Modify: `README.md`

**Interfaces:** none.

- [ ] **Step 1: Document batch mode in the Usage section**

Find the Usage section that shows `python main.py --policy ...` and add a batch example beneath it, e.g.:

```markdown
Run a whole folder of policies and get a side-by-side comparison:

    python main.py --policy-dir data/policies/

This runs every supported policy in the folder (each still gets its own JSON and
report) and writes a batch comparison table to
`output/results/comparison_<id>.md` (and `.csv`).
```

Match the surrounding heading style and code-block format already used in the README; do not change unrelated sections.

- [ ] **Step 2: Verify and commit**

Run: `python -c "t=open('README.md',encoding='utf-8').read(); print('ok' if '--policy-dir' in t else 'MISSING')"`
Expected: `ok`.

```bash
git add README.md
git commit -m "docs: document --policy-dir batch mode in the README"
```

Then run `git status --short` and confirm the only listed file is ` M .claude/settings.local.json`.

---

## Notes for the implementer

- **No pytest.** Run suites directly: `python tests/<file>.py`; success prints `OK`, failure exits non-zero.
- **Offline only.** The discovery and comparison code make no network/LLM call. Never add an API key; never invoke the real pipeline in a test. The Task 3 verification commands deliberately exercise only the no-key validation paths.
- **Reuse, don't re-extract.** Comparison cells come from `build_index_row(result)` — do not pull fields off the raw result dict in `batch_comparison.py`.
- **Single mode is sacred.** If any Task 3 change alters single-policy outputs or exit codes, it is wrong.
- **Do not commit `.claude/settings.local.json`.** Only `git add` the exact files listed in each commit step.
