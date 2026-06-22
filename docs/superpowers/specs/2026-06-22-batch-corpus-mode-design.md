# Batch (Corpus) Mode — Design Spec

**Date:** 2026-06-22
**Status:** Approved for planning
**Scope:** Add a second way to run the pipeline — over a whole folder of policies in one command — that produces a batch-scoped side-by-side comparison file, in addition to the per-policy outputs that already exist. The existing single-policy run is unchanged. No change to the agents, prompts, evaluation logic, or any existing output.

---

## 1. Goal

Today the pipeline runs one policy per invocation:

```
python main.py --policy data/policies/policy_short.txt
python main.py --policy data/policies/policy_medium.txt
python main.py --policy data/policies/policy_long.txt
```

To survey a corpus of *distinct* policies (different applications/websites) you run `main.py` once per file by hand, then read the three results separately. The cumulative `runs_index` accumulates a row per run, but there is no single command to run a set together and no artifact scoped to just *this* survey.

This feature adds a **batch mode** — `python main.py --policy-dir <folder>` — that runs every supported policy in a folder back-to-back and writes one **batch-scoped comparison file** (the survey picture: every policy in the batch, side by side). The single-policy mode stays exactly as it is; batch mode is purely additive.

## 2. Background — what already exists (and is reused)

The "comparison picture" is mostly already built. This feature reuses it rather than duplicating it:

- **`utils/runs_index.py`** — `build_index_row(result)` maps one pipeline result dict to an ordered dict of 15 summary fields (policy, overall label, confidence, clauses, coverage, agreement, retries, disputed, anchoring, etc.). `append_run_to_index(result, output_dir)` appends one row per run to the cumulative `runs_index.md` + `runs_index.csv`. **Batch mode reuses `build_index_row` verbatim** — it introduces no new result-extraction logic.
- **`utils/runs_summary.py`** — `analyze_runs.py` produces aggregate Overall + Per-policy stats over the *cumulative* index. Out of scope here (see §7); batch-scoped aggregate is not part of this feature.
- **`utils/policy_loader.py`** — `SUPPORTED_EXTENSIONS` (the set `{.txt, .md, .html, .htm, .pdf, .docx}`) and `load_policy_text(path)`. Batch discovery filters by `SUPPORTED_EXTENSIONS`.
- **`main.py`** — `run_pipeline(client, policy_path, agent_models, blind_enabled)` runs one policy; `save_result(result, output_dir, run_index)` writes the per-policy JSON + markdown report and calls `append_run_to_index`. Batch mode calls these once per policy per run, unchanged.

Tests are standalone assert scripts (`tests/test_*.py`, run as `python tests/<file>.py`, print `OK`, exit non-zero on failure); the new pure logic is tested the same way and is auto-discovered by CI.

## 3. Feature design

### 3.1 Files

| File | Action | Responsibility |
|---|---|---|
| `utils/policy_loader.py` | Modify | Add `discover_policy_files(directory)` — find supported policy files in a folder |
| `utils/batch_comparison.py` | Create | Build the batch-scoped comparison `.md` and `.csv` from a list of batch entries (pure) |
| `main.py` | Modify | Mutually-exclusive `--policy` / `--policy-dir`; the batch loop; write the comparison files |
| `tests/test_policy_discovery.py` | Create | Tests for `discover_policy_files` |
| `tests/test_batch_comparison.py` | Create | Tests for the comparison renderers |

No change to agents, prompts, evaluation, the per-policy report, or the cumulative runs index.

### 3.2 CLI: two mutually-exclusive modes

`--policy` and `--policy-dir` become a **mutually-exclusive group, exactly one required** (argparse `add_mutually_exclusive_group(required=True)`).

- **Single (unchanged):** `python main.py --policy data/policies/policy_short.txt`
- **Batch (new):** `python main.py --policy-dir data/policies/`

All other flags (`--runs`, `--model`, the per-agent `--model-*`, `--no-blind-labeler`, `--output-dir`) apply unchanged in both modes.

### 3.3 Policy discovery — `discover_policy_files(directory: Path) -> list[Path]`

Pure function in `utils/policy_loader.py`:

- Returns the files **directly inside** `directory` (non-recursive) whose lowercased suffix is in `SUPPORTED_EXTENSIONS`.
- Sorted by filename, **case-insensitive**, for deterministic order.
- Files with unsupported extensions are skipped (not an error).
- Does not raise on an empty result — returns `[]`; the caller decides what to do (see §3.5).

### 3.4 Batch loop (in `main.py`)

When `--policy-dir` is given:

1. Resolve the directory. If it does not exist or is not a directory → print an error to stderr and `sys.exit(1)`.
2. `files = discover_policy_files(dir)`. If `files == []` → print `ERROR: no supported policy files (<exts>) found in <dir>` to stderr and `sys.exit(1)`.
3. For each `policy_path` in `files` (sorted), for `run_i` in `1..--runs`:
   - Call `run_pipeline(...)` then `save_result(..., run_index=run_i)` — **exactly the per-policy path that single mode uses**. Each policy still gets its own JSON, markdown report, and `runs_index` row.
   - Wrap each policy's run in a try/except (see §3.6) so one failure does not abort the batch.
   - Record a **batch entry** (see §3.5) for the comparison file.
4. After the loop, write the batch comparison files from the collected entries (§3.5).

Single mode (`--policy`) keeps its current code path verbatim — no comparison file is written.

### 3.5 Batch entry and the comparison file

Each policy-run produces one **entry** dict:

