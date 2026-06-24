# Surface Scout Decisions in the Human Report — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Section Scout" subsection to each run's human-readable `report.md` that surfaces the auditable scout decisions (`include` / `maybe_include` / `exclude`, each with reason and confidence) already saved in the run JSON.

**Architecture:** One new pure, offline-testable helper `_render_scout_section(scout_report) -> list[str]` in `utils/report_generator.py` that turns a `scout_report` dict into markdown lines (or `[]` when there's nothing to show). `generate_report` calls it inside the existing `## Clause Extraction` section. No pipeline, JSON, schema, or other-section changes.

**Tech Stack:** Python 3.12, standard library only. Tests are standalone assert scripts. Dev machine is Windows + PowerShell (chain with `;`, never `&&`).

## Global Constraints

- **Offline only.** This is a pure rendering change — no LLM/network call, no API key. Do NOT run `main.py`'s real pipeline in any automated test.
- Tests are **standalone assert scripts** (NOT pytest): each `tests/test_*.py` adds the repo root to `sys.path`, defines `test_*()` functions, and a `__main__` block that calls them and prints `OK`; any failure raises and exits non-zero.
- **No change to the JSON output, the `scout_report` schema, the pipeline, agents, prompts, the runs index, the batch comparison, or any existing report section.** Only the new subsection is added.
- Runs **without** a `scout_report` (older runs, single-pass fallback) must render exactly as they do today — the new subsection is silently omitted.
- `docs/` is gitignored (not touched by these tasks). `utils/`, `tests/` are NOT gitignored and stage normally.
- Do NOT commit `.claude/settings.local.json`. Only `git add` the exact files named in each commit step.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `utils/report_generator.py` | Modify | Add `_render_scout_section(scout_report)` pure helper; call it in the `## Clause Extraction` block |
| `tests/test_report_scout_section.py` | Create | Unit tests for `_render_scout_section` |

Repo facts for the implementer (verified):
- `utils/report_generator.py` defines `generate_report(result: dict, out_path: Path) -> None`. It builds a `lines: list[str]` and writes `"\n".join(lines)` to `out_path`. Near the top it sets `extractor = result.get("extractor_output", {})`. It renders a `## Clause Extraction` section (heading `lines.append("## Clause Extraction")`) whose bullets end before a `lines.append("---")` separator that precedes `## Clause Assessments`.
- The scout report lives at `result["extractor_output"]["scout_report"]` — i.e. `extractor.get("scout_report")` inside `generate_report`. Its shape:
  ```python
  {
    "schema_version": "section_decisions_v1",
    "include":       [decision, ...],
    "maybe_include": [decision, ...],
    "exclude":       [decision, ...],
  }
  ```
  Each `decision`:
  ```python
  {"heading": str, "reason": str, "signals": list[str], "confidence": "high"|"medium"|"low"}
  ```
  `confidence` is already normalized to one of the three values; `heading`/`reason` are strings; `signals` is a list of strings. An empty/failed scout produces all three buckets empty. Single-pass fallback output has **no** `scout_report` key at all.

---

## Task 1: Render the Section Scout subsection

**Files:**
- Modify: `utils/report_generator.py`
- Test: `tests/test_report_scout_section.py`

**Interfaces:**
- Consumes: a `scout_report` dict (or `None`) of the shape documented above.
- Produces: `_render_scout_section(scout_report) -> list[str]` — a module-level pure function returning markdown lines (empty list when nothing to show). Called by `generate_report`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_report_scout_section.py`:

```python
"""Standalone assert tests for _render_scout_section in the report generator."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.report_generator import _render_scout_section


def _report():
    return {
        "schema_version": "section_decisions_v1",
        "include": [
            {"heading": "3.1 How we use data", "reason": "States processing purposes.",
             "signals": ["processing purposes"], "confidence": "high"},
        ],
        "maybe_include": [
            {"heading": "3.8 Statistics", "reason": "May describe analytics.",
             "signals": ["analytics"], "confidence": "medium"},
        ],
        "exclude": [
            {"heading": "12. Contact us", "reason": "Administrative only.",
             "signals": [], "confidence": "low"},
        ],
    }


def test_full_report_has_heading_counts_and_one_row_per_decision():
    lines = _render_scout_section(_report())
    text = "\n".join(lines)
    assert "### Section Scout" in text, text
    # counts line: 1 included, 1 maybe, 1 excluded
    assert "**1** included" in text and "**1** maybe-include" in text and "**1** excluded" in text, text
    # table header present
    assert "| Section | Decision | Confidence | Reason |" in text, text
    # one data row per decision (3 headings appear)
    assert text.count("3.1 How we use data") == 1
    assert text.count("3.8 Statistics") == 1
    assert text.count("12. Contact us") == 1


def test_grouping_and_decision_labels():
    lines = _render_scout_section(_report())
    text = "\n".join(lines)
    # include row appears before maybe row before exclude row
    i_inc = text.index("3.1 How we use data")
    i_maybe = text.index("3.8 Statistics")
    i_exc = text.index("12. Contact us")
    assert i_inc < i_maybe < i_exc, (i_inc, i_maybe, i_exc)
    # decision labels: include -> "include", maybe_include -> "maybe", exclude -> "exclude"
    assert "| include |" in text, text
    assert "| maybe |" in text, text
    assert "| exclude |" in text, text


def test_pipe_and_newline_in_reason_are_escaped():
    report = {
        "include": [
            {"heading": "A | B", "reason": "first line\nsecond | piped",
             "signals": [], "confidence": "high"},
        ],
        "maybe_include": [],
        "exclude": [],
    }
    lines = _render_scout_section(report)
    text = "\n".join(lines)
    # the raw reason must not introduce a literal newline inside the table region,
    # and pipes inside cells must be escaped to "\|"
    assert "first line second \\| piped" in text, text
    assert "A \\| B" in text, text
    # no decision's content should create an extra unescaped row break:
    # every table data row starts with "| " — count matches the single decision
    data_rows = [ln for ln in lines if ln.startswith("| ") and "Section" not in ln and "---" not in ln]
    assert len(data_rows) == 1, data_rows


def test_empty_or_missing_report_returns_empty_list():
    assert _render_scout_section(None) == []
    assert _render_scout_section({}) == []
    assert _render_scout_section(
        {"include": [], "maybe_include": [], "exclude": []}
    ) == []


if __name__ == "__main__":
    test_full_report_has_heading_counts_and_one_row_per_decision()
    test_grouping_and_decision_labels()
    test_pipe_and_newline_in_reason_are_escaped()
    test_empty_or_missing_report_returns_empty_list()
    print("OK")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_report_scout_section.py`
Expected: FAIL with `ImportError: cannot import name '_render_scout_section'`.

- [ ] **Step 3: Implement `_render_scout_section`**

In `utils/report_generator.py`, add this module-level function (e.g. directly above `def generate_report`):

```python
def _render_scout_section(scout_report) -> list:
    """
    Render the Section Scout subsection from a scout_report dict.

    Returns a list of markdown lines, or [] when there is nothing to show
    (scout_report is None/empty, or all three buckets are empty). Pure: writes
    nothing and does not mutate the input.

    scout_report shape:
        {"include": [decision, ...], "maybe_include": [...], "exclude": [...]}
    decision shape:
        {"heading": str, "reason": str, "signals": list, "confidence": str}
    """
    if not scout_report:
        return []

    include = scout_report.get("include") or []
    maybe = scout_report.get("maybe_include") or []
    exclude = scout_report.get("exclude") or []
    if not (include or maybe or exclude):
        return []

    def _cell(value) -> str:
        # Sanitize a free-text cell so it can't break the markdown table.
        return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")

    lines = [
        "### Section Scout",
        "",
        f"- Scout decisions: **{len(include)}** included, "
        f"**{len(maybe)}** maybe-include, **{len(exclude)}** excluded",
        "",
        "| Section | Decision | Confidence | Reason |",
        "|---|---|---|---|",
    ]
    for label, bucket in (("include", include), ("maybe", maybe), ("exclude", exclude)):
        for decision in bucket:
            heading = _cell(decision.get("heading", ""))
            confidence = _cell(decision.get("confidence", ""))
            reason = _cell(decision.get("reason", ""))
            lines.append(f"| {heading} | {label} | {confidence} | {reason} |")
    lines.append("")
    return lines
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python tests/test_report_scout_section.py`
Expected: `OK`.

- [ ] **Step 5: Wire it into `generate_report`**

In `utils/report_generator.py`, find the `## Clause Extraction` block. It ends with the extractor-notes bullet and a trailing `lines.append(f"")`, immediately before the `## Clause Assessments` block that starts with `lines.append(f"---")`. The current code is:

```python
    if extractor.get("extraction_notes"):
        lines.append(f"- Extractor notes: {extractor['extraction_notes']}")
    lines.append(f"")
```

Add the scout-section call right after that trailing blank-line append, so it reads:

```python
    if extractor.get("extraction_notes"):
        lines.append(f"- Extractor notes: {extractor['extraction_notes']}")
    lines.append(f"")

    lines.extend(_render_scout_section(extractor.get("scout_report")))
```

(`extractor` is already defined near the top of `generate_report` as `result.get("extractor_output", {})`. Do not re-read it.)

- [ ] **Step 6: Confirm the full report still builds and existing tests pass**

Verify the report generator still imports and runs on a minimal result with no scout_report (it must not raise and must add no scout section):

```powershell
python -c "import os; from pathlib import Path; from utils.report_generator import generate_report; p=Path(os.environ['TEMP'])/'._scout_plan_check.md'; generate_report({'extractor_output': {}, 'finalizer_output': {}, 'evaluator_output': {}}, p); t=p.read_text(encoding='utf-8'); print('NO SCOUT SECTION' if 'Section Scout' not in t else 'UNEXPECTED SECTION'); p.unlink()"
```
Expected: `NO SCOUT SECTION`.

Then re-run all offline suites:

```powershell
Get-ChildItem tests/test_*.py | ForEach-Object { Write-Host "=== $($_.Name) ==="; python $_.FullName; if ($LASTEXITCODE -ne 0) { throw "FAILED: $($_.Name)" } }
```
Expected: every suite prints `OK`; no `FAILED:` thrown.

- [ ] **Step 7: Commit**

```bash
git add utils/report_generator.py tests/test_report_scout_section.py
git commit -m "feat: surface scout decisions in the human report"
```

Then run `git status --short` and confirm the only listed file is ` M .claude/settings.local.json` (if present) — and that `utils/report_generator.py` and `tests/test_report_scout_section.py` are committed.

---

## Notes for the implementer

- **No pytest.** Run the suite directly: `python tests/test_report_scout_section.py`; success prints `OK`, failure exits non-zero.
- **Offline only.** No network/LLM call; never invoke the real pipeline.
- **Pure helper.** `_render_scout_section` returns lines and writes nothing; all table cells pass through the `_cell` sanitizer so a pipe or newline in model free-text can't break the table.
- **Existing reports unchanged.** When `scout_report` is missing/empty the helper returns `[]`, so older runs and the single-pass fallback render exactly as before.
- **Only stage the two named files.** Do not commit `.claude/settings.local.json`.
