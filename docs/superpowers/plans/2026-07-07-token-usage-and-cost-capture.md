# Per-Agent Token & Cost Capture — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture per-run token usage and OpenRouter-reported cost for every LLM call, grouped by agent and totalled, surfaced as an additive `token_usage` JSON key, a "Token Usage & Cost" report section, and two new runs-index columns.

**Architecture:** A `MeteredClient` wraps the OpenAI client and records `response.usage` (tokens + inline OpenRouter cost) into a `UsageMeter` on every `chat.completions.create`, tagged with the active stage. Agents are unchanged (they receive the wrapped client). A pure `_render_usage_section` renders the report table; `build_index_row` reads the run totals for two new columns. Wiring mirrors the shipped `run_trace` feature.

**Tech Stack:** Python 3.12, standard library only (plus the existing `openai` SDK type used only as a passthrough). Tests are standalone assert scripts. Dev machine is Windows + PowerShell (chain with `;`, never `&&`).

## Global Constraints

- **Offline only.** No LLM/network/API key in any automated test. Do NOT run `main.py`'s real pipeline in any test (it needs `OPENROUTER_API_KEY`). Tests use fake client/response objects.
- Tests are **standalone assert scripts** (NOT pytest): each `tests/test_*.py` adds the repo root to `sys.path`, defines `test_*()` functions, and a `__main__` block that calls them and prints `OK`; any failure raises and exits non-zero. Run a suite with `python tests/<file>.py`.
- **The only JSON change permitted is the additive top-level `token_usage` key.** No existing JSON key changes. No change to any file under `agents/`, to prompts, evaluation, `run_metadata`, `run_trace`, `runs_summary.py`, or the batch comparison.
- **No existing report section changes.** The new "Token Usage & Cost" section is appended at the very end of the report, after the Execution Timeline. Runs without a `token_usage` (older runs, empty usage) must render exactly as they do today — the section is silently omitted.
- **Cost comes only from OpenRouter.** No local price table. When OpenRouter does not report a cost, it renders `—` (the `EM_DASH` constant), never estimated.
- **Attribution is orchestration-granularity**, matching `run_trace`: the extractor's Scout/Deep/Self-Check/Gap-Judge sub-calls all attribute to `extractor`. Do NOT modify `agents/extractor.py` to label sub-calls.
- **No new CLI flag.** Usage is always captured and always rendered when present.
- **Never crash a run for usage capture.** A missing/malformed `response.usage` yields a zero/None record, not an exception (same philosophy as `run_metadata`/`runs_index`).
- `docs/` is gitignored. `utils/`, `tests/`, `main.py` are NOT gitignored and stage normally.
- Do NOT commit `.claude/settings.local.json` or anything under `.superpowers/`. Only `git add` the exact files named in each commit step (never `git add -A`).

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `utils/usage_meter.py` | Create | `UsageMeter` (per-call record collector + `stage()` context manager + `by_stage`/`totals`/`to_dict` roll-ups) and `MeteredClient` (wraps the client; injects `usage.include`; records usage; returns response unchanged). |
| `tests/test_usage_meter.py` | Create | Unit tests for `UsageMeter` + `MeteredClient` (fake client/response). |
| `utils/report_generator.py` | Modify | Add pure `_render_usage_section(token_usage)`; call it at the end of `generate_report`. |
| `tests/test_report_usage_section.py` | Create | Unit tests for `_render_usage_section`. |
| `utils/runs_index.py` | Modify | Add `total_tokens` + `cost_usd` to `FIELDS`/`MD_HEADERS`; compute both from `token_usage` in `build_index_row`. |
| `tests/test_runs_index.py` | Modify | Assert the two new columns (with usage; `—` without). |
| `main.py` | Modify | Instantiate `UsageMeter`, wrap the client with `MeteredClient`, tag each stage via `meter.stage(...)`, attach `token_usage` to both result dicts; extend `_empty_result`. |

**`token_usage` shape** (produced by Task 1 via `UsageMeter.to_dict()`; consumed by Tasks 2, 3, 4):

```python
{
  "calls": [                       # one per LLM call, in order
    {"stage": str|None, "model": str|None, "prompt_tokens": int,
     "completion_tokens": int, "total_tokens": int, "cost": float|None},
    ...
  ],
  "by_stage": [                    # roll-up, one per stage, first-seen order
    {"stage": str|None, "calls": int, "prompt_tokens": int,
     "completion_tokens": int, "total_tokens": int, "cost": float|None},
    ...
  ],
  "totals": {"calls": int, "prompt_tokens": int, "completion_tokens": int,
             "total_tokens": int, "cost": float|None},
}
```

