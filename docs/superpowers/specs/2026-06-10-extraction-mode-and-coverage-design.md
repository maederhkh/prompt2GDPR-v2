# Extraction Mode Flag + Coverage-Confidence Column — Design Spec

**Date:** 2026-06-10
**Status:** Approved for planning
**Scope:** Record which extraction path ran, surface it, and turn it into an honest coverage-confidence signal. Small, well-bounded; touches the extractor lightly (two literal assignments), the report, and the runs index.

---

## 1. Goal

Make it visible, per run, **which extraction path was used** and how confident we can be about clause coverage:

- The extractor runs **two-pass** (Scout → Deep Extractor per section → self-check; thorough, no clause cap) or, when the Scout finds no usable sections, falls back to **single-pass** (one LLM call over the whole policy, capped at 15 clauses).
- Today there is **no explicit flag** recording which ran — it can only be inferred from `extraction_notes` text or the presence of `sections_processed`/`self_check_report` keys.

This feature adds:
1. An explicit **`extraction_mode`** field (`two_pass` / `single_pass`) in the extractor result (→ JSON).
2. An **Extraction mode + Coverage confidence** line in the per-run **markdown report**.
3. A **`coverage`** column in the runs index (`.csv` / `.md`) with values **`high`** / **`low`**, derived from the mode.

### 1.1 Why "high/low" (coverage *confidence*), not "full/partial"

Two-pass is more thorough but **not a guarantee**: the self-check that catches missed clauses uses fuzzy paragraph matching (a heuristic, score ≥ 60), not proof. So even a clean two-pass run could miss something. Labeling it `full` would overclaim certainty we do not have. The column therefore expresses **coverage confidence**:

- **two-pass → `high`** (thorough; all scouted sections; no 15-clause cap)
- **single-pass → `low`** (fallback; capped at 15 clauses)

This also corrects the current report, which flatly prints "Coverage: Complete" off a hard-coded flag.

---

## 2. Background — current behavior

- `agents/extractor.py`:
  - Two-pass result dict (built inline in `run_extractor`) hard-codes `"coverage_complete": True` and includes `sections_processed`, `self_check_report`, and a descriptive `extraction_notes`. It does **not** set an `extraction_mode`.
  - `_run_single_pass(...)` returns the raw parsed LLM JSON (`policy_name`, `extracted_clauses`, `extraction_notes`, model-self-reported `coverage_complete`). No `extraction_mode`, no `sections_processed`/`self_check_report`.
- `utils/report_generator.py` (~lines 77-80) renders `Coverage: Complete / Incomplete` from `coverage_complete` (always "Complete" on the two-pass path), plus `extraction_notes`.
- `utils/runs_index.py` writes a **14-field** index and already backs up an on-disk file to `.bak` when its header no longer matches `FIELDS` (so a 14 → 15 schema change needs no new migration code).
- The result dict exposes the extractor output at `result["extractor_output"]`.

---

## 3. Feature changes

### 3.1 `extraction_mode` in the extractor result

In `agents/extractor.py`:
- **Two-pass path:** add `"extraction_mode": "two_pass"` to the result dict assembled in `run_extractor` (alongside the existing `coverage_complete`/`sections_processed` keys).
- **Single-pass path:** in `_run_single_pass`, set `data["extraction_mode"] = "single_pass"` on the parsed output before returning it.

No other extractor behavior changes. Both literal assignments; no logic branches added.

### 3.2 Markdown report

In `utils/report_generator.py`, replace the single `Coverage: Complete/Incomplete` line with two lines derived from `extractor.get("extraction_mode")`:

```
- Extraction mode: <two-pass | single-pass (fallback) | unknown>
- Coverage confidence: <high | low | unknown>
```

Mapping:
- `two_pass` → mode "two-pass", confidence "high"
- `single_pass` → mode "single-pass (fallback)", confidence "low"
- missing/other → mode "unknown", confidence "unknown" (older results without the flag)

The existing `extraction_notes` line is kept as-is.

### 3.3 Coverage column in the runs index (14 → 15 fields)

Insert **`coverage`** immediately **after `clauses`**:

- **`FIELDS`** (15): `run_id, date, policy, policy_sha256, commit, overall_label, confidence, clauses, coverage, agreement_rate, retries, disputed, blind, anchoring_a, anchoring_b`.
- **`MD_HEADERS`** (matching): `Run ID, Date (UTC), Policy, Policy hash, Commit, Overall label, Confidence, Clauses, Coverage, Agreement, Retries, Disputed, Blind, Anchoring A, Anchoring B`.

