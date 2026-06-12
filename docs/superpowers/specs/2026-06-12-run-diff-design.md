# Run Diff (Clause-Level Comparison) — Design Spec

**Date:** 2026-06-12
**Status:** Approved for planning
**Scope:** A standalone, offline tool that compares two pipeline run JSONs clause by clause and model by model, printing the diff to the terminal and writing one markdown file. Zero LLM calls, zero pipeline coupling, on-demand only.

---

## 1. Goal

The pipeline saves a complete JSON per run, but there is no way to answer "what changed between these two runs?" without reading two huge JSONs by hand. This feature adds:

```
python diff_runs.py <run_a.json> <run_b.json>
```

which prints a clause-level comparison to the terminal and writes
`output/results/diff_<runA>_vs_<runB>.md`.

Key properties:

- **On-demand only.** The pipeline never invokes it (same philosophy as `analyze_runs.py`). The diff file is derived data — safe to delete anytime.
- **Read-only** with respect to the run JSONs, the runs index, and the runs summary.
- **Offline.** Pure local file analysis; no API calls.
- **Research purpose.** The measuring instrument for run-to-run stability and for model-swap experiments ("what happens to verdicts when I change the extractor model?"). It is the building block a future stability experiment (N repeated runs) will reuse.

## 2. Background — what is in a run JSON

Verified against the real files in `output/results/`:

- `policy_name` (str).
- `agent_models` (dict agent → model id, e.g. `{"extractor": "meta-llama/llama-3.3-70b-instruct", ...}`). **Absent in older runs** (e.g. `policy_long_run1.json`).
- `verified_clauses` (list): each has `clause_id` ("C1"…), `quote` (verbatim policy text), `section_reference`, etc.
- `finalizer_output`: `overall_label`, `confidence`, and `clause_assessments` (list): each has `clause_id`, `clause_label`, `justification`, … The assessment's own `quote` field is a *summary*, NOT the policy text — the verbatim quote lives only in `verified_clauses`.
- Counts differ even within one run (e.g. 61 verified clauses, 49 assessed).

**Critical fact:** clause IDs are assigned per run. `C1` in run A and `C1` in run B can be different sentences. Cross-run matching MUST use the verbatim quote text, never the clause ID.

## 3. Feature design

### 3.1 Files

| File | Action | Responsibility |
|---|---|---|
| `utils/run_diff.py` | Create | All logic: load runs, join clauses to labels, match across runs, build diff, render markdown, `main()` |
| `diff_runs.py` (project root) | Create | ~12-line runner: parse the two path args, call `utils.run_diff.main()` |
| `tests/test_run_diff.py` | Create | Standalone assert tests over synthetic run dicts |

Output file: `output/results/diff_<stem_a>_vs_<stem_b>.md` where `<stem_x>` is the JSON filename without extension. Each compared pair gets its own file; re-running the same comparison overwrites that file.

### 3.2 `utils/run_diff.py` — public functions

- **`load_run(path) -> dict`**
  Reads one run JSON. Raises ValueError (with a friendly message) when the file is missing, not valid JSON, or lacks the minimal keys (`policy_name`, `verified_clauses`, `finalizer_output`).

- **`clause_labels(run) -> list[dict]`**
  Within ONE run, joins `verified_clauses` to `finalizer_output.clause_assessments` by `clause_id` (IDs are consistent inside a single run). Returns one record per verified clause: `{"clause_id", "quote", "label"}` where `label` is the assessment's `clause_label`, or `"(unassessed)"` when the clause has no assessment.

- **`match_clauses(records_a, records_b) -> dict`**
  Cross-run matching by quote text:
  1. Normalize quotes (lowercase, collapse whitespace).
  2. Exact normalized match first.
  3. Fuzzy fallback for leftovers using rapidfuzz `ratio` with threshold ≥ 90 (rapidfuzz is already a project dependency via the verifier); each clause matches at most one counterpart (greedy best-score).
  Returns `{"pairs": [(rec_a, rec_b), ...], "only_a": [rec, ...], "only_b": [rec, ...]}`.

