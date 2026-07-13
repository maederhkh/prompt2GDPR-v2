# Finish Human Review Brief — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete and commit the Human Review Brief feature: lock in the already-built renderer/CLI/tests, generate the brief automatically on every run, and document it.

**Architecture:** The pure renderer (`utils/review_report.py`), standalone CLI (`review_run.py`), and its tests (`tests/test_review_report.py`) already exist and pass — they were built in an earlier session but were never committed. This plan commits them as-is, then adds a small non-fatal call inside `main.py`'s `save_result` so each run writes `<stem>_review.md` next to the JSON and full report, and documents the artifact and the `review_run.py` command in the README.

**Tech Stack:** Python 3.12, standard library only. Tests are standalone assert scripts (NOT pytest). Dev machine is Windows + PowerShell (chain commands with `;`, never `&&`).

## Global Constraints

- **Offline only.** No LLM/network/API key in any automated test. Never invoke the real pipeline (`main()` / `run_pipeline`) — it needs `OPENROUTER_API_KEY`.
- Tests are **standalone assert scripts**: each `tests/test_*.py` inserts the repo root on `sys.path`, defines `test_*()` functions, and a `__main__` block that calls them and prints `OK`; any failure raises and exits non-zero. Run one with `python tests/<file>.py`.
- **The automatic brief must never crash a run.** If review-brief generation fails inside `save_result`, print a warning and continue — the same way `append_run_to_index` treats index failures as non-fatal convenience-output failures (spec §5).
- **Reuse the existing public API** of the already-built renderer — do NOT rewrite `utils/review_report.py`, `review_run.py`, or `tests/test_review_report.py`. Their public functions are `render_review_report(result) -> str` and `write_review_report(result, path) -> None`.
- The automatic artifact path is `<stem>_review.md`, where `<stem>` is the exact stem `save_result` already computes for the JSON and report (`f"{policy_name}_{run_id}{multi_suffix}"`).
- `docs/` is gitignored; `README.md`, `main.py`, `utils/`, `tests/`, and root `.py` files are tracked normally. Only `git add` the exact files named in each commit step (never `git add -A`). Do NOT stage `.claude/settings.local.json` or anything under `.superpowers/`.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `utils/review_report.py` | Commit as-is | Pure renderer: extracts review issues from a result dict and renders markdown. Already built, tested. |
| `review_run.py` | Commit as-is | Standalone CLI: load one run JSON, write `<stem>_review.md`, print the path. Already built. |
| `tests/test_review_report.py` | Commit as-is | Renderer + CLI tests using fake result dicts. Already built, passing. |
| `main.py` | Modify | Add a guarded `_write_review_brief` helper and call it from `save_result` after the full report is written. |
| `tests/test_save_result_review.py` | Create | Offline test of the `_write_review_brief` helper: happy path writes the file; a failing renderer is swallowed (never raises). |
| `README.md` | Modify | Document the `<run>_review.md` artifact and the `python review_run.py <json>` command. |

---

## Task 1: Commit the already-built renderer, CLI, and tests

The three files below already exist in the working tree (untracked) and pass. This task verifies they are green and commits them unchanged — locking in prior work so the rest of the feature (and the final review) can build on a clean base. No code is written in this task.

**Files:**
- Commit as-is: `utils/review_report.py`, `review_run.py`, `tests/test_review_report.py`

- [ ] **Step 1: Verify the existing tests pass**

Run: `python tests/test_review_report.py`
Expected: prints `OK` (non-zero exit on any failure).

- [ ] **Step 2: Confirm exactly these three files are untracked and unchanged**

Run: `git status --short`
Expected: the three files appear as untracked (`??`): `review_run.py`, `tests/test_review_report.py`, `utils/review_report.py`. If any of the three is missing, STOP and report — the prior work is not present and this plan's assumption is wrong.

- [ ] **Step 3: Commit the three files**

```bash
git add utils/review_report.py review_run.py tests/test_review_report.py
git commit -m "feat: add human review brief renderer and standalone CLI"
```

Then run `git status --short` and confirm only intended files were committed (`.claude/settings.local.json` and `.superpowers/` must NOT appear as staged).

---

## Task 2: Generate the review brief automatically in `save_result`

**Files:**
- Modify: `main.py` (add module-level `_write_review_brief`; add import; call it inside `save_result`)
- Test: `tests/test_save_result_review.py` (create)

