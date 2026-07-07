# Per-Agent Token & Cost Capture — Design Spec

**Date:** 2026-07-07
**Status:** Awaiting user review
**Scope:** Capture, per pipeline run, the token usage and OpenRouter-reported cost of every LLM call — grouped by agent role and totalled for the run. Surfaced as an additive `token_usage` key in the run JSON, a "Token Usage & Cost" section in the human `report.md`, and two new columns (`total_tokens`, `cost_usd`) in the runs index. Capture happens at a single wrapped-client seam; the agents are not modified.

---

## 1. Goal

Today the pipeline records *which model* each agent used (`agent_models`, the report's "Models Used" section, the runs index) but never *how many tokens* a run consumed or *what it cost*. The data is already returned on every API response (`response.usage`) and simply discarded — each agent reads only `response.choices[0].message.content`.

This feature grabs that already-present usage data and OpenRouter's per-call cost, attributes it to the agent that ran, and surfaces per-agent subtotals plus a run grand total. It answers *"how many tokens and how much money did this run cost, and where did it go?"* — complementing `run_trace` (where the wall-clock time went) with where the tokens/cost went.

## 2. Background — what already exists (and is reused)

- **`main.py`** creates one client — `client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=...)` (main.py:501) — and passes it into `run_pipeline(client, ...)`, which hands it to every agent. Agents call `client.chat.completions.create(...)` directly (≈10 call sites across `agents/extractor.py`, `evaluator.py`, `reflector.py`, `blind_labeler.py`, `finalizer.py`) and read only `.choices[0].message.content`.
- **`run_trace` / `RunTrace`** (`utils/run_trace.py`, wired in `main.py`) already wraps each pipeline stage in `with trace.step("<stage>", model=...):`. This feature reuses those exact per-stage boundaries to know which agent is active when a call is made. `run_trace`'s orchestration-granularity decision (Agent 1 = one stage, its Scout/Deep/Self-Check sub-calls not separated) is mirrored here for attribution.
- **`utils/report_generator.py`** — `generate_report(result, out_path)` appends sections to a `lines` list. `_render_scout_section` and `_render_trace_section` are pure helpers returning `[]` when there is nothing to show, wired via `lines.extend(...)`. This feature adds a third such helper in the same style.
- **`utils/runs_index.py`** — one row per run, built from the result dict; `FIELDS` / `MD_HEADERS` / `build_index_row` share a field order; `EM_DASH = "—"` marks not-applicable values; the schema-mismatch path in `append_run_to_index` auto-backs-up an old index and starts fresh when `FIELDS` changes. The recently-added `duration_s` column is the pattern the two new columns mirror.
- **OpenRouter cost:** OpenRouter returns cost **inline** in the response's usage object when the request body includes `usage: {include: true}`. With the OpenAI SDK this is passed via `extra_body={"usage": {"include": True}}` per request. No separate cost-lookup network call is needed.
- **Graceful-degradation precedent:** `run_metadata` and `runs_index` never crash a run on failure. Usage capture follows the same rule.
- **Tests** are standalone assert scripts (`tests/test_*.py`, run as `python tests/<file>.py`, print `OK`, exit non-zero on failure); CI auto-discovers them. No test performs a network/LLM call.

## 3. Feature design

### 3.1 Files

| File | Action | Responsibility |
|---|---|---|
| `utils/usage_meter.py` | Create | `UsageMeter` (per-call record collector + `stage()` context manager + roll-up helpers) and `MeteredClient` (thin wrapper that injects the usage flag, records `response.usage`, and returns the response unchanged). Pure except for delegating to the wrapped client; offline-testable with a fake client. |
| `main.py` | Modify | Instantiate `UsageMeter`, wrap the real client with `MeteredClient`, pass the wrapped client to the agents, tag each stage via `meter.stage(...)`, and attach `result["token_usage"]` on both return paths. |
| `utils/report_generator.py` | Modify | Add a pure `_render_usage_section(token_usage) -> list` helper (mirrors `_render_trace_section`); call it in `generate_report`. |
| `utils/runs_index.py` | Modify | Add `total_tokens` and `cost_usd` to `FIELDS` / `MD_HEADERS`; compute both from `token_usage` in `build_index_row`. |
| `tests/test_usage_meter.py` | Create | Unit tests for `UsageMeter` + `MeteredClient` (fake client/response). |
| `tests/test_report_usage_section.py` | Create | Unit tests for `_render_usage_section`. |
| `tests/test_runs_index.py` | Modify | Assert the two new columns (with usage; `—` without). |

No change to any file under `agents/`, to prompts, evaluation, `run_metadata`, `run_trace`, `runs_summary.py`, or the batch comparison.

### 3.2 The meter — `utils/usage_meter.py`

**Per-call record** (one appended per API call):

```python
{
  "stage":             str,          # active agent/stage, e.g. "extractor", "evaluator"
  "model":             str | None,   # model slug from the call
  "prompt_tokens":     int,          # from response.usage
  "completion_tokens": int,
  "total_tokens":      int,
  "cost":              float | None, # OpenRouter cost (USD); None if not reported
}
```

**`UsageMeter`:**
- `stage(name)` — a context manager that sets the currently-active stage label; restores the previous label on exit (so nested/sequential stages are safe).
- Records are appended by `MeteredClient` under the active stage (or `None`/`"unknown"` if no stage is active — a call outside any stage still records, never crashes).
- `records -> list[dict]` — the ordered per-call list.
- `by_stage() -> list[dict]` — roll-up: one entry per stage in first-seen order, each `{stage, calls, prompt_tokens, completion_tokens, total_tokens, cost}`. `cost` is the sum of non-None costs, or `None` if the stage reported no cost at all.
- `totals() -> dict` — `{calls, prompt_tokens, completion_tokens, total_tokens, cost}` across all records (same cost rule).
- `to_dict() -> dict` — the object attached to the result: `{"calls": records, "by_stage": by_stage(), "totals": totals()}`.

**`MeteredClient`:**
- Constructed as `MeteredClient(inner_client, meter)`.
- Exposes `.chat.completions.create(**kwargs)` matching the OpenAI surface the agents use:
  1. merge `{"usage": {"include": True}}` into any caller-supplied `extra_body` (never clobber other extra_body keys);
  2. call `inner_client.chat.completions.create(**kwargs)`;
  3. read `response.usage` defensively — `getattr` each of `prompt_tokens`, `completion_tokens`, `total_tokens` (default 0) and `cost` (default `None`; OpenRouter may expose it as `usage.cost` or under `usage.cost_details` — read `cost` first, fall back to `None`);
  4. append the record under `meter`'s active stage, tagged with `kwargs.get("model")`;
  5. return the **unmodified** `response`.
- Any exception from the inner client propagates unchanged (existing agent error handling is preserved). A failure to *read* usage must not raise — a malformed/absent `usage` yields a zero/None record, not a crash.

The agents are untouched: they receive `MeteredClient` in place of the raw client and keep calling `.chat.completions.create(...)` and reading `.choices[0].message.content`.

### 3.3 Attribution granularity (a deliberate decision, consistent with `run_trace`)

Calls are attributed to the **active stage**, tagged by `meter.stage("<stage>")` around each stage in `main.py`. The extractor's internal Scout / Deep-Extract / Self-Check / Gap-Judge calls all record while the stage is `"extractor"`, so each is captured as its own per-call record (with its own model) but rolls up under `extractor`. Retries record under retry-suffixed stage names matching `run_trace` (e.g. `extractor (retry 1)`). We deliberately do **not** invent sub-call labels inside `extractor.py` — the same orchestration-granularity call made for the execution timeline. (Per-call sub-labels inside the extractor are a possible future follow-up.)

### 3.4 Wiring into `main.py`

- After creating the real `client`, create `meter = UsageMeter()` and `metered = MeteredClient(client, meter)`; pass `metered` wherever `client` is currently passed into the agents.
- Tag each stage with `meter.stage("<stage>")` using the same stage names and boundaries as `run_trace`. (Implementation detail for the plan: this can share the per-stage wrapping already present for `trace.step(...)`.)
- Attach `"token_usage": meter.to_dict()` to **both** the normal result dict and `_empty_result` (the early-return path carries whatever was recorded so far — extractor + verifier).

This is additive: a **new top-level `token_usage` JSON key**. No existing key changes; any consumer that ignores it is unaffected.

### 3.5 The report renderer — `_render_usage_section(token_usage) -> list`

A module-level pure helper in `utils/report_generator.py`, mirroring `_render_trace_section`:

1. **Guard.** If `token_usage` is falsy, or its `by_stage` is empty, return `[]` — older runs and any run without usage render exactly as today.
2. **Heading + summary.** `## Token Usage & Cost`, blank line, a one-line summary: total calls, total tokens, and total cost (`$X.XXXX`, or `—` if no cost reported). Blank line.
3. **Table.** Header `| Agent | Calls | Prompt | Completion | Total tokens | Cost (USD) |` + separator, one row per `by_stage` entry, then a final **`TOTAL`** row from `totals()`.
   - Token counts render with thousands separators for readability (e.g. `12,400`).
   - Cost renders as `$0.0180` (4 dp), or `—` when `None`.
   - Free-text cells (stage, model) pass through the same pipe/newline sanitizer used by the other sections.
4. Trailing blank line.

Wired with `lines.extend(_render_usage_section(result.get("token_usage")))`, placed after the Execution Timeline section at the end of `generate_report`. Appends only; alters no existing section.

### 3.6 Runs-index columns

- Append `"total_tokens"` and `"cost_usd"` to `FIELDS`, and `"Total tokens"` / `"Cost (USD)"` to `MD_HEADERS` (both after the existing `duration_s` / `Duration (s)`).
- In `build_index_row`, read `result.get("token_usage")`:
  - `total_tokens` = the run's `totals()["total_tokens"]` when present and non-zero, else `EM_DASH`.
  - `cost_usd` = the run's `totals()["cost"]` rounded to 4 dp when present (a number), else `EM_DASH`.
- The existing schema-migration path handles the header change automatically (backs up the old index, starts fresh) — no new migration code.

## 4. What it deliberately does NOT do

- **No per-sub-call labels inside `extractor.py`** (Scout/Deep/Self-Check are attributed to `extractor`) — orchestration granularity, matching `run_trace`.
- **No local price table** — cost comes only from OpenRouter's reported value; when OpenRouter does not report a cost, it renders `—` rather than being estimated.
- **No change** to any `agents/` file, prompts, evaluation, `run_metadata`, `run_trace`, `runs_summary.py`, or the batch comparison.
- **No new CLI flag** — usage is always captured (it is free on responses) and always rendered when present.
- **No budget/limit enforcement** — this is measurement only, not a spend cap.
- **No persistence of partial usage on a hard crash** in single-policy mode (process exits before save, as today).

## 5. Testing / verification

Offline, no API key — consistent with the existing suite and CI.

- **`tests/test_usage_meter.py`** (standalone assert script), using a **fake client** whose `.chat.completions.create(**kwargs)` returns a canned object with a `.usage` carrying scripted token/cost values (and asserts the `usage.include` flag was injected into the request):
  1. A call inside `meter.stage("evaluator")` records one entry tagged `stage="evaluator"` with the model and the fake usage numbers; the response is returned unchanged.
  2. Two calls under `stage("extractor")` (different models) roll up in `by_stage()` to one `extractor` entry with `calls == 2` and summed tokens/cost.
  3. `MeteredClient` merges `usage.include` into an existing `extra_body` without dropping the caller's other keys.
  4. A response whose `usage` lacks `cost` records `cost=None`; `by_stage`/`totals` treat it as no-cost (not zero-dollars) and don't crash.
  5. `totals()` sums across stages; `to_dict()` returns `{"calls", "by_stage", "totals"}`.
- **`tests/test_report_usage_section.py`** (standalone assert script):
  1. A `token_usage` with several stages renders the `## Token Usage & Cost` heading, the summary line, the table header, one row per stage, and a `TOTAL` row with correct sums.
  2. Costs render `$0.0180`-style; a `None` cost renders `—`.
  3. Token counts render with thousands separators.
  4. `_render_usage_section(None)` and an empty-`by_stage` input both return `[]`.
- **`tests/test_runs_index.py`** (extend): a result with `token_usage` yields the summed `total_tokens` and 4-dp `cost_usd`; a result without yields `—` for both; `MD_HEADERS` length equals `FIELDS` length.

`main.py`'s wiring has **no offline unit test** (it drives the real pipeline, which the constraints forbid running in tests — consistent with `run_trace`). It is verified by `python -c "import main"` plus the full suite passing, plus code review of the wiring.

## 6. Out of scope

- Per-sub-call timing/labels inside `extractor.py`.
- A local model price table or cost estimation when OpenRouter reports none.
- Surfacing tokens/cost in `runs_summary.md` or the batch comparison.
- Spend caps, budgets, or alerts.
- Any change to how agents produce their results.
