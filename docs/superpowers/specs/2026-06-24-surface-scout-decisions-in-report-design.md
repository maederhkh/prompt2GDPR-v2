# Surface Scout Decisions in the Human Report — Design Spec

**Date:** 2026-06-24
**Status:** Approved for planning
**Scope:** Add a "Section Scout" subsection to each run's human-readable `report.md`, surfacing the auditable scout decisions (`include` / `maybe_include` / `exclude`, each with a reason and confidence) that are already saved in the run JSON but currently invisible in the report. Reporting-only change: no pipeline, agent, prompt, JSON, or schema changes.

---

## 1. Goal

The Scout (Agent 1, Pass 1) was recently upgraded to emit **auditable section decisions**: every policy section is classified as `include`, `maybe_include`, or `exclude`, and each decision carries a `reason`, matched `signals`, and a `confidence` level. This is stored in the run JSON under `extractor_output.scout_report`.

Today those decisions are only visible to someone who opens the raw JSON. The human-readable `report.md` shows the *result* of extraction (verified/flagged clause counts) but not *why the Scout looked where it looked* — and, crucially, not what it chose to skip. This feature surfaces the scout decisions in the report so a human reviewer can audit them directly.

## 2. Background — what already exists (and is reused)

- **`agents/extractor.py`** — `_run_scout` returns `(selected_headings, scout_report)`. The `scout_report` dict is attached to the extractor result under the key `scout_report` and flows into the run result as `extractor_output.scout_report`. Its shape:
  ```python
  {
    "schema_version": "section_decisions_v1",
    "include":       [decision, ...],
    "maybe_include": [decision, ...],
    "exclude":       [decision, ...],
  }
  ```
  Each `decision` is:
  ```python
  {
    "heading":    str,                       # section heading (or short description)
    "reason":     str,                       # short free-text rationale
    "signals":    list[str],                 # matched purpose-limitation cues
    "confidence": "high" | "medium" | "low", # already normalized to this set
  }
  ```
  The normalizer (`_normalize_scout_decision` / `_normalize_scout_response`) guarantees: `heading` and `reason` are strings, `confidence` is one of the three valid values, `signals` is a list of strings. An empty/failed scout yields `_empty_scout_report()` (all three buckets empty).

- **Single-pass fallback** — `_run_single_pass` (used when the Scout fails or section boundaries can't be located) returns extractor output **without** a `scout_report` key.

- **`utils/report_generator.py`** — `generate_report(result, out_path)` builds the markdown report by appending strings to a `lines` list and writing the file. It already reads `extractor = result.get("extractor_output", {})` and renders a `## Clause Extraction` section. This is the only file this feature touches.

- **Tests** are standalone assert scripts (`tests/test_*.py`, run as `python tests/<file>.py`, print `OK`, exit non-zero on failure); CI auto-discovers them via the `tests/test_*.py` glob.

## 3. Feature design

### 3.1 Files

| File | Action | Responsibility |
|---|---|---|
| `utils/report_generator.py` | Modify | Add a pure `_render_scout_section(scout_report)` helper; call it inside the existing `## Clause Extraction` block |
| `tests/test_report_scout_section.py` | Create | Unit tests for `_render_scout_section` |

No change to agents, prompts, evaluation, the JSON output, or the cumulative runs index.

### 3.2 The pure renderer — `_render_scout_section(scout_report) -> list[str]`

A module-level function in `utils/report_generator.py` that takes a `scout_report` dict (or `None`) and returns a list of markdown lines (the subsection), or an **empty list** when there is nothing to show. Keeping it pure (returns lines, writes nothing) makes it directly unit-testable without touching the filesystem.

Behavior:

1. **Guard.** If `scout_report` is falsy (`None`, `{}`), or all three buckets (`include`, `maybe_include`, `exclude`) are empty/missing, return `[]` — the subsection is omitted entirely (no empty heading).
2. **Heading + counts.** Otherwise emit:
   - `### Section Scout`
   - blank line
   - `- Scout decisions: **{Ni}** included, **{Nm}** maybe-include, **{Nx}** excluded`
     (counts are the lengths of the `include`, `maybe_include`, `exclude` lists respectively)
   - blank line
3. **Table.** A single markdown table with header `| Section | Decision | Confidence | Reason |` and the separator row, followed by one row per decision, grouped in this order: all `include` rows, then all `maybe_include`, then all `exclude`. Within each bucket, preserve the order the decisions appear in the list.
   - The `Decision` column shows the bucket label: `include` → `include`, `maybe_include` → `maybe`, `exclude` → `exclude`.
   - The `Section` column shows the decision's `heading`.
   - The `Confidence` column shows the decision's `confidence`.
   - The `Reason` column shows the decision's `reason`.
4. Trailing blank line after the table.

### 3.3 Cell sanitization

`heading` and `reason` are model-generated free text and can legitimately contain a pipe `|` or a newline, either of which would break the markdown table. The helper sanitizes every cell value with a small inline rule before placing it in a table row:

- replace `|` with `\|`
- replace any newline (`\n`, `\r`) with a single space
- (counts and the fixed `Decision`/`Confidence` values need no sanitization, but applying the same helper to all cells is harmless and simplest)

This is applied only to the cells the renderer emits; it does not alter the stored `scout_report`.

### 3.4 Wiring into `generate_report`

Inside `generate_report`, within the existing `## Clause Extraction` section (after the existing extraction bullets, before the `---` that precedes `## Clause Assessments`), read the scout report and extend `lines`:

```python
scout_report = extractor.get("scout_report")
lines.extend(_render_scout_section(scout_report))
```

Because `_render_scout_section` returns `[]` when there's nothing to show, runs without a `scout_report` (older runs, single-pass fallback) render exactly as they do today.

## 4. What it deliberately does NOT do

- **No JSON / schema change.** The `scout_report` is already in the result; this only reads it.
- **No runs_index columns** (Approach C from brainstorming — out of scope; would touch the `FIELDS` schema and migration path).
- **No `signals` column** in the table (kept compact; reason + confidence carry the audit value).
- **No change to single-pass behavior, the pipeline, agents, prompts, or any other report section.**
- **No batch-comparison change.**

## 5. Testing / verification

Offline, no API key — consistent with the existing suite and CI. `tests/test_report_scout_section.py` (standalone assert script) imports `_render_scout_section` and asserts:

1. **Full report:** given a `scout_report` with at least one decision in each bucket, the returned lines include the `### Section Scout` heading, the counts line with the correct numbers, the table header row, and one data row per decision, grouped include → maybe → exclude.
2. **Decision labels:** a `maybe_include` decision renders the literal `maybe` in its Decision cell; an `exclude` decision renders `exclude`.
3. **Pipe / newline escaping:** a decision whose `reason` contains `|` and a newline renders that cell with `\|` and no raw line break (the table is not broken).
4. **Empty / missing report:** `_render_scout_section(None)` and `_render_scout_section({...all buckets empty...})` both return `[]`.

The function prints `OK` on success via the `__main__` block; failure raises and exits non-zero. CI auto-discovers it via the existing glob.

## 6. Out of scope

- runs_index / runs_summary changes.
- The `signals` field in the rendered table.
- Any change to how the Scout itself classifies sections.
- Surfacing the Pass-3 `self_check_report` (a separate possible follow-up).