**Interfaces:**
- Consumes: `write_review_report(result, path)` from `utils/review_report.py` (committed in Task 1).
- Produces: `main._write_review_brief(result: dict, output_dir: Path, stem: str) -> Path | None` — writes `<stem>_review.md` under `output_dir` and returns its path, or prints a warning and returns `None` if rendering raises. `save_result` calls it after `generate_report`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_save_result_review.py`:

```python
"""Offline tests for automatic review-brief generation in save_result."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import main


def _min_result() -> dict:
    # The renderer is defensive; policy_name + finalizer_output is enough.
    return {
        "policy_name": "policy_x",
        "finalizer_output": {"overall_label": "Compliant", "confidence": "high"},
    }


def test_write_review_brief_creates_file():
    d = Path(tempfile.mkdtemp())
    try:
        path = main._write_review_brief(_min_result(), d, "policy_x_run")
        assert path is not None
        assert path.exists()
        assert path.name == "policy_x_run_review.md"
        assert "# Human Review Brief" in path.read_text(encoding="utf-8")
    finally:
        shutil.rmtree(d)


def test_write_review_brief_never_raises():
    # A broken renderer must be swallowed so a good run still succeeds.
    d = Path(tempfile.mkdtemp())
    original = main.write_review_report

    def _boom(*args, **kwargs):
        raise RuntimeError("render failed")

    try:
        main.write_review_report = _boom
        path = main._write_review_brief(_min_result(), d, "policy_x_run")
        assert path is None
    finally:
        main.write_review_report = original
        shutil.rmtree(d)


if __name__ == "__main__":
    test_write_review_brief_creates_file()
    test_write_review_brief_never_raises()
    print("OK")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_save_result_review.py`
Expected: FAIL — `AttributeError: module 'main' has no attribute '_write_review_brief'` (and/or `write_review_report`). Non-zero exit, no `OK`.

- [ ] **Step 3: Add the import in `main.py`**

Find the existing import of the report generator near the top of `main.py` (the line importing `generate_report`, e.g. `from utils.report_generator import generate_report`). Immediately after it, add:

```python
from utils.review_report import write_review_report
```

- [ ] **Step 4: Add the `_write_review_brief` helper in `main.py`**

Add this module-level function directly above the `save_result` definition:

```python
def _write_review_brief(result: dict, output_dir: Path, stem: str):
    """Write <stem>_review.md next to the full report. Convenience artifact —
    a failure here must never fail an otherwise-successful run (mirrors how
    append_run_to_index treats index failures as non-fatal)."""
    try:
        review_path = output_dir / f"{stem}_review.md"
        write_review_report(result, review_path)
        return review_path
    except Exception as exc:  # convenience output must not crash a run
        print(f"  [warn] could not write review brief: {exc}")
        return None
```

- [ ] **Step 5: Call it from `save_result`**

In `save_result`, the body currently reads:

```python
    # Markdown — human-readable report
    report_path = output_dir / f"{stem}_report.md"
    generate_report(result, report_path)

    # Cumulative runs index — append one summary row per run (md + csv)
    append_run_to_index(result, output_dir)

    print(f"\nJSON saved to:   {json_path}")
    print(f"Report saved to: {report_path}")
    return json_path
```

Change it to:

```python
    # Markdown — human-readable report
    report_path = output_dir / f"{stem}_report.md"
    generate_report(result, report_path)

    # Markdown — reviewer-focused brief (convenience artifact; never fatal)
    review_path = _write_review_brief(result, output_dir, stem)

    # Cumulative runs index — append one summary row per run (md + csv)
    append_run_to_index(result, output_dir)

    print(f"\nJSON saved to:   {json_path}")
    print(f"Report saved to: {report_path}")
    if review_path is not None:
        print(f"Review saved to: {review_path}")
    return json_path
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `python tests/test_save_result_review.py`
Expected: `OK`.

- [ ] **Step 7: Confirm `main` still imports cleanly**

Run: `python -c "import main; print('IMPORT OK')"`
Expected: prints `IMPORT OK`.

- [ ] **Step 8: Run the full offline suite**

```powershell
Get-ChildItem tests/test_*.py | ForEach-Object { Write-Host "=== $($_.Name) ==="; python $_.FullName; if ($LASTEXITCODE -ne 0) { throw "FAILED: $($_.Name)" } }
```
Expected: every suite prints `OK`; no `FAILED:` thrown.

- [ ] **Step 9: Commit**

```bash
git add main.py tests/test_save_result_review.py
git commit -m "feat: write a human review brief automatically on each run"
```

Then run `git status --short` and confirm only `main.py` and `tests/test_save_result_review.py` were staged.

---

## Task 3: Document the review brief in the README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add the artifact to the Output section**

In `README.md`, the automatic-outputs list under `## Output` ends with the `runs_index.md / runs_index.csv` bullet. Add a new bullet immediately after it:

```markdown
- **`<policy>_<run_id>_review.md`**  a concise **Human Review Brief** — a reviewer-focused triage artifact that surfaces only the review-critical parts of a run (disputed clauses, unverified/flagged evidence, reflector findings, low-confidence signals, and the legal references used), sorted by priority. It is generated automatically for every run and never blocks a run if it cannot be written. It makes no LLM calls — it re-reads what the run already produced.
```

- [ ] **Step 2: Document the standalone command under Analysis Tools**

In the `## Analysis Tools` section, after the `diff_runs.py` subsection (which ends with the paragraph beginning "Compares two run JSONs clause by clause…"), add:

```markdown
**Regenerate a review brief for any past run:**

```bash
python review_run.py output/results/<run>.json
```

Regenerates the Human Review Brief from an existing run JSON without rerunning the pipeline (read-only, zero LLM calls). Writes `<run>_review.md` next to the JSON; pass `--output PATH` to choose a different destination. If the file is missing or is not a pipeline-run JSON, it prints a readable message and exits cleanly. Use this to produce briefs for runs saved before this feature existed, or to regenerate one after deleting it.
```

- [ ] **Step 3: Verify the README renders and links are intact**

Run: `git diff --stat README.md`
Expected: `README.md` shows additions only (no unrelated changes). Visually confirm the two new blocks read correctly and the fenced code block in Step 2 is closed.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document the human review brief artifact and review_run.py"
```

---

## Notes for the implementer

- **No pytest.** Run a suite directly: `python tests/<file>.py`; success prints `OK`, failure exits non-zero.
- **Offline only.** Never invoke the real pipeline. The Task 2 test imports `main` (safe — the pipeline only runs under `main()` / `if __name__ == "__main__"`, not at import) and calls the helper directly with a fake result.
- **Do not rewrite the Task 1 files.** They are complete and tested; Task 1 only verifies and commits them.
- **The `except Exception` in `_write_review_brief` is intentional and required** by the spec's never-crash-a-run rule (§5) — it is not an over-broad catch to be narrowed.
- The `test_write_review_brief_never_raises` test swaps `main.write_review_report` for a raising stub and restores it in `finally`; this verifies the guard without needing a genuinely malformed result (the renderer is too defensive to fail on its own).
