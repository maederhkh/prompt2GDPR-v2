# Execution Timeline Trace — Design Spec

**Date:** 2026-06-25
**Status:** Awaiting user review
**Scope:** Add a per-run **execution timeline** — a chronological record of every pipeline step (which stage ran, in what order, how long it took, which model, and its status: ok / fallback / retry / error). Surfaced both as a new `run_trace` array in the run JSON and as an "Execution Timeline" section in the human `report.md`. Captured at the orchestration layer (`main.py`); no agent-internal or prompt changes.

---

## 1. Goal

Today a run's JSON shows the **final state of each stage** (extractor output, evaluator verdicts, merged reflectors, finalizer label) and the cumulative `model_usage_log.md` shows *which model* each agent used. What no artifact shows is **how the run unfolded over time**:

- the order stages fired, and whether any ran more than once;
- how long each stage took (where the wall-clock goes);
- whether the **reflector retry loop** fired, how many attempts, and what it re-ran;
- whether Agent 1 fell back to **single-pass extraction** (no Scout) — currently near-invisible;
- whether a stage raised an error before the run ended.

The execution timeline answers *"what happened, in what order, how long, and what went wrong"* — the temporal dimension missing from the final-state JSON. It complements, and does not duplicate, `run_metadata` (provenance) and `model_usage_log.md` (model-per-agent).

## 2. Background — what already exists (and is reused)

- **`main.py` → `run_pipeline(client, policy_path, agent_models, blind_enabled)`** orchestrates every stage sequentially: extractor (Agent 1) → verifier → evaluator (Agent 2) → reflector A + reflector B → merge → blind A/B + label panel → (retry loop) → finalizer (Agent 4). It already assembles the result dict that `save_result` writes to JSON and feeds to `generate_report`.
- **`utils/run_metadata.py`** stamps provenance (`run_id`, UTC timestamp, git commit, policy SHA-256, temperature, flags). The trace sits alongside it — provenance is "what produced this", the trace is "how it ran".
- **`utils/report_generator.py`** — `generate_report(result, out_path)` builds markdown by appending to a `lines` list. The recently-added `_render_scout_section(scout_report) -> list[str]` pure helper is the **pattern this feature mirrors**: a pure renderer returning `[]` when there's nothing to show, wired in with `lines.extend(...)`.
- **Single-pass fallback signal:** `run_extractor` produces **no `scout_report` key** when it falls back to single-pass extraction. `main.py` can therefore detect a fallback *after the call returns* — without touching `extractor.py`.
- **The retry loop** (`main.py:189-248`) re-runs Agent 1 and/or Agent 2 (up to `MAX_RETRIES = 2`), then both reflectors and a merge, per attempt. This is the most valuable thing to make visible.
- **Tests** are standalone assert scripts (`tests/test_*.py`, run as `python tests/<file>.py`, print `OK`, exit non-zero on failure); CI auto-discovers them via the `tests/test_*.py` glob.

## 3. Feature design

### 3.1 Files

| File | Action | Responsibility |
|---|---|---|
| `utils/run_trace.py` | Create | `RunTrace` recorder: a context manager that times each step and records an event list. Pure, injectable clock, offline-testable. |
| `main.py` | Modify | Instantiate a `RunTrace`, wrap each stage call with `trace.step(...)`, mark the fallback/retry status, attach `result["run_trace"] = trace.events`. |
| `utils/report_generator.py` | Modify | Add a pure `_render_trace_section(run_trace) -> list[str]` helper; call it in `generate_report`. |
| `tests/test_run_trace.py` | Create | Unit tests for `RunTrace` (timing via fake clock, ordering, status transitions, error capture). |
| `tests/test_report_trace_section.py` | Create | Unit tests for `_render_trace_section` (table, escaping, empty/missing → `[]`). |

No change to agents, prompts, evaluation, `run_metadata`, the runs index, or the batch comparison.