```python
{
    "policy": <policy stem, str>,
    "run_index": <int, 1-based>,
    "status": "ok" | "empty" | "failed",
    "row": <build_index_row(result) dict, or None on failure>,
    "error": <str message, or None>,
}
```

- `"ok"` — pipeline returned a normal result; `row` = `build_index_row(result)`.
- `"empty"` — pipeline returned the `_empty_result` shape (no verified clauses); `row` = `build_index_row(result)` (label/confidence cells will be `N/A`), `error` carries the empty-result note.
- `"failed"` — an exception was raised for this policy; `row` = `None`, `error` = the exception message.

`utils/batch_comparison.py` provides two **pure** renderers over `list[entry]`:

- `build_comparison_csv_rows(entries) -> list[list[str]]` — a header row plus one row per entry.
- `build_comparison_md(entries, batch_label: str) -> str` — a Markdown document: a title line referencing `batch_label` and a table, one row per entry.

**Columns** (a focused, readable subset, every value taken from the entry's `build_index_row` output — no new extraction):

| Column | Source |
|---|---|
| Policy | `entry["policy"]` |
| Run | `entry["run_index"]` |
| Status | `entry["status"]` (`ok` / `empty` / `failed`) |
| Overall label | `row["overall_label"]` or `—` |
| Confidence | `row["confidence"]` or `—` |
| Clauses | `row["clauses"]` or `—` |
| Disputed | `row["disputed"]` or `—` |
| Retries | `row["retries"]` or `—` |
| Agreement | `row["agreement_rate"]` or `—` |

For `failed`/`empty` entries with no usable metric, cells render the em dash `—`.

The files are written to `--output-dir` (default `output/results/`) as:

- `comparison_<batch_label>.md`
- `comparison_<batch_label>.csv`

**`batch_label`** is the `run_id` of the **first entry that has a `row`** (i.e. the first `ok` *or* `empty` entry — both carry `run_metadata`, so both have a `run_id`). The `run_id` is already a unique, filesystem-safe, time-based id produced by `build_run_metadata`. If every entry `failed` (no `row` at all), `batch_label` is the literal `"failed"`. This avoids introducing any new timestamp/`datetime` code and keeps the renderer pure (the label is passed in, not computed inside it).

### 3.6 Error handling

| Condition | Behavior |
|---|---|
| `--policy` and `--policy-dir` both given (or neither) | argparse rejects it (mutually-exclusive, required) → usage error, exit 2. |
| `--policy-dir` path missing / not a directory | Error to stderr, `sys.exit(1)`. |
| Directory has no supported files | Error to stderr, `sys.exit(1)`. |
| One policy raises mid-batch (unreadable file, pipeline error) | Caught; logged to the terminal; recorded as a `failed` entry; **the batch continues** with the remaining policies. |
| A policy yields no verified clauses (`_empty_result`) | Saved as today; recorded as an `empty` entry. |
| The comparison file cannot be written | Logged as a warning; the per-policy JSON/report/index already written remain the source of truth (mirrors `append_run_to_index`'s never-fatal contract). |

Single-policy mode keeps its existing error behavior (e.g. unreadable policy → `sys.exit(1)`), unchanged.

## 4. What it deliberately does NOT do

- **No change to single-policy mode**, the agents, prompts, evaluation metrics, the per-policy report, or the cumulative `runs_index`.
- **No recursion** into subfolders — only files directly inside `--policy-dir`.
- **No batch-scoped aggregate statistics** (averages, distributions). Per-policy aggregate already exists via `analyze_runs.py` over the cumulative index; a batch-scoped aggregate is a possible follow-up, not part of this feature (YAGNI).
- **No new LLM calls or models.** Batch reuses `run_pipeline` exactly; cost scales linearly with the number of policies × `--runs`.
- **No parallelism.** Policies run sequentially (simplest; avoids interleaved console output and rate-limit complexity).
- **No HTML output** (separate possible feature).

## 5. Testing / verification

Offline, no API key — consistent with the existing suite and CI:

- **`tests/test_policy_discovery.py`** — create a temp dir with a mix of supported and unsupported files (and a subfolder); assert `discover_policy_files` returns only the supported top-level files, sorted case-insensitively, and `[]` for an empty/all-unsupported dir.
- **`tests/test_batch_comparison.py`** — feed a hand-built list of entries (`ok`, `empty`, `failed`) into `build_comparison_csv_rows` and `build_comparison_md`; assert the header, one row per entry, correct cell values, `—` for missing metrics, the `failed`/`empty` status text, and that `batch_label` appears in the Markdown title.

Both print `OK` and exit non-zero on failure; CI auto-discovers them via the existing `tests/test_*.py` glob. The batch orchestration in `main.py` (the LLM loop) is verified by an offline reviewer reading the code and, optionally, a real corpus run by the user (out of CI, costs money).

## 6. Error/behavior summary

See §3.6. The guiding principle: batch mode is a convenience loop plus one pure rendering step over results the pipeline already produces; it never changes how a single policy is assessed, and one policy failing never loses the others.

## 7. Out of scope

- Batch-scoped aggregate stats (averages/distributions over just the batch) — `analyze_runs.py` covers cumulative aggregate; batch-scoped is a later follow-up.
- Recursive folder discovery.
- Parallel execution of policies.
- HTML/PDF comparison output.
- Any change to the assessment pipeline, prompts, agents, evaluation metrics, or the cumulative runs index/summary.
- A compare-two-runs CLI (separate `run_diff` exposure — a different feature).