- **`build_diff(run_a, run_b, name_a, name_b) -> dict`**
  Pure function combining everything into one diff structure:
  - `policy_a`, `policy_b` and a `same_policy` flag (compared on `policy_name`).
  - `overall`: label A, label B, changed flag. `confidence`: same shape.
  - `models`: per agent (union of both runs' `agent_models` keys, alphabetical): model A, model B (`"N/A"` when the run lacks the key or the agent), changed flag. Plus `models_changed`: list of agents that differ (N/A on one side counts as differing).
  - `changed`: matched pairs whose labels differ. `unchanged_count`: matched pairs with equal labels (count only). `only_a` / `only_b`: unmatched clauses with their labels.
  - `clause_counts`: number of verified clauses in each run.

- **`render_diff_md(diff) -> str`**
  Renders the markdown document (see 3.4).

- **`main(path_a, path_b, output_dir="output/results") -> int`**
  Glue: load both runs → build → print markdown to terminal (with the same `sys.stdout.reconfigure(errors="replace")` Windows guard used by `runs_summary.main`) → write the diff file into `output_dir`. Returns 0 in all handled cases.

### 3.3 Matching rules (the heart)

- Match by verbatim quote, never by clause ID (see §2).
- Exact normalized match, then fuzzy (rapidfuzz ratio ≥ 90), greedy best-first, one-to-one.
- Unmatched clauses are reported, not dropped: "only in A" / "only in B" is itself a finding (extraction instability).
- Verified clauses without an assessment get label `"(unassessed)"` and participate in matching normally.

### 3.4 Output format (`diff_<a>_vs_<b>.md`)

```markdown
# Run Diff: <stem_a> vs <stem_b>

Policy: <policy_name>            ← or a loud warning when the policies differ
Overall label: <A> → <B> (same | ⚠ changed)
Confidence:    <A> → <B> (same | ⚠ changed)
Clauses:       <n_a> vs <n_b>
Models:        identical | ⚠ <k> agent(s) differ (<names>)

## Models
| Agent | <stem_a> | <stem_b> | |
|---|---|---|---|
| evaluator | openai/gpt-4o-mini | openai/gpt-4o-mini | same |
| extractor | meta-llama/llama-3.3-70b-instruct | openai/gpt-4o-mini | ⚠ changed |
...

## Label changes (<k>)
| Clause (start of quote) | <stem_a> | <stem_b> |
|---|---|---|
| "Data may be shared with partn…" | Compliant | Non-Compliant |
(or "_None._" when no labels changed)

## Only in <stem_a> (<k>)
- "quote snippet…" — <label>
(or "_None._")

## Only in <stem_b> (<k>)
(same shape)

## Unchanged
<k> clause(s) had the same label in both runs.
```

Quote snippets are truncated to ~60 characters with an ellipsis. Exact wording may be polished at implementation time; the structure (header verdicts, models table, change buckets, unchanged as count only) is fixed.

### 3.5 Different-policy comparison

When `policy_name` differs between the runs, the tool prints a prominent warning in the header (`⚠ WARNING: these runs are for DIFFERENT policies`) but still produces the diff — occasionally useful, never silently misleading.

## 4. Error handling

| Condition | Behavior |
|---|---|
| Either path missing / not valid JSON / not a run JSON | Print "Cannot diff: <reason>." Exit code 0; nothing written. |
| Run lacks `agent_models` (older runs) | Models column shows `N/A`; agents present in only one run also show `N/A`. Never crashes. |
| Clause without assessment | Label `"(unassessed)"`, included in matching. |
| Different policies | Loud warning, diff still produced (§3.5). |
| Empty `verified_clauses` on either side | Buckets render with counts of 0; header still produced. |

The tool writes exactly one file (the diff markdown) and modifies nothing else.

## 5. Testing

Standalone assert script (`python tests/test_run_diff.py`, prints `OK`; `sys.path` shim). No pytest. Synthetic run dicts built by a small helper.

- `clause_labels`: joins quote + label by clause_id; unassessed clause → `"(unassessed)"`.
- `match_clauses`: exact match pairs correctly; fuzzy match catches a near-identical quote (≥ 90); clearly different quotes land in only_a/only_b; one-to-one greediness.
- `build_diff`: flipped label lands in `changed`; same labels counted in `unchanged_count`; model table covers union of agents with changed flags; missing `agent_models` → all `N/A`; different `policy_name` → `same_policy` False.
- `render_diff_md`: header verdict lines, Models section with ⚠ on the changed agent, "_None._" for empty buckets, unchanged rendered as count only.
- `main` end-to-end: two temp JSON files → exit 0, diff file exists with expected lines; missing file → exit 0, nothing written.

## 6. Out of scope

- Justification/explanation text diffing; reflector/labeler internals.
- Comparing more than two runs at once (the future stability experiment will orchestrate pairwise diffs).
- Any pipeline integration or auto-invocation (on-demand only, like `analyze_runs.py`).
- CSV/HTML output; new third-party dependencies (stdlib + existing rapidfuzz only).
- Any change to `main.py`, `utils/runs_index.py`, `utils/runs_summary.py`, agents, or prompts.
