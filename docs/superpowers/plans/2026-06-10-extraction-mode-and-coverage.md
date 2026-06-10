# Extraction Mode Flag + Coverage-Confidence Column Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record which extraction path ran (`extraction_mode`: `two_pass`/`single_pass`) in the result, surface it in the markdown report as an honest coverage-confidence signal, and add a `coverage` column (`high`/`low`/`—`) to the runs index.

**Architecture:** Four small, independent changes. The extractor tags its output with `extraction_mode` (two literal assignments). The report generator renders an "Extraction mode" + "Coverage confidence" line from that tag. `build_index_row` derives a `coverage` column from it (schema 14 → 15; the index writer's existing `.bak` backup handles the schema bump). A new fake-client test drives both extractor paths offline; an offline end-to-end check verifies the report + index together.

**Tech Stack:** Python 3.12, stdlib + existing deps (`rapidfuzz`, OpenAI client only as a type — tests use a fake). No pytest — tests are standalone `assert` scripts run with `python tests/<file>.py` that print `OK`. Windows + PowerShell (chain with `;`). Git LF→CRLF warnings are cosmetic.

**Spec:** `docs/superpowers/specs/2026-06-10-extraction-mode-and-coverage-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `agents/extractor.py` | Modify | Set `extraction_mode` in the two-pass result dict and in `_run_single_pass` |
| `tests/test_extraction_mode.py` | Create | Fake-client tests driving both extractor paths |
| `utils/runs_index.py` | Modify | `FIELDS`/`MD_HEADERS` → 15; derive `coverage` from `extraction_mode` |
| `tests/test_runs_index.py` | Modify | 15-field schema + coverage assertions (high/low/—) |
| `utils/report_generator.py` | Modify | Replace "Coverage: Complete" with "Extraction mode" + "Coverage confidence" lines |

---

## Task 1: Tag the extractor output with `extraction_mode`

**Files:**
- Modify: `agents/extractor.py`
- Create: `tests/test_extraction_mode.py`

- [ ] **Step 1: Write the failing test (fake-client, both paths)**

Create `tests/test_extraction_mode.py` with EXACTLY this content:

```python
"""Standalone assert tests for the extractor's extraction_mode flag.

Uses a minimal fake OpenAI-style client (no network). The Scout call uses
SCOUT_SYSTEM; section-extraction and single-pass use EXTRACTOR_SYSTEM, so the
fake routes on the system message. The two-pass policy is crafted so the single
content paragraph is fully covered by the returned clause quote — the self-check
then finds no uncovered paragraphs and makes no further LLM calls.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from prompts.scout_prompt import SCOUT_SYSTEM
from agents.extractor import run_extractor


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Completions:
    def __init__(self, parent):
        self._p = parent

    def create(self, model=None, max_tokens=None, messages=None):
        system = messages[0]["content"]
        if system == SCOUT_SYSTEM:
            body = {"relevant_sections": self._p.scout_sections}
        else:
            body = {
                "policy_name": "P",
                "extracted_clauses": self._p.clauses,
                "extraction_notes": None,
                "coverage_complete": True,
            }
        return _Resp(json.dumps(body))


class _Chat:
    def __init__(self, parent):
        self.completions = _Completions(parent)


class FakeClient:
    def __init__(self, scout_sections, clauses):
        self.scout_sections = scout_sections
        self.clauses = clauses
        self.chat = _Chat(self)


_PARAGRAPH = (
    "We use your personal data only for the stated purposes and never for "
    "incompatible secondary purposes."
)


def test_single_pass_mode():
    # Scout returns no sections -> single-pass fallback.
    client = FakeClient(
        scout_sections=[],
        clauses=[{
            "clause_id": "C1",
            "quote": _PARAGRAPH,
            "section_reference": "Data Use",
            "relevance_type": "stated_purpose",
        }],
    )
    result = run_extractor(client, "P", "Some policy text.", model="x", scout_model="y")
    assert result["extraction_mode"] == "single_pass", result.get("extraction_mode")


def test_two_pass_mode():
    # Scout returns a heading present in the policy text -> two-pass.
    policy_text = f"Data Use\n\n{_PARAGRAPH}"
    client = FakeClient(
        scout_sections=["Data Use"],
        clauses=[{
            "clause_id": "C1",
            "quote": _PARAGRAPH,                 # == the paragraph -> covered, no self-check calls
            "section_reference": "Data Use",
            "relevance_type": "stated_purpose",
        }],
    )
    result = run_extractor(client, "P", policy_text, model="x", scout_model="y")
    assert result["extraction_mode"] == "two_pass", result.get("extraction_mode")
    assert "sections_processed" in result


if __name__ == "__main__":
    test_single_pass_mode()
    test_two_pass_mode()
    print("OK")
```

- [ ] **Step 2: Run the test to confirm it FAILS**

Run: `python tests/test_extraction_mode.py`
Expected: FAIL — `AssertionError` (the result has no `extraction_mode` key yet, so `result["extraction_mode"]` raises `KeyError`, or the assert reports `None`).

- [ ] **Step 3: Add `extraction_mode` to the two-pass result dict**

In `agents/extractor.py`, find the two-pass result assembly inside `run_extractor`:

```python
    result = {
        "policy_name": policy_name,
        "extracted_clauses": all_clauses,
        "extraction_notes": notes,
        "coverage_complete": True,
        "sections_processed": [s["name"] for s in sections],
        "self_check_report": self_check_report,
    }
```

Replace it with (adds `extraction_mode`):

```python
    result = {
        "policy_name": policy_name,
        "extracted_clauses": all_clauses,
        "extraction_notes": notes,
        "coverage_complete": True,
        "extraction_mode": "two_pass",
        "sections_processed": [s["name"] for s in sections],
        "self_check_report": self_check_report,
    }
```

- [ ] **Step 4: Add `extraction_mode` to the single-pass path**

In `agents/extractor.py`, inside `_run_single_pass`, find the end of the function:

```python
    errors = validate_extractor_output(data)
    if errors:
        raise ValueError(
            "Extractor output failed validation:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    return data
```

Replace with (tags the mode before returning):

```python
    errors = validate_extractor_output(data)
    if errors:
        raise ValueError(
            "Extractor output failed validation:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    data["extraction_mode"] = "single_pass"
    return data
```

- [ ] **Step 5: Run the test to confirm it PASSES**

Run: `python tests/test_extraction_mode.py`
Expected output: `OK`

- [ ] **Step 6: Commit**

```bash
git add agents/extractor.py tests/test_extraction_mode.py
git commit -m "feat: tag extractor output with extraction_mode (two_pass/single_pass)"
```

---

## Task 2: Add the `coverage` column to the runs index

**Files:**
- Modify: `utils/runs_index.py`
- Modify: `tests/test_runs_index.py`

- [ ] **Step 1: Update the test fixtures and builder tests (write failing tests first)**

In `tests/test_runs_index.py`, add an `extractor_output` to `_full_result()` so it exercises `two_pass`. Find the closing of `_full_result`'s dict:

```python
        "label_panel": {
            "disputed_count": 26,
            "anchoring_summary": {
                "reflector_a": {"shift_rate": 0.35},
                "reflector_b": {"shift_rate": 0.37},
            },
        },
    }
```

Replace with (adds `extractor_output`):

```python
        "label_panel": {
            "disputed_count": 26,
            "anchoring_summary": {
                "reflector_a": {"shift_rate": 0.35},
                "reflector_b": {"shift_rate": 0.37},
            },
        },
        "extractor_output": {"extraction_mode": "two_pass"},
    }
```

(`_empty_result()` keeps `"extractor_output": {}` — no mode, exercises the `—` fallback.)

In `test_build_index_row_full`, add this line right after `assert row["clauses"] == 68`:

```python
    assert row["coverage"] == "high"
```

In `test_build_index_row_empty_result`, add this line right after `assert row["clauses"] == 0`:

```python
    assert row["coverage"] == "—"
```

Add a new builder test for the single-pass case (place it right after `test_build_index_row_empty_result`):

```python
def test_build_index_row_single_pass_coverage():
    r = _full_result()
    r["extractor_output"] = {"extraction_mode": "single_pass"}
    row = build_index_row(r)
    assert row["coverage"] == "low"
```

Register it in the `__main__` block — change:

```python
if __name__ == "__main__":
    test_build_index_row_full()
    test_build_index_row_empty_result()
    test_append_newest_first()
    test_schema_mismatch_backs_up()
    print("OK")
```

to:

```python
if __name__ == "__main__":
    test_build_index_row_full()
    test_build_index_row_empty_result()
    test_build_index_row_single_pass_coverage()
    test_append_newest_first()
    test_schema_mismatch_backs_up()
    print("OK")
```

- [ ] **Step 2: Run the tests to confirm they FAIL**

Run: `python tests/test_runs_index.py`
Expected: FAIL — `AssertionError` on `list(row.keys()) == FIELDS` (the builder has no `coverage` key, and `FIELDS` does not yet contain it) or a `KeyError` on `row["coverage"]`.

- [ ] **Step 3: Add `coverage` to `FIELDS` and `MD_HEADERS`**

In `utils/runs_index.py`, replace the entire `FIELDS = [...]` list with (inserts `"coverage"` after `"clauses"`):

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
    "coverage",
    "agreement_rate",
    "retries",
    "disputed",
    "blind",
    "anchoring_a",
    "anchoring_b",
]
```

Replace the entire `MD_HEADERS = [...]` list with (inserts `"Coverage"` after `"Clauses"`):

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
    "Coverage",
    "Agreement",
    "Retries",
    "Disputed",
    "Blind",
    "Anchoring A",
    "Anchoring B",
]
```

- [ ] **Step 4: Derive `coverage` in `build_index_row`**

In `utils/runs_index.py`, in `build_index_row`, add a derivation line alongside the other locals (right after the `gc = rm.get("git_commit", {}) or {}` line):

```python
    eo = result.get("extractor_output", {}) or {}
    coverage = {"two_pass": "high", "single_pass": "low"}.get(eo.get("extraction_mode"), EM_DASH)
```

Then add the `coverage` key to the returned dict, immediately after the `clauses` entry. Find:

```python
        "clauses": rm.get("clause_count", len(result.get("verified_clauses", []))),
        "agreement_rate": refl.get("agreement_rate", "N/A"),
```

Replace with:

```python
        "clauses": rm.get("clause_count", len(result.get("verified_clauses", []))),
        "coverage": coverage,
        "agreement_rate": refl.get("agreement_rate", "N/A"),
```

Also update the `build_index_row` docstring count: change `Map a pipeline result dict to an ordered dict of the 14 index fields.` to `... 15 index fields.`

- [ ] **Step 5: Run the full test file to confirm all PASS**

Run: `python tests/test_runs_index.py`
Expected output: `OK`

(`test_append_newest_first` and `test_schema_mismatch_backs_up` still pass: they assert `rows[0] == FIELDS` and the run_id in column 0, both unaffected by the new column.)

- [ ] **Step 6: Commit**

```bash
git add utils/runs_index.py tests/test_runs_index.py
git commit -m "feat: add coverage-confidence column (high/low) to runs index"
```

---

## Task 3: Show extraction mode + coverage confidence in the markdown report

**Files:**
- Modify: `utils/report_generator.py`

- [ ] **Step 1: Replace the coverage line with mode + confidence lines**

In `utils/report_generator.py`, find the Clause Extraction block:

```python
    coverage = "Complete" if extractor.get("coverage_complete", True) else "**Incomplete — policy may contain more relevant clauses**"
    lines.append(f"- Verified clauses: **{len(verified)}**")
    lines.append(f"- Flagged clauses (failed verification): **{len(flagged)}**")
    lines.append(f"- Coverage: {coverage}")
```

Replace it with:

```python
    _mode = extractor.get("extraction_mode")
    _mode_label = {"two_pass": "two-pass", "single_pass": "single-pass (fallback)"}.get(_mode, "unknown")
    _coverage_conf = {"two_pass": "high", "single_pass": "low"}.get(_mode, "unknown")
    lines.append(f"- Verified clauses: **{len(verified)}**")
    lines.append(f"- Flagged clauses (failed verification): **{len(flagged)}**")
    lines.append(f"- Extraction mode: {_mode_label}")
    lines.append(f"- Coverage confidence: {_coverage_conf}")
```

- [ ] **Step 2: Verify the report renders the new lines (inline check)**

Run (single line):

```bash
python -c "import os; from pathlib import Path; from utils.report_generator import generate_report; d=Path('output/_rptcheck'); os.makedirs(d, exist_ok=True); r={'policy_name':'demo','finalizer_output':{'overall_label':'Compliant','confidence':'high'},'evaluator_output':{},'extractor_output':{'extraction_mode':'single_pass'},'final_reflector_output':{},'agent_models':{},'verified_clauses':[1,2],'flagged_clauses':[],'label_panel':{},'run_metadata':{}}; p=d/'r.md'; generate_report(r,p); t=p.read_text(encoding='utf-8'); assert '- Extraction mode: single-pass (fallback)' in t, t; assert '- Coverage confidence: low' in t; print('report OK')"
```

Expected output: `report OK`.

- [ ] **Step 3: Clean up the throwaway dir**

```bash
python -c "import shutil; shutil.rmtree('output/_rptcheck', ignore_errors=True); print('cleaned')"
```

- [ ] **Step 4: Commit**

```bash
git add utils/report_generator.py
git commit -m "feat: report extraction mode + coverage confidence (replaces Coverage line)"
```

---

## Task 4: End-to-end (offline) verification

**Files:** none (verification only)

Drives the real `save_result` with two synthetic results — one `two_pass`, one `single_pass` — to confirm the report lines and the index `coverage` column together, with no API cost.

- [ ] **Step 1: Drive `save_result` for both modes and assert report + index**

Run (single line):

```bash
python -c "import os, csv; from pathlib import Path; import main; d=Path('output/_covcheck'); os.makedirs(d, exist_ok=True); base={'agent_models':{},'verified_clauses':[1,2,3],'flagged_clauses':[],'evaluator_output':{},'final_reflector_output':{'agreement_rate':0.9},'finalizer_output':{'overall_label':'Compliant','confidence':'high'},'label_panel':{'disputed_count':0,'anchoring_summary':None},'retry_count':0,'policy_name':'demo'}; cfg={'20260610T090000Z':('2026-06-10T09:00:00Z','two_pass'),'20260610T093000Z':('2026-06-10T09:30:00Z','single_pass')}; [main.save_result({**base,'extractor_output':{'extraction_mode':cfg[rid][1]},'run_metadata':{'run_id':rid,'utc_timestamp':cfg[rid][0],'policy_file':'p.txt','policy_sha256':'abcd1234','git_commit':{'sha':'bae249d','dirty':False},'clause_count':3,'blind_enabled':True}}, d, run_index=1) for rid in ('20260610T090000Z','20260610T093000Z')]; rows=list(csv.reader(open(d/'runs_index.csv',encoding='utf-8'))); hdr=rows[0]; ci=hdr.index('coverage'); top=rows[1]; bot=rows[2]; print('coverage col idx:', ci); print('top:', top[0], top[ci]); print('bot:', bot[0], bot[ci]); assert hdr.index('coverage')==8; assert top[0]=='20260610T093000Z' and top[ci]=='low'; assert bot[0]=='20260610T090000Z' and bot[ci]=='high'; r1=(d/'demo_20260610T090000Z_report.md').read_text(encoding='utf-8'); assert '- Extraction mode: two-pass' in r1 and '- Coverage confidence: high' in r1; print('PASS: index coverage high/low + report lines correct')"
```

Expected: `coverage col idx: 8`, top run `...093000Z low`, bottom run `...090000Z high`, and `PASS: index coverage high/low + report lines correct`.

- [ ] **Step 2: Clean up the throwaway dir (output/ is gitignored)**

```bash
python -c "import shutil; shutil.rmtree('output/_covcheck', ignore_errors=True); print('cleaned')"
```

- [ ] **Step 3: Final commit (marker, allow empty)**

```bash
git add -A
git commit -m "test: verify extraction_mode + coverage column end-to-end (offline)" --allow-empty
```

> `output/` is gitignored, so `git add -A` should stage nothing from it. If it would stage any unexpected non-output file (e.g. `.claude/settings.local.json`), do NOT commit that file — unstage it with `git restore --staged <file>` first, then commit empty.

---

## Notes for the implementer

- **No pytest in this repo.** Run test files directly with `python tests/<file>.py`; they print `OK` on success.
- **The two-pass test depends on coverage:** the crafted policy's single content paragraph must equal the returned clause `quote` (so the self-check finds it covered and makes no further LLM calls). Do not alter `_PARAGRAPH` or the clause `quote` independently — keep them identical.
- **`extraction_mode` is set in exactly two places** in `agents/extractor.py` (two-pass result dict; `_run_single_pass` before return). Do not add logic branches.
- **`FIELDS` is the single source of column order** — `build_index_row` keys, the CSV header, and (positionally) `MD_HEADERS` all follow it. All three now have 15 entries with `coverage` after `clauses`.
- **Coverage values:** `high` (two_pass) / `low` (single_pass) / `—` (EM_DASH, unknown). These express coverage *confidence*, not a verified guarantee.
- **Do not touch** prompts, the retry loop, the scout/section logic, or run filenames.