`cost` is the sum of non-None per-call costs, or `None` if no call in that group reported a cost.

---

## Task 1: `UsageMeter` + `MeteredClient`

**Files:**
- Create: `utils/usage_meter.py`
- Test: `tests/test_usage_meter.py`

**Interfaces:**
- Consumes: an OpenAI-like client exposing `client.chat.completions.create(**kwargs)` returning an object with a `.usage` attribute.
- Produces:
  - `UsageMeter()` — recorder; `stage(name)` context manager; `record(*, model, prompt_tokens, completion_tokens, total_tokens, cost)`; `records` property; `by_stage() -> list`; `totals() -> dict`; `to_dict() -> dict` (shape above).
  - `MeteredClient(inner_client, meter)` — exposes `.chat.completions.create(**kwargs)`: injects `extra_body={"usage": {"include": True}}` (merging), calls the inner client, records usage under the meter's active stage tagged with `kwargs["model"]`, returns the response unchanged.

- [ ] **Step 1: Write the failing test**

Create `tests/test_usage_meter.py`:

```python
"""Standalone assert tests for the UsageMeter + MeteredClient."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.usage_meter import UsageMeter, MeteredClient

_MISSING = object()


class _Usage:
    """Fake response.usage. Omit `cost` to simulate a provider that reports none."""
    def __init__(self, prompt_tokens, completion_tokens, total_tokens, cost=_MISSING):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        if cost is not _MISSING:
            self.cost = cost


class _Response:
    def __init__(self, usage):
        self.usage = usage


class _FakeCompletions:
    """Records the kwargs of each call and returns scripted responses in order."""
    def __init__(self, responses):
        self._it = iter(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return next(self._it)


class _FakeChat:
    def __init__(self, responses):
        self.completions = _FakeCompletions(responses)


class _FakeClient:
    def __init__(self, responses):
        self.chat = _FakeChat(responses)


def test_records_call_under_active_stage_and_returns_response_unchanged():
    resp = _Response(_Usage(10, 20, 30, cost=0.001))
    client = _FakeClient([resp])
    meter = UsageMeter()
    metered = MeteredClient(client, meter)

    with meter.stage("evaluator"):
        got = metered.chat.completions.create(model="m1", messages=[{"role": "user", "content": "x"}])

    assert got is resp, "response must be returned unchanged"
    assert len(meter.records) == 1
    rec = meter.records[0]
    assert rec["stage"] == "evaluator"
    assert rec["model"] == "m1"
    assert rec["prompt_tokens"] == 10 and rec["completion_tokens"] == 20 and rec["total_tokens"] == 30
    assert rec["cost"] == 0.001
    # the usage.include flag was injected into the request
    assert client.chat.completions.calls[0]["extra_body"]["usage"]["include"] is True


def test_by_stage_rolls_up_multiple_calls():
    responses = [_Response(_Usage(5, 5, 10, cost=0.001)), _Response(_Usage(7, 3, 10, cost=0.002))]
    client = _FakeClient(responses)
    meter = UsageMeter()
    metered = MeteredClient(client, meter)
    with meter.stage("extractor"):
        metered.chat.completions.create(model="scout-model", messages=[])
        metered.chat.completions.create(model="extractor-model", messages=[])

    by_stage = meter.by_stage()
    assert len(by_stage) == 1
    e = by_stage[0]
    assert e["stage"] == "extractor" and e["calls"] == 2
    assert e["total_tokens"] == 20
    assert abs(e["cost"] - 0.003) < 1e-9


def test_merges_existing_extra_body():
    client = _FakeClient([_Response(_Usage(1, 1, 2, cost=0.0))])
    meter = UsageMeter()
    metered = MeteredClient(client, meter)
    with meter.stage("finalizer"):
        metered.chat.completions.create(model="m", messages=[], extra_body={"foo": 1})
    sent = client.chat.completions.calls[0]["extra_body"]
    assert sent["foo"] == 1                      # caller's key preserved
    assert sent["usage"]["include"] is True      # our flag added


def test_missing_cost_records_none_and_does_not_crash():
    client = _FakeClient([_Response(_Usage(4, 6, 10))])   # no cost attribute
    meter = UsageMeter()
    metered = MeteredClient(client, meter)
    with meter.stage("reflector_a"):
        metered.chat.completions.create(model="m", messages=[])
    assert meter.records[0]["cost"] is None
    assert meter.by_stage()[0]["cost"] is None
    assert meter.totals()["cost"] is None


def test_totals_and_to_dict():
    responses = [_Response(_Usage(5, 5, 10, cost=0.001)), _Response(_Usage(7, 3, 10, cost=0.002))]
    client = _FakeClient(responses)
    meter = UsageMeter()
    metered = MeteredClient(client, meter)
    with meter.stage("extractor"):
        metered.chat.completions.create(model="a", messages=[])
    with meter.stage("evaluator"):
        metered.chat.completions.create(model="b", messages=[])

    totals = meter.totals()
    assert totals["calls"] == 2 and totals["total_tokens"] == 20
    assert abs(totals["cost"] - 0.003) < 1e-9

    d = meter.to_dict()
    assert set(d.keys()) == {"calls", "by_stage", "totals"}
    assert len(d["calls"]) == 2 and len(d["by_stage"]) == 2


if __name__ == "__main__":
    test_records_call_under_active_stage_and_returns_response_unchanged()
    test_by_stage_rolls_up_multiple_calls()
    test_merges_existing_extra_body()
    test_missing_cost_records_none_and_does_not_crash()
    test_totals_and_to_dict()
    print("OK")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_usage_meter.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'utils.usage_meter'` (or `ImportError`).

