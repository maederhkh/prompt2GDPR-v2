# Cross-Run Cost & Token Summary — Design Spec

**Date:** 2026-07-13
**Status:** Awaiting user review
**Scope:** Add a "Cost & tokens" subsection to the on-demand aggregate summary
(`analyze_runs.py` → `runs_summary.md`), reporting total and average cost and
token usage across runs — in both the Overall block and each Per-policy block.
Read-only over the existing runs index; pure stdlib; zero LLM calls.

---

## 1. Goal

Yesterday's work made every *single* pipeline run record its token usage and
cost (the `token_usage` JSON key, the report's Token Usage & Cost section, and
the `total_tokens` / `cost_usd` columns in the runs index). What is still
missing is a view **across runs**: the per-run numbers are never rolled up, so
there is no answer to "across all the policies I have assessed, what did this
cost, and what is the typical cost per run?"

This feature adds that roll-up to the aggregate summary. For a thesis, it turns
cost into a reportable figure (e.g. *"assessing the corpus cost $3.40, averaging
$0.085 per policy"*) and makes the token budget of the whole research effort
visible in one place.

## 2. Background — what already exists and is reused

- **`utils/runs_summary.py`** is the aggregate view. `load_index_rows` reads
  `runs_index.csv` into per-run dicts keyed by `FIELDS`; `summarize(rows)`
  computes one stats block; `_render_block(stats, heading)` renders it as
  markdown; `build_summary_md` assembles the Overall block plus one block per
  policy. This feature extends `summarize` and `_render_block` and adds a small
  amount of formatting; it introduces no new file.
- **`runs_index.csv`** already carries the two columns this feature reads —
  `total_tokens` and `cost_usd` — added in the 2026-07-07 token/cost work. They
  are part of `FIELDS`, so `load_index_rows` already exposes them on each row
  dict. No index change is needed.
- **`_numeric(value)`** already coerces a non-numeric cell (`—`, `N/A`, empty)
  to `None`, and **`_num_stats(rows, field)`** already computes avg/min/max/n
  over the numeric cells of a column, returning `None` when a column has no
  numeric values. This is exactly the "denominator rule" every existing stat
  uses; cost and tokens follow it unchanged.
- **`_avg_with_denominator(stats, total)`** already renders the
  `"0.88 (from 6 of 8 runs)"` / `"n/a (0 of 8 runs)"` convention that the new
  lines reuse for their "(from n of N runs)" suffix and their empty case.

## 3. Approaches considered

### 3.1 Recommended: extend the aggregate summary only

Add the roll-up to `summarize`/`_render_block`, reading the index columns that
already exist. Smallest change, no new file, no index change, fully offline.

Trade-off: the summary can only aggregate **run-level totals** (the index stores
one `total_tokens` and one `cost_usd` per run, not the per-agent breakdown), so
a per-agent cost aggregation across runs is not possible from this data source.
That is acceptable — the per-agent breakdown already exists per run in the JSON
and the report; the cross-run question is about run-level totals.

### 3.2 Also add columns to the batch comparison

Additionally surface `Total tokens` / `Cost (USD)` in the per-batch comparison
table. Rejected for now (YAGNI): the batch table is already wide and only covers
a single batch, while the cross-run cost question is answered by the aggregate
summary. Easy to add later if per-batch cost proves useful.

### 3.3 Read the per-run JSONs for a per-agent cross-run breakdown

Aggregate `by_stage` across every run's JSON to show cross-run per-agent cost.
Rejected: much larger scope, needs reading every JSON (not just the index CSV),
and the run-level roll-up already answers the driving question.

## 4. Feature design

### 4.1 Files

| File | Action | Responsibility |
|---|---|---|
| `utils/runs_summary.py` | Modify | Roll up `total_tokens` and `cost_usd`; render a "Cost & tokens" subsection in each block. |
| `tests/test_runs_summary.py` | Modify | Assert the roll-up math and the rendered lines, including the partial-data and no-data cases. |

No new files, no index change, no change to `runs_index.py`, the report, or the
per-run JSON.

### 4.2 Summing the columns

`_num_stats` currently returns `{"avg", "min", "max", "n"}`. The "total cost"
and "total tokens" figures need a sum. Extend `_num_stats` to also return
`"sum": sum(vals)`. This is additive — existing callers ignore the new key — and
keeps the sum computed from the same filtered numeric values, so total and
average share one denominator.

`summarize(rows)` gains two entries in its returned dict:

```python
"cost": _num_stats(rows, "cost_usd"),
"total_tokens": _num_stats(rows, "total_tokens"),
```

Both are `None` when the column has no numeric cells (older/empty runs), exactly
like the existing stats.

### 4.3 Rendered subsection

`_render_block(s, h)` appends one subsection after the existing "Reliability"
block, using the same heading prefix `h` (`###` under Overall, `####` under a
per-policy section):

```markdown
{h} Cost & tokens
- Total cost: $3.4021 (from 6 of 8 runs)
- Avg cost/run: $0.5670
- Total tokens: 210,400 (from 6 of 8 runs)
- Avg tokens/run: 35,067
```

Formatting:

- **Cost** renders with a leading `$` and **4 decimal places** (`f"${x:.4f}"`),
  matching the report's `_cost` and the index's rounded `cost_usd`.
- **Tokens** render as whole numbers with **thousands separators**
  (`f"{x:,.0f}"`), matching the report's token columns.
- The **total** line carries the `"(from n of N runs)"` denominator suffix
  (some runs may lack a value); the **average** line omits it (its denominator
  is implied by the total line directly above it).

### 4.4 Edge cases

- **No cost/token data in a block** (every cell is `—`, e.g. an index written
  before the token/cost feature, or a block of blind-only/failed runs): the
  stat is `None`. Render a single neutral line per metric, mirroring the
  existing `n/a` style:

  ```markdown
  {h} Cost & tokens
  - Cost: n/a (0 of 8 runs)
  - Tokens: n/a (0 of 8 runs)
  ```

- **Partial data** (some runs have cost, some show `—`): the sum and average are
  computed over the numeric cells only, and the denominator suffix reports how
  many of the total contributed (e.g. `from 6 of 8 runs`) — the established rule.
- **Zero runs** in a block cannot occur (`build_summary_md` only renders a
  per-policy block for policies that have rows), so no divide-by-zero guard
  beyond what `_num_stats` already provides is needed.

### 4.5 Placement

The subsection is added in `_render_block`, so it appears automatically in the
Overall block and in every Per-policy block, with correct heading depth. No
change to `build_summary_md`, `main`, or the CLI (`analyze_runs.py`).

## 5. Error handling

This feature is read-only over the index and adds no new failure modes. A
malformed cost/token cell is already coerced to `None` by `_numeric` and
excluded; a fully empty column yields the `n/a` lines. `main()` keeps its
existing behavior of reporting a missing/outdated index and returning `0`.

## 6. Testing and verification

Offline tests only. No API key, no LLM calls. Extend
`tests/test_runs_summary.py` (whose `_row()` fixture already includes
`total_tokens` and `cost_usd`):

1. **Roll-up math:** build several rows with known `cost_usd` / `total_tokens`;
   assert `summarize(rows)["cost"]["sum"]`, `["avg"]`, and `["n"]` and the same
   for `total_tokens`.
2. **Rendered lines:** assert `build_summary_md(rows)` contains a
   `Total cost: $…` line, an `Avg cost/run: $…` line, a `Total tokens: …` line
   (with a thousands separator), and an `Avg tokens/run: …` line.
3. **Partial data:** some rows with `—` cost/tokens; assert the sum/avg use only
   the numeric rows and the denominator suffix reads `from k of N runs`.
4. **No data:** all rows have `—` for both columns; assert the block renders the
   `Cost: n/a (0 of N runs)` / `Tokens: n/a (0 of N runs)` lines and does not
   crash.

Manual verification:

```bash
python tests/test_runs_summary.py
python analyze_runs.py   # against an existing output/results/runs_index.csv, if present
```

## 7. Out of scope

- No change to the batch comparison table (approach 3.2, deferred).
- No per-agent cost aggregation across runs (approach 3.3): the index stores
  only run-level totals; the per-agent breakdown stays per-run in the JSON/report.
- No change to `runs_index.py`, the per-run JSON, the human report, or the CLI
  surface.
- No new output file — this extends the existing `runs_summary.md`.
- No cost forecasting, budgets, or spend caps.
