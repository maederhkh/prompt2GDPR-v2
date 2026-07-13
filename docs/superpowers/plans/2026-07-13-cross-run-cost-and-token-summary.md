# Cross-Run Cost & Token Summary — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Cost & tokens" subsection to the aggregate runs summary, reporting total and average cost and token usage across runs — in the Overall block and every Per-policy block.

**Architecture:** A single-file change to `utils/runs_summary.py`: extend `_num_stats` to also return a `sum`, roll up the `cost_usd` and `total_tokens` columns (already present in `runs_index.csv`) inside `summarize`, and render a new subsection in `_render_block`. The subsection appears automatically in both the Overall and per-policy blocks because both go through `_render_block`. Runs with no cost/token value are excluded via the existing "from *n* of *N* runs" denominator rule.

**Tech Stack:** Python 3.12, standard library only. Tests are standalone assert scripts (NOT pytest). Dev machine is Windows + PowerShell (chain commands with `;`, never `&&`).

## Global Constraints

- **Offline only.** No LLM/network/API key in any automated test. Never invoke the real pipeline.
- Tests are **standalone assert scripts**: `tests/test_runs_summary.py` inserts the repo root on `sys.path`, defines `test_*()` functions, and a `__main__` block that calls them and prints `OK`. Run with `python tests/test_runs_summary.py`.
- **Single-file feature.** Only `utils/runs_summary.py` (implementation) and `tests/test_runs_summary.py` (tests) change. No change to `runs_index.py`, the per-run JSON, the human report, the batch comparison, or the CLI (`analyze_runs.py`).
- **Reuse the existing helpers.** `_numeric(value)` already coerces `—`/`N/A`/empty to `None`; `_num_stats(rows, field)` already filters to numeric cells and returns `None` for an all-empty column. Cost and tokens follow the same denominator rule as every existing stat — do NOT special-case them.
- **Exact formats:** cost renders with a leading `$` and **4 decimals** (`f"${x:.4f}"`); tokens render as whole numbers with **thousands separators** (`f"{x:,.0f}"`). The **total** line carries a `"(from n of N runs)"` suffix; the **average** line does not. The all-empty case renders `- Cost: n/a (0 of N runs)` and `- Tokens: n/a (0 of N runs)`.
- The index columns this reads (`total_tokens`, `cost_usd`) already exist in `FIELDS` from the 2026-07-07 token/cost work; no index or schema change is needed.
- `docs/` is gitignored; `utils/` and `tests/` are tracked normally. Only `git add` the two named files (never `git add -A`). Do NOT stage `.claude/settings.local.json` or `.superpowers/`.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `utils/runs_summary.py` | Modify | Add `sum` to `_num_stats`; add `cost` and `total_tokens` roll-ups to `summarize`; render the "Cost & tokens" subsection in `_render_block`. |
| `tests/test_runs_summary.py` | Modify | Assert the roll-up math (sum/avg/n) and the rendered lines, including the partial-data and all-empty cases. |

---

## Task 1: Add cost & token roll-up to the aggregate summary

**Files:**
- Modify: `utils/runs_summary.py`
- Test: `tests/test_runs_summary.py`

**Interfaces:**
- Consumes: each index-row dict's `cost_usd` and `total_tokens` string cells (already exposed by `load_index_rows` via `FIELDS`); a cell may be a numeric string or a sentinel (`—`/`N/A`/empty).
- Produces: `summarize(rows)` gains two keys — `"cost"` and `"total_tokens"` — each either `None` (no numeric cells) or a dict `{"avg", "min", "max", "sum", "n"}`. `_render_block` emits a `"{h} Cost & tokens"` subsection.

- [ ] **Step 1: Write the failing tests**

In `tests/test_runs_summary.py`, add these four test functions (the existing `_row(**overrides)` helper already supplies every field, including `cost_usd` and `total_tokens`):

```python
def test_summarize_cost_and_token_rollup():
    rows = [
        _row(cost_usd="0.10", total_tokens="1000"),
        _row(cost_usd="0.20", total_tokens="3000"),
    ]
    s = summarize(rows)
    assert round(s["cost"]["sum"], 4) == 0.30
    assert round(s["cost"]["avg"], 4) == 0.15
    assert s["cost"]["n"] == 2
    assert s["total_tokens"]["sum"] == 4000
    assert s["total_tokens"]["avg"] == 2000
    assert s["total_tokens"]["n"] == 2


def test_summarize_cost_partial_data():
    rows = [
        _row(cost_usd="0.10", total_tokens="1000"),
        _row(cost_usd="—", total_tokens="—"),
    ]
    s = summarize(rows)
    assert s["cost"]["n"] == 1
    assert round(s["cost"]["sum"], 4) == 0.10
    assert s["total_tokens"]["n"] == 1
    assert s["total_tokens"]["sum"] == 1000


def test_render_cost_and_tokens_section():
    rows = [
        _row(cost_usd="0.10", total_tokens="1000"),
        _row(cost_usd="0.20", total_tokens="3000"),
    ]
    md = build_summary_md(rows)
    assert "Cost & tokens" in md
    assert "Total cost: $0.3000 (from 2 of 2 runs)" in md
    assert "Avg cost/run: $0.1500" in md
    assert "Total tokens: 4,000 (from 2 of 2 runs)" in md
    assert "Avg tokens/run: 2,000" in md


def test_render_cost_and_tokens_no_data():
    rows = [_row(cost_usd="—", total_tokens="—")]
    md = build_summary_md(rows)
    assert "Cost: n/a (0 of 1 runs)" in md
    assert "Tokens: n/a (0 of 1 runs)" in md
```