- [ ] **Step 3: Implement `utils/usage_meter.py`**

Create `utils/usage_meter.py`:

```python
"""
Per-run token & cost meter.

UsageMeter collects one record per LLM call — the active stage (which agent was
running), the model, token counts, and OpenRouter-reported cost — and rolls
them up per stage and for the whole run. MeteredClient wraps the OpenAI client
so every chat.completions.create call is recorded and OpenRouter's inline cost
is requested; the agents keep calling the client unchanged.

Pure aside from delegating to the wrapped client: it performs no I/O of its own
and never crashes a run — a missing or malformed usage object yields a
zero/None record rather than raising.
"""

from contextlib import contextmanager


class UsageMeter:
    def __init__(self):
        self._records = []
        self._stage = None

    @contextmanager
    def stage(self, name):
        """Mark `name` as the active stage for calls made inside the block.

        Restores the previous stage on exit so sequential/nested stages are safe.
        """
        previous = self._stage
        self._stage = name
        try:
            yield
        finally:
            self._stage = previous

    def record(self, *, model, prompt_tokens, completion_tokens, total_tokens, cost) -> None:
        """Append one per-call record under the currently-active stage."""
        self._records.append({
            "stage": self._stage,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost": cost,
        })

    @property
    def records(self) -> list:
        return self._records

    def _rollup(self, rows) -> dict:
        agg = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
               "total_tokens": 0, "cost": None}
        for r in rows:
            agg["calls"] += 1
            agg["prompt_tokens"] += r["prompt_tokens"] or 0
            agg["completion_tokens"] += r["completion_tokens"] or 0
            agg["total_tokens"] += r["total_tokens"] or 0
            if r["cost"] is not None:
                agg["cost"] = (agg["cost"] or 0) + r["cost"]
        return agg

    def by_stage(self) -> list:
        """One roll-up entry per stage, in first-seen order."""
        order = []
        buckets = {}
        for r in self._records:
            stage = r["stage"]
            if stage not in buckets:
                buckets[stage] = []
                order.append(stage)
            buckets[stage].append(r)
        result = []
        for stage in order:
            entry = self._rollup(buckets[stage])
            entry["stage"] = stage
            # stage first for readability
            result.append({"stage": stage, **{k: entry[k] for k in
                            ("calls", "prompt_tokens", "completion_tokens", "total_tokens", "cost")}})
        return result

    def totals(self) -> dict:
        return self._rollup(self._records)

    def to_dict(self) -> dict:
        return {"calls": self._records, "by_stage": self.by_stage(), "totals": self.totals()}


def _extract_usage(response) -> dict:
    """Read token/cost fields off response.usage, defensively. Never raises."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": None}

    def _int(attr):
        value = getattr(usage, attr, 0)
        return value if isinstance(value, int) else 0

    cost = getattr(usage, "cost", None)
    if not isinstance(cost, (int, float)) or isinstance(cost, bool):
        cost = None
    return {
        "prompt_tokens": _int("prompt_tokens"),
        "completion_tokens": _int("completion_tokens"),
        "total_tokens": _int("total_tokens"),
        "cost": cost,
    }


class _MeteredCompletions:
    def __init__(self, inner, meter):
        self._inner = inner
        self._meter = meter

    def create(self, **kwargs):
        # Ask OpenRouter to include cost inline, preserving any caller extra_body keys.
        extra_body = dict(kwargs.get("extra_body") or {})
        usage_opt = dict(extra_body.get("usage") or {})
        usage_opt["include"] = True
        extra_body["usage"] = usage_opt
        kwargs["extra_body"] = extra_body

        response = self._inner.create(**kwargs)

        u = _extract_usage(response)
        self._meter.record(model=kwargs.get("model"), **u)
        return response


class _MeteredChat:
    def __init__(self, inner_chat, meter):
        self.completions = _MeteredCompletions(inner_chat.completions, meter)


class MeteredClient:
    """Wraps an OpenAI client so every chat.completions.create is metered.

    Exposes only the surface the agents use (`client.chat.completions.create`).
    """
    def __init__(self, inner_client, meter: UsageMeter):
        self._inner = inner_client
        self.chat = _MeteredChat(inner_client.chat, meter)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python tests/test_usage_meter.py`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add utils/usage_meter.py tests/test_usage_meter.py
