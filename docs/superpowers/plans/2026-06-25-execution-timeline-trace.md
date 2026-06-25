# Execution Timeline Trace — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record a per-run execution timeline (one event per pipeline stage: order, duration, model, status) and surface it both as a `run_trace` array in the run JSON and as an "Execution Timeline" section in the human `report.md`.

**Architecture:** A pure, dependency-free `RunTrace` recorder (`utils/run_trace.py`) wraps each stage call in `main.py` via a context manager that times the block and records an event. A pure `_render_trace_section` helper in `utils/report_generator.py` renders those events as a markdown table, mirroring the existing `_render_scout_section`. `main.py` attaches `trace.events` to the result dict.

**Tech Stack:** Python 3.12, standard library only. Tests are standalone assert scripts. Dev machine is Windows + PowerShell (chain with `;`, never `&&`).

## Global Constraints

- **Offline only.** No LLM/network/API key in any automated test. Do NOT run `main.py`'s real pipeline in any test (it needs `OPENROUTER_API_KEY`).
- Tests are **standalone assert scripts** (NOT pytest): each `tests/test_*.py` adds the repo root to `sys.path`, defines `test_*()` functions, and a `__main__` block that calls them and prints `OK`; any failure raises and exits non-zero. Run a suite with `python tests/<file>.py`.
- **The only JSON change permitted is the additive top-level `run_trace` key.** No existing JSON key changes. No change to `run_metadata`, the runs index, `model_usage_log.md`, the batch comparison, agents, prompts, or evaluation.
- **No existing report section changes.** The new "Execution Timeline" section is appended at the very end of the report. Runs without a `run_trace` (older runs, empty traces) must render exactly as they do today — the section is silently omitted.
- **No new CLI flag.** The trace is always recorded (timing only) and always rendered when present.
- `docs/` is gitignored. `utils/`, `tests/`, `main.py` are NOT gitignored and stage normally.
- Do NOT commit `.claude/settings.local.json` or anything under `.superpowers/`. Only `git add` the exact files named in each commit step (never `git add -A`).

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `utils/run_trace.py` | Create | `RunTrace` recorder: context manager that times each step and records an event list. Pure, injectable clock. |
| `tests/test_run_trace.py` | Create | Unit tests for `RunTrace`. |
| `utils/report_generator.py` | Modify | Add pure `_render_trace_section(run_trace)` helper; call it at the end of `generate_report`. |
| `tests/test_report_trace_section.py` | Create | Unit tests for `_render_trace_section`. |
| `main.py` | Modify | Instantiate `RunTrace`, wrap each stage with `trace.step(...)`, tag fallback/retry, attach `run_trace` to both result dicts; extend `_empty_result`. |

**Event shape** (produced by Task 1, consumed by Tasks 2 and 3) — every event is a dict:

```python
{
  "step":       int,            # 1-based sequence number
  "stage":      str,            # "extractor", "verifier", "evaluator", "reflector_a",
                                # "reflector_b", "merge", "blind_a", "blind_b",
                                # "label_panel", "finalizer", or a retry variant
  "model":      str | None,     # model slug, or None for non-LLM steps
  "duration_s": float,          # wall-clock seconds, rounded to 3 dp
  "status":     str,            # "ok" | "fallback" | "retry" | "error"
  "note":       str,            # short free text ("" when nothing to add)
}
```

---

## Task 1: `RunTrace` recorder

**Files:**
- Create: `utils/run_trace.py`
- Test: `tests/test_run_trace.py`

**Interfaces:**
- Consumes: nothing (pure stdlib).
- Produces:
  - `RunTrace(clock=time.perf_counter)` — recorder.
  - `RunTrace.step(stage: str, model: str | None = None)` — context manager; times the block, appends one event (status `"ok"` on clean exit; `"error"` + exception note on exception, then re-raises).
  - `RunTrace.mark_last(*, status: str | None = None, note: str | None = None) -> None` — override the most recent event's status/note.
  - `RunTrace.events -> list[dict]` — the ordered event list (shape above).

- [ ] **Step 1: Write the failing test**

Create `tests/test_run_trace.py`:

```python
"""Standalone assert tests for the RunTrace execution-timeline recorder."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.run_trace import RunTrace


class FakeClock:
    """Deterministic clock: returns scripted increasing values, one per call."""
    def __init__(self, values):
        self._it = iter(values)

    def __call__(self):
        return next(self._it)


def test_two_steps_record_order_durations_status():
    # step() calls the clock twice (start, end): two steps -> four values.
    trace = RunTrace(clock=FakeClock([0.0, 2.0, 2.0, 5.0]))
    with trace.step("extractor", model="m1"):
        pass
    with trace.step("verifier"):
        pass
    events = trace.events
    assert len(events) == 2, events
    assert events[0]["step"] == 1 and events[1]["step"] == 2
    assert events[0]["stage"] == "extractor" and events[0]["model"] == "m1"
    assert events[0]["duration_s"] == 2.0, events[0]
    assert events[1]["stage"] == "verifier" and events[1]["duration_s"] == 3.0
    assert events[0]["status"] == "ok" and events[1]["status"] == "ok"


def test_mark_last_overrides_only_latest():
    trace = RunTrace(clock=FakeClock([0.0, 1.0, 1.0, 2.0]))
    with trace.step("extractor", model="m1"):
        pass
    trace.mark_last(status="fallback", note="single-pass fallback (no Scout)")
    with trace.step("verifier"):
        pass
    events = trace.events
    assert events[0]["status"] == "fallback"
    assert events[0]["note"] == "single-pass fallback (no Scout)"
    assert events[1]["status"] == "ok" and events[1]["note"] == ""


def test_step_records_error_and_reraises():
    trace = RunTrace(clock=FakeClock([0.0, 4.0]))
    raised = False
    try:
        with trace.step("evaluator", model="m2"):
            raise ValueError("boom")
    except ValueError:
        raised = True
    assert raised, "step() must re-raise the body's exception"
    events = trace.events
    assert len(events) == 1
    assert events[0]["status"] == "error"
    assert "ValueError" in events[0]["note"] and "boom" in events[0]["note"]
    assert events[0]["duration_s"] == 4.0


def test_non_llm_step_has_none_model():
    trace = RunTrace(clock=FakeClock([0.0, 0.5]))
    with trace.step("merge"):
        pass
    assert trace.events[0]["model"] is None
    assert trace.events[0]["duration_s"] == 0.5


if __name__ == "__main__":
    test_two_steps_record_order_durations_status()
    test_mark_last_overrides_only_latest()
    test_step_records_error_and_reraises()
    test_non_llm_step_has_none_model()
    print("OK")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_run_trace.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'utils.run_trace'` (or `ImportError`).

- [ ] **Step 3: Implement `RunTrace`**

Create `utils/run_trace.py`:

```python
"""
Per-run execution-timeline recorder.

RunTrace records one event per pipeline stage: its order, wall-clock duration,
the model used (or None for non-LLM steps), and a status (ok / fallback /
retry / error). The orchestrator wraps each stage call in `with trace.step(...)`.
Pure: no I/O, no knowledge of pipeline data. The clock is injectable so the
recorder is deterministically unit-testable offline.
"""

import time
from contextlib import contextmanager


class RunTrace:
    def __init__(self, clock=time.perf_counter):
        self._clock = clock
        self._events = []

    @contextmanager
    def step(self, stage: str, model=None):
        """
        Time a pipeline stage and record one event.

        Appends the event on entry (so its step number is stable and it is
        recorded even if the body raises). On clean exit: status "ok". On
        exception: status "error" with the exception in the note, then
        re-raises so the orchestrator's existing error handling is unchanged.
        """
        start = self._clock()
        event = {
            "step": len(self._events) + 1,
            "stage": stage,
            "model": model,
            "duration_s": 0.0,
            "status": "ok",
            "note": "",
        }
        self._events.append(event)
        try:
            yield
        except BaseException as exc:
            event["duration_s"] = round(self._clock() - start, 3)
            event["status"] = "error"
            event["note"] = f"{type(exc).__name__}: {exc}"
            raise
        else:
            event["duration_s"] = round(self._clock() - start, 3)

    def mark_last(self, *, status=None, note=None) -> None:
        """Override the most recent event's status and/or note. No-op if empty."""
        if not self._events:
            return
        if status is not None:
            self._events[-1]["status"] = status
        if note is not None:
            self._events[-1]["note"] = note

    @property
    def events(self) -> list:
        """The ordered list of recorded event dicts."""
        return self._events
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python tests/test_run_trace.py`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add utils/run_trace.py tests/test_run_trace.py
git commit -m "feat: add RunTrace execution-timeline recorder"
```

---

## Task 2: Render the Execution Timeline section

**Files:**
- Modify: `utils/report_generator.py`
- Test: `tests/test_report_trace_section.py`

**Interfaces:**
- Consumes: a `run_trace` list of event dicts (shape in the File Map) — or `None`.
- Produces: `_render_trace_section(run_trace) -> list` — a module-level pure function returning markdown lines (empty list when nothing to show). Called by `generate_report`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_report_trace_section.py`:

```python
"""Standalone assert tests for _render_trace_section in the report generator."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.report_generator import _render_trace_section


def _trace():
    return [
        {"step": 1, "stage": "extractor", "model": "llama-3.3-70b",
         "duration_s": 16.8, "status": "fallback", "note": "single-pass fallback (no Scout)"},
        {"step": 2, "stage": "verifier", "model": None,
         "duration_s": 0.3, "status": "ok", "note": ""},
        {"step": 3, "stage": "evaluator", "model": "gpt-4o-mini",
         "duration_s": 14.6, "status": "ok", "note": ""},
    ]


def test_full_trace_has_heading_summary_and_one_row_per_event():
    lines = _render_trace_section(_trace())
    text = "\n".join(lines)
    assert "## Execution Timeline" in text, text
    assert "| # | Stage | Model | Duration (s) | Status | Note |" in text, text
    assert "3 steps" in text, text          # total step count in summary
    assert "31.7" in text, text             # total duration 16.8+0.3+14.6
    assert "1 fallback" in text, text       # non-ok status surfaced in summary
    # one data row per event
    assert text.count("| extractor |") == 1
    assert text.count("| verifier |") == 1
    assert text.count("| evaluator |") == 1


def test_none_model_renders_dash():
    lines = _render_trace_section(_trace())
    # the verifier row (step 2) has model None -> em dash cell
    verifier_row = [ln for ln in lines if ln.startswith("| 2 |")][0]
    assert "| — |" in verifier_row, verifier_row


def test_pipe_and_newline_in_cells_are_escaped():
    trace = [
        {"step": 1, "stage": "evaluator", "model": "a|b",
         "duration_s": 1.0, "status": "ok", "note": "line1\nline2 | piped"},
    ]
    lines = _render_trace_section(trace)
    text = "\n".join(lines)
    assert "line1 line2 \\| piped" in text, text
    assert "a\\|b" in text, text
    data_rows = [ln for ln in lines if ln.startswith("| 1 |")]
    assert len(data_rows) == 1, data_rows


def test_empty_or_missing_trace_returns_empty_list():
    assert _render_trace_section(None) == []
    assert _render_trace_section([]) == []


if __name__ == "__main__":
    test_full_trace_has_heading_summary_and_one_row_per_event()
    test_none_model_renders_dash()
    test_pipe_and_newline_in_cells_are_escaped()
    test_empty_or_missing_trace_returns_empty_list()
    print("OK")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_report_trace_section.py`
Expected: FAIL with `ImportError: cannot import name '_render_trace_section'`.

- [ ] **Step 3: Implement `_render_trace_section`**

In `utils/report_generator.py`, add this module-level function directly **below** the existing `_render_scout_section` function (i.e. after its `return lines` on line 53, before `def generate_report`):

