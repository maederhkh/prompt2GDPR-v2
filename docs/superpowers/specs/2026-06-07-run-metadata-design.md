# Run Metadata & Stable Run IDs — Design Spec

**Date:** 2026-06-07
**Status:** Approved for planning
**Scope:** Small, self-contained traceability step. No pipeline-logic changes.

---

## 1. Goal

Make every pipeline run **traceable** by:

1. Stamping each run's output with a `run_metadata` block that records *when* it ran, *which code version* produced it, and *which exact input* it read.
2. Giving each run a unique, time-based `run_id` used for output filenames, so successive runs **never overwrite each other** (a confirmed gap: two separate `python main.py` invocations both wrote `policy_short_run1.json`, the second silently overwriting the first, because `run_index` resets to `1` on every invocation).

The `run_metadata` block appears in **both** output formats: as a top-level key in the result JSON and as a short "Run Metadata" header in the Markdown report.

This is a deliberately small step. It is the foundation other traceability work (audit logs, experiment tracking) could later build on, but none of that is in scope here.

---

## 2. Background — current behavior

- `save_result(result, output_dir, run_index=1)` (`main.py`) writes `{policy_name}_run{run_index}.json` and `{policy_name}_run{run_index}_report.md`.
- `run_index` comes from the `--runs` loop (`for run_i in range(1, args.runs + 1)`), so it **resets to `1` on every program invocation**. Two separate invocations therefore collide on `..._run1.json`.
- The result dict already contains `policy_name` and `agent_models` (the per-agent model slugs). These are **not** duplicated by this feature.
- `_append_model_usage_log()` already appends a per-run row (index, timestamp, policy, models, overall label) to a cumulative `model_usage_log.md`. This feature does **not** modify that log.

---

## 3. The `run_metadata` block — complete field reference

`run_metadata` is a JSON object with exactly the following keys. Every key is explained in full below: what it is, how it is produced, an example value, and why it matters for traceability.

```json
"run_metadata": {
  "run_id": "20260607T143022Z",
  "utc_timestamp": "2026-06-07T14:30:22Z",
  "git_commit": { "sha": "72d8ed6", "dirty": false },
  "policy_file": "policy_short.txt",
  "policy_sha256": "a1b2c3d4",
  "temperature": 0,
  "blind_enabled": true,
  "clause_count": 71
}
```

### 3.1 `run_id` — the unique identity of this run
- **Type:** string.
- **Format:** `YYYYMMDDTHHMMSSZ` (compact UTC timestamp, no separators), e.g. `20260607T143022Z`. The trailing `Z` marks it as UTC ("Zulu") time.
- **How produced:** derived from a single UTC timestamp captured once at the start of `build_run_metadata` (the same instant that produces `utc_timestamp`), formatted with `strftime("%Y%m%dT%H%M%SZ")`.
- **Why it matters:** this is the run's primary key. It is used verbatim in the output filenames (`{policy_name}_{run_id}.json`), so it is what guarantees runs do not overwrite each other. Because it is a timestamp, filenames also sort chronologically. The same `run_id` stored inside the JSON lets you match a result back to its file and vice versa.
- **Multiple runs in one invocation:** when `--runs N` (N > 1) is used, runs may share the same wall-clock second. To keep them distinct on disk, the filename appends `-run{i}` for the i-th run of the invocation (e.g. `policy_short_20260607T143022Z-run2.json`). The `run_id` value itself stays the timestamp.

### 3.2 `utc_timestamp` — *when* the run happened
- **Type:** string.
- **Format:** ISO 8601 in UTC, e.g. `2026-06-07T14:30:22Z`.
- **How produced:** from the same captured timestamp as `run_id`, formatted human-readably (`strftime("%Y-%m-%dT%H:%M:%SZ")`).
- **Why UTC (not local Munich time):** UTC has no time zones and no daylight-saving ambiguity, so a timestamp is unambiguous and directly comparable across machines and collaborators. A local "16:30" could mean two different instants depending on the season; `14:30:22Z` cannot.
- **Why it matters:** gives every result a definitive "born-on" instant for chronological ordering and for correlating a result with external events (e.g. when a model provider changed something).