git commit -m "feat: add UsageMeter and MeteredClient for token/cost capture"
```

---

## Task 2: Render the Token Usage & Cost section

**Files:**
- Modify: `utils/report_generator.py`
- Test: `tests/test_report_usage_section.py`

**Interfaces:**
- Consumes: a `token_usage` dict (shape in the File Map) — or `None`.
- Produces: `_render_usage_section(token_usage) -> list` — a module-level pure function returning markdown lines (empty list when nothing to show). Called by `generate_report`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_report_usage_section.py`:

```python
"""Standalone assert tests for _render_usage_section in the report generator."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.report_generator import _render_usage_section


def _usage():
    return {
        "calls": [],  # not read by the renderer
        "by_stage": [
            {"stage": "extractor", "calls": 4, "prompt_tokens": 10000,
             "completion_tokens": 2400, "total_tokens": 12400, "cost": 0.018},
            {"stage": "evaluator", "calls": 1, "prompt_tokens": 6000,
             "completion_tokens": 2100, "total_tokens": 8100, "cost": None},
        ],
        "totals": {"calls": 5, "prompt_tokens": 16000, "completion_tokens": 4500,
                   "total_tokens": 20500, "cost": 0.018},
    }


def test_full_usage_has_heading_summary_rows_and_total():
    lines = _render_usage_section(_usage())
    text = "\n".join(lines)
    assert "## Token Usage & Cost" in text, text
    assert "| Agent | Calls | Prompt | Completion | Total tokens | Cost (USD) |" in text, text
    assert "5 call(s)" in text, text
    assert "20,500 tokens" in text, text     # totals with thousands separator
    assert "$0.0180" in text, text           # total cost, 4dp
    assert text.count("| extractor |") == 1
    assert text.count("| evaluator |") == 1
    assert "| **TOTAL** |" in text, text


def test_none_cost_renders_dash():
    lines = _render_usage_section(_usage())
    evaluator_row = [ln for ln in lines if ln.startswith("| evaluator |")][0]
    assert "| — |" in evaluator_row, evaluator_row


def test_token_counts_use_thousands_separators():
    lines = _render_usage_section(_usage())
    extractor_row = [ln for ln in lines if ln.startswith("| extractor |")][0]
    assert "12,400" in extractor_row, extractor_row


def test_empty_or_missing_usage_returns_empty_list():
    assert _render_usage_section(None) == []
    assert _render_usage_section({}) == []
    assert _render_usage_section({"by_stage": []}) == []


if __name__ == "__main__":
    test_full_usage_has_heading_summary_rows_and_total()
    test_none_cost_renders_dash()
    test_token_counts_use_thousands_separators()
    test_empty_or_missing_usage_returns_empty_list()
    print("OK")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_report_usage_section.py`
Expected: FAIL with `ImportError: cannot import name '_render_usage_section'`.

- [ ] **Step 3: Implement `_render_usage_section`**

In `utils/report_generator.py`, add this module-level function directly **below** the existing `_render_trace_section` function (i.e. after its `return lines` on line 105, before `def generate_report` on line 107):