Register them in the `__main__` block (add the four calls alongside the existing ones, before `print("OK")`):

```python
    test_summarize_cost_and_token_rollup()
    test_summarize_cost_partial_data()
    test_render_cost_and_tokens_section()
    test_render_cost_and_tokens_no_data()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python tests/test_runs_summary.py`
Expected: FAIL — `test_summarize_cost_and_token_rollup` raises `TypeError`/`KeyError` because `summarize` has no `"cost"` key yet (and `_num_stats` has no `"sum"`). Non-zero exit, no `OK`.

- [ ] **Step 3: Add `sum` to `_num_stats`**

In `utils/runs_summary.py`, `_num_stats` currently returns:

```python
    return {
        "avg": sum(vals) / len(vals),
        "min": min(vals),
        "max": max(vals),
        "n": len(vals),
    }
```

Change it to add a `sum` (the totals lines need it; existing callers ignore the new key):

```python
    return {
        "avg": sum(vals) / len(vals),
        "min": min(vals),
        "max": max(vals),
        "sum": sum(vals),
        "n": len(vals),
    }
```

- [ ] **Step 4: Roll up cost and tokens in `summarize`**

The dict returned by `summarize` currently ends:

```python
        "anchoring_a": _num_stats(rows, "anchoring_a"),
        "anchoring_b": _num_stats(rows, "anchoring_b"),
    }
```

Change it to add the two roll-ups:

```python
        "anchoring_a": _num_stats(rows, "anchoring_a"),
        "anchoring_b": _num_stats(rows, "anchoring_b"),
        "cost": _num_stats(rows, "cost_usd"),
        "total_tokens": _num_stats(rows, "total_tokens"),
    }
```

- [ ] **Step 5: Render the "Cost & tokens" subsection in `_render_block`**

`_render_block` currently ends with the anchoring line and `return lines`:

```python
    lines.append(
        f"- Anchoring shift: A {_avg_with_denominator(s['anchoring_a'], n)}, "
        f"B {_avg_with_denominator(s['anchoring_b'], n)}"
    )
    return lines
```

Change it to append the new subsection before `return`:

```python
    lines.append(
        f"- Anchoring shift: A {_avg_with_denominator(s['anchoring_a'], n)}, "
        f"B {_avg_with_denominator(s['anchoring_b'], n)}"
    )
    lines.append("")
    lines.append(f"{h} Cost & tokens")
    cost = s["cost"]
    if cost is None:
        lines.append(f"- Cost: n/a (0 of {n} runs)")
    else:
        lines.append(f"- Total cost: ${cost['sum']:.4f} (from {cost['n']} of {n} runs)")
        lines.append(f"- Avg cost/run: ${cost['avg']:.4f}")
    tok = s["total_tokens"]
    if tok is None:
        lines.append(f"- Tokens: n/a (0 of {n} runs)")
    else:
        lines.append(f"- Total tokens: {tok['sum']:,.0f} (from {tok['n']} of {n} runs)")
        lines.append(f"- Avg tokens/run: {tok['avg']:,.0f}")
    return lines
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python tests/test_runs_summary.py`
Expected: `OK`.

- [ ] **Step 7: Run the full offline suite**

```powershell
Get-ChildItem tests/test_*.py | ForEach-Object { Write-Host "=== $($_.Name) ==="; python $_.FullName; if ($LASTEXITCODE -ne 0) { throw "FAILED: $($_.Name)" } }
```
Expected: every suite prints `OK`; no `FAILED:` thrown.

- [ ] **Step 8: Commit**

```bash
git add utils/runs_summary.py tests/test_runs_summary.py
git commit -m "feat: report cross-run cost and token totals in the runs summary"
```

Then run `git status --short` and confirm only `utils/runs_summary.py` and `tests/test_runs_summary.py` were staged.

---

## Notes for the implementer

- **No pytest.** Run the suite directly: `python tests/test_runs_summary.py`; success prints `OK`.
- **Float note:** `0.10 + 0.20` is `0.30000000000000004` in float, but `f"{0.30000000000000004:.4f}"` renders exactly `"0.3000"`, so the render assertions hold without rounding. The `summarize` math assertions use `round(..., 4)` for the same reason.
- **Denominator rule:** the `"from n of N runs"` suffix comes straight from `stats["n"]` (numeric cells) and `n` (all rows in the block) — do not recompute it; it mirrors `_avg_with_denominator`.
- **Do not** add cost/token columns to the batch comparison or read the per-run JSONs — the summary aggregates only the run-level totals already in the index CSV (spec §7).
- `_num_stats` is shared by many columns; adding a `sum` key is additive and safe — every existing caller reads only `avg`/`min`/`max`/`n`.