### 3.2 The recorder — `utils/run_trace.py`

A small, dependency-free class that records one event per pipeline step.

```python
class RunTrace:
    def __init__(self, clock=time.perf_counter): ...
    def step(self, stage: str, model: str | None = None) -> "context manager"
    def mark_last(self, *, status: str | None = None, note: str | None = None) -> None
    @property
    def events(self) -> list[dict]
```

- **`step(stage, model=None)`** returns a context manager that:
  - records the start time on enter;
  - on **clean exit**, appends an event with `status="ok"` and the measured `duration_s`;
  - on **exception**, appends the event with `status="error"` and a `note` carrying the exception type/message, then **re-raises** (the orchestrator's existing error handling is unchanged).
- **`mark_last(status=, note=)`** lets the orchestrator override the just-recorded event's status/note — used to relabel the extractor step as `fallback` when `scout_report` is absent, and to tag retry re-runs.
- **`events`** is the ordered list of event dicts. Each event:

  ```python
  {
    "step":       int,            # 1-based sequence number
    "stage":      str,            # "extractor", "verifier", "evaluator",
                                  # "reflector_a", "reflector_b", "merge",
                                  # "blind_a", "blind_b", "label_panel",
                                  # "finalizer", or a retry variant (see §3.4)
    "model":      str | None,     # model slug, or None for non-LLM steps
    "duration_s": float,          # wall-clock seconds, rounded to 3 dp
    "status":     str,            # "ok" | "fallback" | "retry" | "error"
    "note":       str,            # short free text ("" when nothing to add)
  }
  ```

- **Injectable clock.** The default is `time.perf_counter`; tests pass a fake clock (a callable returning scripted increasing values) so durations are deterministic and **no real time or LLM call is involved**.
- **Pure & isolated.** `RunTrace` holds only its event list; it performs no I/O and knows nothing about the pipeline's data.

### 3.3 Granularity (a deliberate scoping decision — please confirm)

The trace records steps at the **granularity `main.py` can see** — one event per stage the orchestrator invokes. Specifically:

- Agent 1 is recorded as a **single `extractor` event** covering the whole call (Scout + Deep Extractor + Self-Check happen *inside* `run_extractor`; main.py does not see them separately). The fallback case is still surfaced via the `fallback` status (§3.4).
- Non-LLM steps (`verifier`, `merge`, `label_panel`) **are** recorded, with `model=None`, so the timeline is complete and honest about where time goes.

**Out of scope (possible follow-ups):** instrumenting inside `extractor.py` to time Scout vs. Deep vs. Self-Check separately; capturing **token/cost** per call (would require plumbing usage out of every agent — far more invasive). These are explicitly deferred.

### 3.4 Status semantics

- **`ok`** — stage completed normally.
- **`fallback`** — set on the `extractor` event (via `mark_last`) when the returned `extractor_output` has **no `scout_report` key**, i.e. Agent 1 used single-pass extraction. Note: `"single-pass fallback (no Scout)"`.
- **`retry`** — set on every stage re-run inside the retry loop. Retry events use stage names suffixed with the attempt, e.g. `extractor (retry 1)`, `evaluator (retry 1)`, `reflector_a (retry 1)`, `reflector_b (retry 1)`, `merge (retry 1)`. The `note` carries the trigger, e.g. `"re-run: 2 Agent-1 error(s)"`.
- **`error`** — set automatically when a step raises. In single-policy mode an unhandled exception still exits before `save_result` (so the trace is not persisted) — that is unchanged and acceptable; the trace's value is in successful and retrying runs. (Persisting partial traces on hard failure is out of scope.)

### 3.5 Wiring into `main.py`

- Instantiate `trace = RunTrace()` at the top of `run_pipeline`.
- Wrap each stage call in `with trace.step("<stage>", model=...):`. The variable assigned inside the `with` escapes normally (no new scope), so existing code is unchanged apart from indentation.
- Immediately after the first extractor step: `if "scout_report" not in extractor_output: trace.mark_last(status="fallback", note="single-pass fallback (no Scout)")`.
- Inside the retry loop, wrap each re-run with a retry-suffixed stage name and `trace.mark_last(status="retry", note=...)`.
- Add `"run_trace": trace.events` to **both** the normal result dict and `_empty_result` (the empty-result early return should still carry the trace built up to that point — extractor + verifier).

This is additive: a **new top-level `run_trace` JSON key**. Unlike the scout-report feature (pure rendering, no JSON change), adding trace data to the JSON is the *point* of this feature and is in scope. No existing key changes; any consumer that ignores `run_trace` is unaffected.

### 3.6 The renderer — `_render_trace_section(run_trace) -> list[str]`

A module-level pure helper in `utils/report_generator.py`, mirroring `_render_scout_section`:

1. **Guard.** If `run_trace` is falsy (`None`, `[]`), return `[]` — older runs and any run without a trace render exactly as today.
2. **Heading + summary.** Emit `## Execution Timeline`, a blank line, then a one-line summary: total steps, total duration (sum of `duration_s`), and counts of any non-`ok` statuses (e.g. `1 fallback`, `4 retry`). Blank line.
3. **Table.** Header `| # | Stage | Model | Duration (s) | Status | Note |` + separator, one row per event in recorded order.
   - `Model` shows the slug, or `—` when `None`.
   - Every free-text cell (`stage`, `model`, `note`) passes through the same pipe/newline sanitizer used by `_render_scout_section` (`|` → `\|`, `\r`/`\n` → space) so model slugs or notes can't break the table.
4. Trailing blank line.

Wired into `generate_report` with `lines.extend(_render_trace_section(result.get("run_trace")))`, placed at the **end of the report**, after the last existing section. It appends only; it must not alter any existing section's output.

## 4. What it deliberately does NOT do

- **No agent-internal timing** (Scout/Deep/Self-Check sub-steps) — orchestration granularity only.
- **No token or cost capture** — deferred; would require changing every agent's return contract.
- **No change** to `run_metadata`, the runs index, `model_usage_log.md`, the batch comparison, agents, prompts, or evaluation.
- **No persistence of partial traces on hard crash** in single-policy mode (process exits before save, as today).
- **No new CLI flag** — the trace is always recorded (cheap: just timing) and always rendered when present.

## 5. Testing / verification

Offline, no API key — consistent with the existing suite and CI.

- **`tests/test_run_trace.py`** (standalone assert script) drives `RunTrace` with a **fake clock**:
  1. Two sequential `step(...)` blocks produce two events with correct `step` numbers (1, 2), the injected durations, `status="ok"`, and the given `stage`/`model`.
  2. `mark_last(status="fallback", note=...)` overrides only the most recent event.
  3. A `step(...)` block whose body raises records `status="error"` with the exception in `note` **and** re-raises (assert via `try/except`).
  4. `model=None` is preserved in the event (non-LLM step).
- **`tests/test_report_trace_section.py`** (standalone assert script) asserts:
  1. A trace with several events renders the `## Execution Timeline` heading, the summary line with correct totals, the table header, and one row per event in order.
  2. A `None` model renders as `—`.
  3. A `note`/`stage` containing `|` and a newline is escaped (`\|`, no raw line break); row count matches event count.
  4. `_render_trace_section(None)` and `_render_trace_section([])` both return `[]`.

No test invokes `main.py`'s real pipeline or any LLM. Each script prints `OK` on success via its `__main__` block; failure raises and exits non-zero. CI auto-discovers both via the existing glob.

## 6. Out of scope

- Per-agent-pass timing inside `extractor.py`.
- Token / cost accounting.
- A separate `*_trace.md` file (the timeline lives as a section in the existing `report.md`).
- Any change to how stages decide their results.
- Surfacing the trace in the cumulative runs index or batch comparison.