```python
def _render_usage_section(token_usage) -> list:
    """
    Render the Token Usage & Cost section from a token_usage dict.

    Returns [] when there is nothing to show (token_usage is falsy or its
    by_stage roll-up is empty). Pure: writes nothing and does not mutate input.

    token_usage shape:
      {"calls": [...],
       "by_stage": [{"stage","calls","prompt_tokens","completion_tokens",
                     "total_tokens","cost"}, ...],
       "totals": {"calls","prompt_tokens","completion_tokens","total_tokens","cost"}}
    """
    if not token_usage:
        return []
    by_stage = token_usage.get("by_stage") or []
    if not by_stage:
        return []

    def _cell(value) -> str:
        return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")

    def _cost(value) -> str:
        # OpenRouter cost in USD; em dash when the provider reported none.
        return f"${value:.4f}" if isinstance(value, (int, float)) and not isinstance(value, bool) else "—"

    totals = token_usage.get("totals") or {}
    total_calls = totals.get("calls", sum(s.get("calls", 0) for s in by_stage))
    total_tokens = totals.get("total_tokens", 0)
    total_cost = totals.get("cost")

    summary = f"- {total_calls} call(s), {total_tokens:,} tokens, {_cost(total_cost)} total"

    lines = [
        "## Token Usage & Cost",
        "",
        summary,
        "",
        "| Agent | Calls | Prompt | Completion | Total tokens | Cost (USD) |",
        "|---|---|---|---|---|---|",
    ]
    for s in by_stage:
        lines.append(
            f"| {_cell(s.get('stage', ''))} | {s.get('calls', 0)} "
            f"| {s.get('prompt_tokens', 0):,} | {s.get('completion_tokens', 0):,} "
            f"| {s.get('total_tokens', 0):,} | {_cost(s.get('cost'))} |"
        )
    lines.append(
        f"| **TOTAL** | {total_calls} | {totals.get('prompt_tokens', 0):,} "
        f"| {totals.get('completion_tokens', 0):,} | {total_tokens:,} | {_cost(total_cost)} |"
    )
    lines.append("")
    return lines
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python tests/test_report_usage_section.py`
Expected: `OK`.

- [ ] **Step 5: Wire it into `generate_report`**

In `utils/report_generator.py`, the report currently ends with the trace section extend (line 472) immediately before the write-file block:

```python
    lines.extend(_render_trace_section(result.get("run_trace")))

    # -----------------------------------------------------------------------
    # Write file
    # -----------------------------------------------------------------------
    out_path.write_text("\n".join(lines), encoding="utf-8")
```

Insert the usage-section call right after the trace-section line, so it reads:

```python
    lines.extend(_render_trace_section(result.get("run_trace")))
    lines.extend(_render_usage_section(result.get("token_usage")))

    # -----------------------------------------------------------------------
    # Write file
    # -----------------------------------------------------------------------
    out_path.write_text("\n".join(lines), encoding="utf-8")
```

- [ ] **Step 6: Confirm the report still builds with no token_usage and existing tests pass**

A result with no `token_usage` must add no Token Usage section:

```powershell
python -c "import os; from pathlib import Path; from utils.report_generator import generate_report; p=Path(os.environ['TEMP'])/'._usage_plan_check.md'; generate_report({'extractor_output': {}, 'finalizer_output': {}, 'evaluator_output': {}}, p); t=p.read_text(encoding='utf-8'); print('NO USAGE' if 'Token Usage' not in t else 'UNEXPECTED SECTION'); p.unlink()"
```
Expected: `NO USAGE`.

Then re-run all offline suites:

```powershell
Get-ChildItem tests/test_*.py | ForEach-Object { Write-Host "=== $($_.Name) ==="; python $_.FullName; if ($LASTEXITCODE -ne 0) { throw "FAILED: $($_.Name)" } }
```
Expected: every suite prints `OK`; no `FAILED:` thrown.

- [ ] **Step 7: Commit**

```bash
git add utils/report_generator.py tests/test_report_usage_section.py
git commit -m "feat: render token usage and cost section in the human report"
```

---

## Task 3: Add token & cost columns to the runs index

**Files:**
- Modify: `utils/runs_index.py`
- Test: `tests/test_runs_index.py`

**Interfaces:**
- Consumes: `result["token_usage"]["totals"]` — `{"total_tokens": int, "cost": float|None, ...}` — or absent.
- Produces: `build_index_row(result)` returns a dict now ending with `"total_tokens"` and `"cost_usd"`; `FIELDS` and `MD_HEADERS` each gain two trailing entries.

`runs_summary.py` does **not** need changes: `summarize` reads columns by name via `.get()` and does not require all `FIELDS` to be present; the two appended columns are ignored there. Step 4 confirms this by running the full suite (including `test_runs_summary.py`).

- [ ] **Step 1: Update the test to add the failing assertions**

In `tests/test_runs_index.py`:

(a) In `_full_result()`, add a `token_usage` entry as the last key of the returned dict. The dict currently ends (after the `run_trace` list added by the previous feature):