### 3.3 `git_commit` — *which version of the code* produced the run
- **Type:** object `{ "sha": string, "dirty": boolean | null }`.
- **`sha`:** the short Git commit hash of `HEAD` at run time (e.g. `72d8ed6`). Git stores code as a chain of commits, each identified by a unique SHA hash; this records exactly which commit the pipeline ran from.
- **`dirty`:** `true` if there were **uncommitted changes** in the working tree when the run executed (edits not yet captured in a commit); `false` if the working tree was clean. A `dirty: true` run is a reproducibility warning — the committed `sha` does not fully describe the code that ran.
- **How produced:** `_git_commit()` shells out to `git rev-parse --short HEAD` for the SHA and inspects `git status --porcelain` (non-empty output ⇒ dirty).
- **Failure behavior:** if Git is not installed or the directory is not a Git repository, `_git_commit()` returns `{ "sha": "unknown", "dirty": null }` and the pipeline continues normally. The stamp is metadata only and must never crash a run.
- **Why it matters:** this is the single most valuable traceability field. It ties every result to an exact, recoverable code state. Change a prompt or the rubric, rerun, and the new result carries a different `sha`, so you can always tell which code produced which numbers.

### 3.4 `policy_file` — *which input file* was read
- **Type:** string.
- **Value:** the policy file's name (basename), e.g. `policy_short.txt`.
- **How produced:** `policy_path.name`.
- **Why it matters:** records which input document the run analyzed, in human-readable form. (On its own a filename is not enough — see `policy_sha256` — but it is the friendly label.)

### 3.5 `policy_sha256` — *which exact input content* was read
- **Type:** string.
- **Value:** the first 8 hex characters of the SHA-256 hash of the policy file's bytes, e.g. `a1b2c3d4`.
- **How produced:** `_sha256_hex(policy_path.read_bytes())`, truncated to 8 characters.
- **What SHA-256 is:** a hashing function that maps any input to a fixed-length fingerprint. The same content always yields the same fingerprint; changing even one character changes it completely.
- **Why a hash and not just the filename:** a file named `policy_short.txt` can be edited while keeping its name. The hash detects such silent content changes, so two runs with matching `policy_sha256` are guaranteed to have read identical input — making "same policy →" comparisons trustworthy.
- **Why 8 characters:** 8 hex chars (32 bits) is more than enough to distinguish the handful of policy files in this research setting, while keeping the value short and readable. (Full collisions are irrelevant at this scale.)

### 3.6 `temperature` — the sampling setting used by label-producing calls
- **Type:** number.
- **Value:** the value of `LABELER_TEMPERATURE` from `config.py` (currently `0`).
- **How produced:** read directly from `config.LABELER_TEMPERATURE`.
- **Why it matters:** temperature controls output randomness. Recording it documents that label-producing calls (evaluator, reflectors, blind labelers) ran deterministically (temperature 0), which is essential context for interpreting and reproducing the anchoring measurement.

### 3.7 `blind_enabled` — whether the anchoring measurement ran
- **Type:** boolean.
- **Value:** `true` if the Blind Labeler tier ran this run, `false` if it was disabled (via `--no-blind-labeler` or `ENABLE_BLIND_LABELER = False`).
- **How produced:** the `blind_enabled` argument already threaded into `run_pipeline`.
- **Why it matters:** tells a reader at a glance whether this run includes blind-vs-anchored data and an anchoring summary, or only evaluator + reflector labels. Distinguishes the two run modes without inspecting the label panel.

### 3.8 `clause_count` — the size of this run
- **Type:** integer.
- **Value:** the number of verified clauses the pipeline evaluated, e.g. `71`.
- **How produced:** `len(verified_clauses)` at the point the metadata is built.
- **Why it matters:** a quick size indicator for comparing runs (a 71-clause run and a 12-clause run are not comparable at face value) and for sanity-checking that extraction produced a plausible clause set.

### 3.9 Deliberately excluded fields
- **Per-agent model slugs** — already present in `result["agent_models"]`; duplicating them would violate DRY.
- **Overall label / confidence** — already present in `result["finalizer_output"]`. Not mirrored into `run_metadata` to keep the block focused on *provenance* (when / which code / which input / which settings) rather than *results*.