```python
def _render_trace_section(run_trace) -> list:
    """
    Render the Execution Timeline section from a run_trace event list.

    Returns a list of markdown lines, or [] when there is nothing to show
    (run_trace is None/empty). Pure: writes nothing and does not mutate input.

    Each event: {"step": int, "stage": str, "model": str|None,
                 "duration_s": float, "status": str, "note": str}
    """
    if not run_trace:
        return []

    def _cell(value) -> str:
        # Sanitize a free-text cell so it can't break the markdown table.
        return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")

    total_steps = len(run_trace)
    total_duration = sum((e.get("duration_s") or 0) for e in run_trace)

    non_ok_counts = {}
    for e in run_trace:
        status = e.get("status", "ok")
        if status != "ok":
            non_ok_counts[status] = non_ok_counts.get(status, 0) + 1
    non_ok = ", ".join(f"{n} {s}" for s, n in non_ok_counts.items())

    summary = f"- {total_steps} steps, **{total_duration:.3f}s** total"
    if non_ok:
        summary += f" — {non_ok}"

    lines = [
        "## Execution Timeline",
        "",
        summary,
        "",
        "| # | Stage | Model | Duration (s) | Status | Note |",
        "|---|---|---|---|---|---|",
    ]
    for e in run_trace:
        model = e.get("model")
        model_cell = _cell(model) if model else "—"
        lines.append(
            f"| {e.get('step', '?')} | {_cell(e.get('stage', ''))} | {model_cell} "
            f"| {e.get('duration_s', 0):.3f} | {_cell(e.get('status', ''))} "
            f"| {_cell(e.get('note', ''))} |"
        )
    lines.append("")
    return lines
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python tests/test_report_trace_section.py`
Expected: `OK`.

- [ ] **Step 5: Wire it into `generate_report`**

In `utils/report_generator.py`, the report currently ends with the Label-Panel block whose final statement is `lines.append(f"")`, immediately followed by the write-file block:

```python
        lines.append(f"")

    # -----------------------------------------------------------------------
    # Write file
    # -----------------------------------------------------------------------
    out_path.write_text("\n".join(lines), encoding="utf-8")
```

Insert the trace-section call right before the `# Write file` comment block, so it reads:

```python
        lines.append(f"")

    lines.extend(_render_trace_section(result.get("run_trace")))

    # -----------------------------------------------------------------------
    # Write file
    # -----------------------------------------------------------------------
    out_path.write_text("\n".join(lines), encoding="utf-8")
```