```python
        "run_trace": [
            {"step": 1, "stage": "extractor", "model": "m1", "duration_s": 16.8, "status": "ok", "note": ""},
            {"step": 2, "stage": "verifier", "model": None, "duration_s": 0.3, "status": "ok", "note": ""},
            {"step": 3, "stage": "evaluator", "model": "m2", "duration_s": 14.6, "status": "ok", "note": ""},
        ],
    }
```

Change it to add `token_usage` right after the `run_trace` list:

```python
        "run_trace": [
            {"step": 1, "stage": "extractor", "model": "m1", "duration_s": 16.8, "status": "ok", "note": ""},
            {"step": 2, "stage": "verifier", "model": None, "duration_s": 0.3, "status": "ok", "note": ""},
            {"step": 3, "stage": "evaluator", "model": "m2", "duration_s": 14.6, "status": "ok", "note": ""},
        ],
        "token_usage": {
            "calls": [],
            "by_stage": [],
            "totals": {"calls": 5, "prompt_tokens": 30000, "completion_tokens": 11000,
                       "total_tokens": 41000, "cost": 0.0523},
        },
    }
```

(b) Add two assertions at the end of `test_build_index_row_full` (after the `duration_s` assertion):

```python
    assert row["total_tokens"] == 41000
    assert row["cost_usd"] == 0.0523   # round(0.0523, 4)
```

(c) Add two assertions at the end of `test_build_index_row_empty_result` (after the `duration_s` assertion):

```python
    assert row["total_tokens"] == "—"   # no token_usage -> em dash
    assert row["cost_usd"] == "—"
```

(The existing `test_headers_align_with_fields` already asserts `len(MD_HEADERS) == len(FIELDS)` and needs no change; it will keep both lists honest.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_runs_index.py`
Expected: FAIL — `test_build_index_row_full` raises `KeyError: 'total_tokens'` (the fields do not exist yet). Non-zero exit, no `OK`.

- [ ] **Step 3: Implement the columns in `utils/runs_index.py`**

(a) Append `"total_tokens"` and `"cost_usd"` to the `FIELDS` list. It currently ends (after the `duration_s` added by the previous feature):

```python
    "anchoring_a",
    "anchoring_b",
    "duration_s",
]
```

Change it to:

```python
    "anchoring_a",
    "anchoring_b",
    "duration_s",
    "total_tokens",
    "cost_usd",
]
```

(b) Append `"Total tokens"` and `"Cost (USD)"` to the `MD_HEADERS` list. It currently ends:

```python
    "Anchoring A",
    "Anchoring B",
    "Duration (s)",
]
```

Change it to:

```python
    "Anchoring A",
    "Anchoring B",
    "Duration (s)",
    "Total tokens",
    "Cost (USD)",
]
```

(c) In `build_index_row`, compute the two values next to the existing `duration_s` computation. It currently reads:

```python
    run_trace = result.get("run_trace") or []
    duration_s = round(sum(e.get("duration_s") or 0 for e in run_trace), 1) if run_trace else EM_DASH

    return {
```

Change it to:

```python
    run_trace = result.get("run_trace") or []
    duration_s = round(sum(e.get("duration_s") or 0 for e in run_trace), 1) if run_trace else EM_DASH

    tu_totals = (result.get("token_usage") or {}).get("totals") or {}
    tok = tu_totals.get("total_tokens")
    total_tokens = tok if isinstance(tok, int) and tok else EM_DASH
    cost = tu_totals.get("cost")
    cost_usd = round(cost, 4) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else EM_DASH

    return {
```

(d) Add the two entries as the **last** keys of the returned dict. It currently ends:

```python
        "anchoring_a": _anchoring(lp, "reflector_a"),
        "anchoring_b": _anchoring(lp, "reflector_b"),
        "duration_s": duration_s,
    }
```

Change it to:

```python
        "anchoring_a": _anchoring(lp, "reflector_a"),
        "anchoring_b": _anchoring(lp, "reflector_b"),
        "duration_s": duration_s,
        "total_tokens": total_tokens,
        "cost_usd": cost_usd,
    }