---

## 4. Components and responsibilities

### 4.1 New file: `utils/run_metadata.py`
A small, mostly-pure module. Responsibilities:

- `build_run_metadata(policy_path, temperature, blind_enabled, clause_count) -> dict`
  - Captures one UTC timestamp; derives `run_id` and `utc_timestamp` from it.
  - Calls `_git_commit()` and `_sha256_hex(policy_path.read_bytes())`.
  - Returns the complete `run_metadata` dict described in §3.
- `_git_commit() -> dict` — returns `{"sha", "dirty"}`; degrades to `{"sha": "unknown", "dirty": null}` on any failure (not a repo, git missing, subprocess error). Never raises.
- `_sha256_hex(data: bytes) -> str` — returns the first 8 hex chars of `sha256(data)`. Pure function, independently testable without a file or repo.

### 4.2 Modified: `main.py`
- In `run_pipeline`, build `run_metadata` (all inputs — `policy_path`, `LABELER_TEMPERATURE`, `blind_enabled`, `len(verified_clauses)` — are already in scope) and insert it as the **first key** of the returned result dict.
- The `_empty_result(...)` early-return path also receives a `run_metadata` block (built with `clause_count = 0`) so that *every* result, including the no-verified-clauses case, is traceable.
- `save_result(result, output_dir, run_index=1)` reads `result["run_metadata"]["run_id"]` and names files `{policy_name}_{run_id}.json` and `{policy_name}_{run_id}_report.md`. When `run_index > 1` (i.e. `--runs N`), it appends `-run{run_index}` before the extension to keep within-invocation runs distinct.

### 4.3 Modified: `utils/report_generator.py`
- `generate_report` reads `result.get("run_metadata", {})` and, when present, renders a short **"Run Metadata"** block near the top of the report (before the existing body), showing: timestamp, commit (`sha` + a "(dirty)" marker when applicable), policy file + hash, temperature, blind-enabled, clause count. When absent, the report renders exactly as today (backward compatible).

---

## 5. Data flow

```
run start
  → capture ONE utc timestamp
      → run_id           (YYYYMMDDTHHMMSSZ)
      → utc_timestamp    (ISO-8601 Z)
  → _git_commit()        ({sha, dirty})
  → _sha256_hex(policy bytes)  (policy_sha256)
  → settings             (temperature, blind_enabled, clause_count, policy_file)
  → run_metadata dict
      → result["run_metadata"]
          → JSON file, named {policy_name}_{run_id}.json
          → Markdown report "Run Metadata" header
```

---

## 6. Error handling

- **Git absent / not a repository / subprocess failure:** `_git_commit()` returns `{"sha": "unknown", "dirty": null}`. The run proceeds. No traceability field is allowed to abort a pipeline run.
- **Policy file already validated upstream:** the pipeline already fails earlier if the policy file cannot be read, so `policy_sha256` computation does not introduce a new failure mode.
- **Backward compatibility:** older result JSONs without `run_metadata` still render — the report block is guarded by `if run_metadata`.

---

## 7. Testing

This repo has no pytest; tests are standalone `assert` scripts run as `python tests/<file>.py`, printing `OK` on success.

`tests/test_run_metadata.py`:
- `_sha256_hex` is deterministic: same bytes → same 8-char hash; a one-byte change → a different hash.
- `run_id` matches the regex `^\d{8}T\d{6}Z$`, and `utc_timestamp` ends with `Z`; both derive from the same instant (the date portion matches).
- `build_run_metadata(...)` returns all eight keys of §3 with correct types, a well-formed `git_commit` dict (`sha` is a string, `dirty` is bool-or-None), and the `temperature`/`blind_enabled`/`clause_count` values it was given.
- Smoke check: `generate_report` on a synthetic result containing a `run_metadata` block produces output containing a "Run Metadata" heading and the commit SHA.

---

## 8. Out of scope (keeping this a little step)

- No experiment-tracking database or runs index.
- No full audit log of individual LLM calls.
- No changes to `model_usage_log.md`.
- No pipeline-logic, prompt, or agent changes.
- No prompt/rubric versioning fields (could be a future addition once prompts are versioned).