(`result` is the `generate_report` parameter; `run_trace` is read directly off it. Note the insertion is at the function's outer indentation level — one level less than the `lines.append(f"")` inside the Label-Panel `if` block.)

- [ ] **Step 6: Confirm the report still builds with no run_trace and existing tests pass**

A result with no `run_trace` must add no Execution Timeline section:

```powershell
python -c "import os; from pathlib import Path; from utils.report_generator import generate_report; p=Path(os.environ['TEMP'])/'._trace_plan_check.md'; generate_report({'extractor_output': {}, 'finalizer_output': {}, 'evaluator_output': {}}, p); t=p.read_text(encoding='utf-8'); print('NO TIMELINE' if 'Execution Timeline' not in t else 'UNEXPECTED SECTION'); p.unlink()"
```
Expected: `NO TIMELINE`.

Then re-run all offline suites:

```powershell
Get-ChildItem tests/test_*.py | ForEach-Object { Write-Host "=== $($_.Name) ==="; python $_.FullName; if ($LASTEXITCODE -ne 0) { throw "FAILED: $($_.Name)" } }
```
Expected: every suite prints `OK`; no `FAILED:` thrown.

- [ ] **Step 7: Commit**

```bash
git add utils/report_generator.py tests/test_report_trace_section.py
git commit -m "feat: render execution timeline section in the human report"
```

---

## Task 3: Wire `RunTrace` into the pipeline

**Files:**
- Modify: `main.py`

**Interfaces:**
- Consumes: `RunTrace` (Task 1) and `_render_trace_section` (Task 2, already wired into `generate_report`).
- Produces: `result["run_trace"]` — the event list — on both the normal and empty-result return paths.

This task has **no offline unit test** (it drives the real LLM pipeline, which the Global Constraints forbid running in tests — consistent with the existing suite, which never tests `run_pipeline`). It is verified by an import smoke-test plus the full existing suite, and by code review of the wiring. Follow the edits exactly.

- [ ] **Step 1: Add the import**

In `main.py`, next to the other `utils` imports (e.g. after `from utils.run_metadata import build_run_metadata`), add:

```python
from utils.run_trace import RunTrace
```

- [ ] **Step 2: Instantiate the trace at the top of `run_pipeline`**

In `run_pipeline`, just after `policy_text = load_policy_text(policy_path)`, add:

```python
    trace = RunTrace()
```

- [ ] **Step 3: Wrap the Extractor (Step 1) and tag fallback**

Replace the existing extractor call:

```python
    extractor_output = run_extractor(
        client, policy_name, policy_text,
        model=agent_models["extractor"],
        scout_model=agent_models["scout"],
    )
```

with:

```python
    with trace.step("extractor", model=agent_models["extractor"]):
        extractor_output = run_extractor(
            client, policy_name, policy_text,
            model=agent_models["extractor"],
            scout_model=agent_models["scout"],
        )
    if "scout_report" not in extractor_output:
        trace.mark_last(status="fallback", note="single-pass fallback (no Scout)")
```

- [ ] **Step 4: Wrap the Verifier (Step 2)**

Replace:

```python
    verified_clauses, flagged_clauses = verify_clauses(
        extractor_output.get("extracted_clauses", []),
        policy_text,
    )
```

with:

```python
    with trace.step("verifier"):
        verified_clauses, flagged_clauses = verify_clauses(
            extractor_output.get("extracted_clauses", []),
            policy_text,
        )
```

- [ ] **Step 5: Pass the trace into the empty-result early return**

The empty-result branch currently reads:

```python
    if not verified_clauses:
        print("  WARNING: No verified clauses. Pipeline cannot continue with evaluation.")
        return _empty_result(policy_name, extractor_output, flagged_clauses, run_metadata)
```

Change the return call to pass `trace.events`:

```python
    if not verified_clauses:
        print("  WARNING: No verified clauses. Pipeline cannot continue with evaluation.")
        return _empty_result(policy_name, extractor_output, flagged_clauses, run_metadata, trace.events)
```

- [ ] **Step 6: Wrap the Evaluator (Step 3)**

Replace:

```python
    evaluator_output = run_evaluator(client, verified_clauses, model=agent_models["evaluator"])
```

with:

```python
    with trace.step("evaluator", model=agent_models["evaluator"]):
        evaluator_output = run_evaluator(client, verified_clauses, model=agent_models["evaluator"])
```

- [ ] **Step 7: Wrap the two Reflectors and the merge (Step 4)**

Replace:

```python
    reflector_a_initial = run_reflector(
        client, verified_clauses, flagged_clauses, evaluator_output,
        model=agent_models["reflector_a"]
    )
```

with:

```python
    with trace.step("reflector_a", model=agent_models["reflector_a"]):
        reflector_a_initial = run_reflector(
            client, verified_clauses, flagged_clauses, evaluator_output,
            model=agent_models["reflector_a"]
        )
```

Replace:

```python
    reflector_b_initial = run_reflector(
        client, verified_clauses, flagged_clauses, evaluator_output,
        model=agent_models["reflector_b"]
    )
```

with:

```python
    with trace.step("reflector_b", model=agent_models["reflector_b"]):
        reflector_b_initial = run_reflector(
            client, verified_clauses, flagged_clauses, evaluator_output,
            model=agent_models["reflector_b"]
        )
```

Replace:

```python
    initial_reflector_output = merge_reflector_outputs(reflector_a_initial, reflector_b_initial)
```

with:

```python
    with trace.step("merge"):
        initial_reflector_output = merge_reflector_outputs(reflector_a_initial, reflector_b_initial)
```

- [ ] **Step 8: Wrap the Blind Labelers and the Label Panel**

Inside `if blind_enabled:`, replace:

```python
        blind_a_output = run_blind_labeler(
            client, verified_clauses, model=agent_models["blind_a"]
        )
```

with:

```python
        with trace.step("blind_a", model=agent_models["blind_a"]):
            blind_a_output = run_blind_labeler(
                client, verified_clauses, model=agent_models["blind_a"]
            )
```

and replace:

```python
        blind_b_output = run_blind_labeler(
            client, verified_clauses, model=agent_models["blind_b"]
        )
```

with:

```python
        with trace.step("blind_b", model=agent_models["blind_b"]):
            blind_b_output = run_blind_labeler(
                client, verified_clauses, model=agent_models["blind_b"]
            )
```

Then replace the label-panel build:

```python
    label_panel = build_label_panel(
        evaluator_output=evaluator_output,
        reflector_a=reflector_a_initial,
        reflector_b=reflector_b_initial,
        blind_a=blind_a_output,
        blind_b=blind_b_output,
        models=agent_models,
        blind_enabled=blind_enabled,
    )
```

with:

```python
    with trace.step("label_panel"):
        label_panel = build_label_panel(
            evaluator_output=evaluator_output,
            reflector_a=reflector_a_initial,
            reflector_b=reflector_b_initial,
            blind_a=blind_a_output,
            blind_b=blind_b_output,
            models=agent_models,
            blind_enabled=blind_enabled,
        )
```

- [ ] **Step 9: Wrap the retry-loop re-runs**

Inside the `for attempt in range(1, MAX_RETRIES + 1):` loop, wrap each re-run and tag it `retry`.

Replace the Agent-1 re-run block:

```python
            if agent1_errors:
                instructions = build_retry_instructions(agent1_errors)
                print(f"    Re-running Agent 1 ({len(agent1_errors)} error(s))...")
                extractor_output = run_extractor(
                    client, policy_name, policy_text,
                    model=agent_models["extractor"],
                    scout_model=agent_models["scout"],
                    retry_instructions=instructions,
                )
                verified_clauses, flagged_clauses = verify_clauses(
                    extractor_output.get("extracted_clauses", []), policy_text
                )
                retried = True
```

with:

```python
            if agent1_errors:
                instructions = build_retry_instructions(agent1_errors)
                print(f"    Re-running Agent 1 ({len(agent1_errors)} error(s))...")
                with trace.step(f"extractor (retry {attempt})", model=agent_models["extractor"]):
                    extractor_output = run_extractor(
                        client, policy_name, policy_text,
                        model=agent_models["extractor"],
                        scout_model=agent_models["scout"],
                        retry_instructions=instructions,
                    )
                trace.mark_last(status="retry", note=f"re-run: {len(agent1_errors)} Agent-1 error(s)")
                with trace.step(f"verifier (retry {attempt})"):
                    verified_clauses, flagged_clauses = verify_clauses(
                        extractor_output.get("extracted_clauses", []), policy_text
                    )
                trace.mark_last(status="retry")
                retried = True
```

Replace the Agent-2 re-run block:

```python
            if agent2_errors:
                instructions = build_retry_instructions(agent2_errors)
                print(f"    Re-running Agent 2 ({len(agent2_errors)} error(s))...")
                evaluator_output = run_evaluator(
                    client, verified_clauses,
                    model=agent_models["evaluator"], retry_instructions=instructions
                )
                retried = True
```

with:

```python
            if agent2_errors:
                instructions = build_retry_instructions(agent2_errors)
                print(f"    Re-running Agent 2 ({len(agent2_errors)} error(s))...")
                with trace.step(f"evaluator (retry {attempt})", model=agent_models["evaluator"]):
                    evaluator_output = run_evaluator(
                        client, verified_clauses,
                        model=agent_models["evaluator"], retry_instructions=instructions
                    )
                trace.mark_last(status="retry", note=f"re-run: {len(agent2_errors)} Agent-2 error(s)")
                retried = True
```

Replace the post-retry reflector + merge block:

```python
            if retried:
                ref_a = run_reflector(
                    client, verified_clauses, flagged_clauses, evaluator_output,
                    model=agent_models["reflector_a"]
                )
                ref_b = run_reflector(
                    client, verified_clauses, flagged_clauses, evaluator_output,
                    model=agent_models["reflector_b"]
                )
                final_reflector_output = merge_reflector_outputs(ref_a, ref_b)
                final_reflector_output["retry_count"] = attempt
                retry_count = attempt
```

with:

```python
            if retried:
                with trace.step(f"reflector_a (retry {attempt})", model=agent_models["reflector_a"]):
                    ref_a = run_reflector(
                        client, verified_clauses, flagged_clauses, evaluator_output,
                        model=agent_models["reflector_a"]
                    )
                trace.mark_last(status="retry")
                with trace.step(f"reflector_b (retry {attempt})", model=agent_models["reflector_b"]):
                    ref_b = run_reflector(
                        client, verified_clauses, flagged_clauses, evaluator_output,
                        model=agent_models["reflector_b"]
                    )
                trace.mark_last(status="retry")
                with trace.step(f"merge (retry {attempt})"):
                    final_reflector_output = merge_reflector_outputs(ref_a, ref_b)
                trace.mark_last(status="retry")
                final_reflector_output["retry_count"] = attempt
                retry_count = attempt
```

- [ ] **Step 10: Wrap the Finalizer (Step 5)**

Replace:

```python
    finalizer_output = run_finalizer(
        client=client,
        policy_name=policy_name,
        extractor_output=extractor_output,
        verified_clauses=verified_clauses,
        flagged_clauses=flagged_clauses,
        evaluator_output=evaluator_output,
        reflector_output=final_reflector_output,
        model=agent_models["finalizer"],
    )
```

with:

```python
    with trace.step("finalizer", model=agent_models["finalizer"]):
        finalizer_output = run_finalizer(
            client=client,
            policy_name=policy_name,
            extractor_output=extractor_output,
            verified_clauses=verified_clauses,
            flagged_clauses=flagged_clauses,
            evaluator_output=evaluator_output,
            reflector_output=final_reflector_output,
            model=agent_models["finalizer"],
        )
```

- [ ] **Step 11: Attach `run_trace` to the normal result dict**

In the big `return { ... }` dict at the end of `run_pipeline`, add a `run_trace` entry. Change the opening of the dict:

```python
    return {
        "run_metadata": run_metadata,
        "policy_name": policy_name,
```

to:

```python
    return {
        "run_metadata": run_metadata,
        "run_trace": trace.events,
        "policy_name": policy_name,
```

- [ ] **Step 12: Extend `_empty_result` to carry the trace**

Replace the whole `_empty_result` function:

```python
def _empty_result(policy_name: str, extractor_output: dict, flagged_clauses: list,
                  run_metadata: dict) -> dict:
    return {
        "run_metadata": run_metadata,
        "policy_name": policy_name,
        "error": "No verified clauses — all extracted clauses failed string-match verification.",
        "extractor_output": extractor_output,
        "flagged_clauses": flagged_clauses,
    }
```

with:

```python
def _empty_result(policy_name: str, extractor_output: dict, flagged_clauses: list,
                  run_metadata: dict, run_trace: list) -> dict:
    return {
        "run_metadata": run_metadata,
        "run_trace": run_trace,
        "policy_name": policy_name,
        "error": "No verified clauses — all extracted clauses failed string-match verification.",
        "extractor_output": extractor_output,
        "flagged_clauses": flagged_clauses,
    }
```

- [ ] **Step 13: Verify `main.py` imports cleanly (offline smoke test)**

This confirms the wiring has no syntax/indentation/import errors. It does NOT call the pipeline, so no API key is needed.

Run:

```powershell
python -c "import main; print('IMPORT OK')"
```
Expected: `IMPORT OK` (no traceback).

- [ ] **Step 14: Re-run all offline suites**

```powershell
Get-ChildItem tests/test_*.py | ForEach-Object { Write-Host "=== $($_.Name) ==="; python $_.FullName; if ($LASTEXITCODE -ne 0) { throw "FAILED: $($_.Name)" } }
```
Expected: every suite prints `OK`; no `FAILED:` thrown.

- [ ] **Step 15: Commit**

```bash
git add main.py
git commit -m "feat: record execution timeline across the pipeline"
```

Then run `git status --short` and confirm no unintended files are staged (only `main.py` in this commit; `.claude/settings.local.json` and `.superpowers/` must NOT appear as staged).

---

## Notes for the implementer

- **No pytest.** Run a suite directly: `python tests/<file>.py`; success prints `OK`, failure exits non-zero.
- **Offline only.** No network/LLM call; never invoke the real pipeline (`main()` / `run_pipeline`). Task 3 is verified by the import smoke test + the full suite, not by running the pipeline.
- **Pure helpers.** Both `RunTrace` and `_render_trace_section` perform no I/O; `_render_trace_section` returns `[]` when there is no trace, so older runs render exactly as before.
- **Additive JSON only.** The single JSON change is the new top-level `run_trace` key on both return paths. Do not alter any other key.
- **Only stage the files named in each commit step.** Do not commit `.claude/settings.local.json` or `.superpowers/`.
- **Indentation matters in `main.py`.** Wrapping a call in `with trace.step(...):` indents the wrapped statement one level; the variable it assigns still escapes the `with` block (no new scope), so downstream code is unchanged.
```