```

- [ ] **Step 4: Run the test to verify it passes, then the full suite**

Run: `python tests/test_runs_index.py`
Expected: `OK`.

Then the full suite (confirms `test_runs_summary.py` still passes unchanged):

```powershell
Get-ChildItem tests/test_*.py | ForEach-Object { Write-Host "=== $($_.Name) ==="; python $_.FullName; if ($LASTEXITCODE -ne 0) { throw "FAILED: $($_.Name)" } }
```
Expected: every suite prints `OK`; no `FAILED:` thrown.

- [ ] **Step 5: Commit**

```bash
git add utils/runs_index.py tests/test_runs_index.py
git commit -m "feat: add total tokens and cost columns to the runs index"
```

---

## Task 4: Wire the meter into the pipeline

**Files:**
- Modify: `main.py`

**Interfaces:**
- Consumes: `UsageMeter`, `MeteredClient` (Task 1) and `_render_usage_section` (Task 2, already wired into `generate_report`), and the runs-index columns (Task 3, already reading `token_usage`).
- Produces: `result["token_usage"]` — `meter.to_dict()` — on both the normal and empty-result return paths.

This task has **no offline unit test** (it drives the real LLM pipeline, which the Global Constraints forbid running in tests — consistent with `run_trace`). It is verified by an import smoke-test plus the full existing suite, and by code review of the wiring. Follow the edits exactly.

- [ ] **Step 1: Add the import**

In `main.py`, next to the other `utils` imports (e.g. after `from utils.run_trace import RunTrace`), add:

```python
from utils.usage_meter import UsageMeter, MeteredClient
```

- [ ] **Step 2: Instantiate the meter and wrap the client at the top of `run_pipeline`**

In `run_pipeline`, the top currently reads:

```python
    policy_name = policy_path.stem
    policy_text = load_policy_text(policy_path)
    trace = RunTrace()
```

Change it to:

```python
    policy_name = policy_path.stem
    policy_text = load_policy_text(policy_path)
    trace = RunTrace()
    meter = UsageMeter()
    client = MeteredClient(client, meter)  # meter every agent LLM call; agents unchanged