`build_index_row` derives `coverage` from the extraction mode:

```
extractor_output = result.get("extractor_output", {}) or {}
mode = extractor_output.get("extraction_mode")
coverage = {"two_pass": "high", "single_pass": "low"}.get(mode, EM_DASH)
```

- `high` when two-pass, `low` when single-pass, `—` (EM_DASH) when the mode is absent/unknown (older or degenerate results).

### 3.4 Backward-compatibility (reuse existing mechanism)

No new code: when the 15-field writer first runs against an existing 14-field `runs_index.csv`, the header mismatch triggers `append_run_to_index`'s existing backup path — old `runs_index.csv`/`.md` are renamed to `.bak`, a fresh 15-column index starts, old rows preserved in `.bak`.

---

## 4. Components and responsibilities

| File | Change |
|---|---|
| `agents/extractor.py` | Set `extraction_mode` in both paths (two literal assignments) |
| `utils/report_generator.py` | Replace the coverage line with Extraction-mode + Coverage-confidence lines |
| `utils/runs_index.py` | `FIELDS`/`MD_HEADERS` → 15; `build_index_row` derives `coverage` from mode |
| `tests/test_runs_index.py` | Update for 15-field schema; assert `coverage` high/low/— |
| `tests/test_extraction_mode.py` (new) | Drive `run_extractor` down both paths via a fake client; assert `extraction_mode` |

---

## 5. Data flow

```
run_extractor(...)
  · Scout finds sections → two-pass → result["extraction_mode"] = "two_pass"
  · Scout finds none      → _run_single_pass → data["extraction_mode"] = "single_pass"
        │
        ▼
result["extractor_output"]["extraction_mode"]
        ├─→ report_generator: "Extraction mode" + "Coverage confidence" lines  (MD)
        └─→ build_index_row: coverage = high/low/—  → runs_index.csv/.md       (index)
```

---

## 6. Error handling

- **Missing `extraction_mode`** (older results, degenerate runs) → report shows "unknown"; index `coverage` is `—`. No crash.
- Index writing keeps its existing `try/except` guard (never crashes a run).
- The single-pass model self-report `coverage_complete` is left in the JSON untouched (informational); the user-facing confidence is driven by the objective mode, not that flag.

---

## 7. Testing

Standalone assert scripts (no pytest; run `python tests/<file>.py`, prints `OK`; `sys.path.insert(0, ...)` shim).

**`tests/test_runs_index.py` (extend):**
- `FIELDS` has 15 entries with `coverage` immediately after `clauses`.
- `build_index_row` on a result with `extractor_output={"extraction_mode": "two_pass"}` → `row["coverage"] == "high"`.
- `extractor_output={"extraction_mode": "single_pass"}` → `row["coverage"] == "low"`.
- no `extraction_mode` → `row["coverage"] == "—"` (EM_DASH).
- Existing append/newest-first/backup tests updated for the 15-field header.

**`tests/test_extraction_mode.py` (new) — uses a minimal fake OpenAI-style client (no network):**
- A `FakeClient` whose `chat.completions.create(...)` returns canned JSON per call. Single-pass: Scout returns `{"relevant_sections": []}` → `run_extractor` calls `_run_single_pass`, whose canned response is a valid extractor JSON; assert `result["extraction_mode"] == "single_pass"`.
- Two-pass: Scout returns one heading that exists as a line in a crafted `policy_text`; the section-extractor call returns one clause; the self-check call returns no new paragraphs; assert `result["extraction_mode"] == "two_pass"` (and that `sections_processed` is present).
- (Report rendering: a lightweight check that `generate_report`/its helper emits "Extraction mode:" and "Coverage confidence:" lines for a synthetic result with `extraction_mode` set — may be folded into this file or an offline one-liner during verification.)

**Offline end-to-end (verification, no API):** drive `main.save_result` with two synthetic results (one `two_pass`, one `single_pass`) and assert the index `coverage` column reads `high` then `low`, and that the rendered report contains the new lines.

---

## 8. Out of scope

- **Feature B — runs analysis helper** (aggregate stats over `runs_index.csv`): deferred to a separate spec/plan (planned for tomorrow).
- No change to *how* the extractor decides coverage beyond recording the path it took (no new heuristic for "did two-pass truly cover everything").
- No per-clause export, cross-run diff, batch `--all`, or `.xlsx`.
- No new third-party dependencies.
- No changes to prompts, the retry loop, agents other than the two literal `extraction_mode` assignments, or run filenames.