```

(Rebinding `client` means every existing `run_extractor(client, ...)` / `run_evaluator(client, ...)` / etc. call downstream is metered with no other call-site change.)

- [ ] **Step 3: Tag each stage with `meter.stage(...)`**

Add `, meter.stage("<name>")` as a second context manager to **each** existing `with trace.step("<name>", ...):` line, using the **same** stage string. Make these ten edits:

| Current line | Change to |
|---|---|
| `    with trace.step("extractor", model=agent_models["extractor"]):` | `    with trace.step("extractor", model=agent_models["extractor"]), meter.stage("extractor"):` |
| `    with trace.step("verifier"):` | `    with trace.step("verifier"), meter.stage("verifier"):` |
| `    with trace.step("evaluator", model=agent_models["evaluator"]):` | `    with trace.step("evaluator", model=agent_models["evaluator"]), meter.stage("evaluator"):` |
| `    with trace.step("reflector_a", model=agent_models["reflector_a"]):` | `    with trace.step("reflector_a", model=agent_models["reflector_a"]), meter.stage("reflector_a"):` |
| `    with trace.step("reflector_b", model=agent_models["reflector_b"]):` | `    with trace.step("reflector_b", model=agent_models["reflector_b"]), meter.stage("reflector_b"):` |
| `    with trace.step("merge"):` | `    with trace.step("merge"), meter.stage("merge"):` |
| `        with trace.step("blind_a", model=agent_models["blind_a"]):` | `        with trace.step("blind_a", model=agent_models["blind_a"]), meter.stage("blind_a"):` |
| `        with trace.step("blind_b", model=agent_models["blind_b"]):` | `        with trace.step("blind_b", model=agent_models["blind_b"]), meter.stage("blind_b"):` |
| `    with trace.step("label_panel"):` | `    with trace.step("label_panel"), meter.stage("label_panel"):` |
| `    with trace.step("finalizer", model=agent_models["finalizer"]):` | `    with trace.step("finalizer", model=agent_models["finalizer"]), meter.stage("finalizer"):` |

(`verifier`, `merge`, and `label_panel` make no LLM calls, so their `meter.stage(...)` simply records nothing — harmless and keeps the wrapping uniform.)

- [ ] **Step 4: Tag each retry-loop re-run**

Inside the `for attempt in range(1, MAX_RETRIES + 1):` loop, add `, meter.stage(...)` to each retry `with trace.step(...)` line, using the same retry-suffixed string. Make these six edits:

| Current line | Change to |
|---|---|
| `                with trace.step(f"extractor (retry {attempt})", model=agent_models["extractor"]):` | `                with trace.step(f"extractor (retry {attempt})", model=agent_models["extractor"]), meter.stage(f"extractor (retry {attempt})"):` |
| `                with trace.step(f"verifier (retry {attempt})"):` | `                with trace.step(f"verifier (retry {attempt})"), meter.stage(f"verifier (retry {attempt})"):` |
| `                with trace.step(f"evaluator (retry {attempt})", model=agent_models["evaluator"]):` | `                with trace.step(f"evaluator (retry {attempt})", model=agent_models["evaluator"]), meter.stage(f"evaluator (retry {attempt})"):` |
| `                with trace.step(f"reflector_a (retry {attempt})", model=agent_models["reflector_a"]):` | `                with trace.step(f"reflector_a (retry {attempt})", model=agent_models["reflector_a"]), meter.stage(f"reflector_a (retry {attempt})"):` |
| `                with trace.step(f"reflector_b (retry {attempt})", model=agent_models["reflector_b"]):` | `                with trace.step(f"reflector_b (retry {attempt})", model=agent_models["reflector_b"]), meter.stage(f"reflector_b (retry {attempt})"):` |
| `                with trace.step(f"merge (retry {attempt})"):` | `                with trace.step(f"merge (retry {attempt})"), meter.stage(f"merge (retry {attempt})"):` |

- [ ] **Step 5: Attach `token_usage` to the normal result dict**

In the big `return { ... }` dict at the end of `run_pipeline`, add a `token_usage` entry right after `run_trace`. Change:

```python
    return {
        "run_metadata": run_metadata,
        "run_trace": trace.events,
        "policy_name": policy_name,
```

to:

```python
    return {
        "run_metadata": run_metadata,
        "run_trace": trace.events,
        "token_usage": meter.to_dict(),
        "policy_name": policy_name,
```

- [ ] **Step 6: Extend `_empty_result` to carry the usage, and pass it at the call site**

Change the `_empty_result` call in the early-return branch. It currently reads:

```python
    if not verified_clauses:
        print("  WARNING: No verified clauses. Pipeline cannot continue with evaluation.")
        return _empty_result(policy_name, extractor_output, flagged_clauses, run_metadata, trace.events)
```

to:

```python
    if not verified_clauses:
        print("  WARNING: No verified clauses. Pipeline cannot continue with evaluation.")
        return _empty_result(policy_name, extractor_output, flagged_clauses, run_metadata, trace.events, meter.to_dict())
```

Then change the `_empty_result` definition. It currently reads:

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

to:

```python
def _empty_result(policy_name: str, extractor_output: dict, flagged_clauses: list,
                  run_metadata: dict, run_trace: list, token_usage: dict) -> dict:
    return {
        "run_metadata": run_metadata,
        "run_trace": run_trace,
        "token_usage": token_usage,
        "policy_name": policy_name,
        "error": "No verified clauses — all extracted clauses failed string-match verification.",
        "extractor_output": extractor_output,
        "flagged_clauses": flagged_clauses,
    }
```

- [ ] **Step 7: Verify `main.py` imports cleanly (offline smoke test)**

This confirms the wiring has no syntax/indentation/import errors. It does NOT call the pipeline, so no API key is needed.

Run:

```powershell
python -c "import main; print('IMPORT OK')"
```
Expected: `IMPORT OK` (no traceback).

- [ ] **Step 8: Re-run all offline suites**

```powershell
Get-ChildItem tests/test_*.py | ForEach-Object { Write-Host "=== $($_.Name) ==="; python $_.FullName; if ($LASTEXITCODE -ne 0) { throw "FAILED: $($_.Name)" } }
```
Expected: every suite prints `OK`; no `FAILED:` thrown.

- [ ] **Step 9: Commit**

```bash
git add main.py
git commit -m "feat: capture per-agent token usage and cost across the pipeline"
```

Then run `git status --short` and confirm no unintended files are staged (only `main.py` in this commit; `.claude/settings.local.json` and `.superpowers/` must NOT appear as staged).

---

## Notes for the implementer

- **No pytest.** Run a suite directly: `python tests/<file>.py`; success prints `OK`, failure exits non-zero.
- **Offline only.** No network/LLM call; never invoke the real pipeline (`main()` / `run_pipeline`). Task 4 is verified by the import smoke test + the full suite, not by running the pipeline.
- **Agents are never modified.** All capture happens at the `MeteredClient` seam and the `main.py` stage tagging. Do not touch anything under `agents/`.
- **Additive JSON only.** The single JSON change is the new top-level `token_usage` key on both return paths. Do not alter any other key.
- **Two context managers per stage.** Python's `with A, B:` enters both; the assigned variable still escapes the block (no new scope), so downstream code is unchanged apart from the longer `with` line.
- **`EM_DASH` is already defined** in `utils/runs_index.py` — reuse it for missing token/cost values.
- **`cost` may be `None`.** OpenRouter does not always report cost; every consumer (`by_stage`, `totals`, the renderer, the index) treats `None` as "no cost", never as `$0`, and renders `—`.
- **Only stage the files named in each commit step.** Do not commit `.claude/settings.local.json` or `.superpowers/`.
```
