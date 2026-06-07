# Run Metadata & Stable Run IDs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stamp every pipeline run with a `run_metadata` provenance block (in both JSON and Markdown) and name output files by a unique timestamp `run_id` so runs never overwrite each other.

**Architecture:** A new pure-ish helper module `utils/run_metadata.py` builds the metadata block (timestamp-derived `run_id` + `utc_timestamp`, git commit info, policy content hash, settings). `main.py` builds the block once per run (right after verification, so the verified clause count is known), injects it as the first key of the result dict, and uses `run_id` for output filenames. `utils/report_generator.py` renders a small "Run Metadata" header in the Markdown report. No pipeline-logic changes.

**Tech Stack:** Python 3.12, stdlib only (`hashlib`, `subprocess`, `datetime`). No test framework in this repo — tests are standalone `assert` scripts run with `python tests/<file>.py` that print `OK` on success. Python is `python` on PATH. Windows + PowerShell (chain commands with `;`, not `&&`).

**Spec:** `docs/superpowers/specs/2026-06-07-run-metadata-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `utils/run_metadata.py` | Create | `build_run_metadata()` + helpers `_git_commit()`, `_sha256_hex()` |
| `tests/test_run_metadata.py` | Create | Standalone assert tests for the metadata builder |
| `main.py` | Modify | Build `run_metadata`, inject into result, name files by `run_id` |
| `utils/report_generator.py` | Modify | Render a "Run Metadata" block near the top of the report |

---

## Task 1: Create the run-metadata builder module (TDD)

**Files:**
- Create: `utils/run_metadata.py`
- Create: `tests/test_run_metadata.py`

- [ ] **Step 1: Write the failing tests first**

Create `tests/test_run_metadata.py` with EXACTLY this content. It uses the same `sys.path` shim as `tests/test_rubric_extraction.py` / `tests/test_label_panel.py` so it runs standalone from the project root. It hashes a real existing file (the test file itself) so `build_run_metadata` has valid bytes to read.

```python
"""Standalone assert tests for the run-metadata builder."""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from utils.run_metadata import build_run_metadata, _sha256_hex, _git_commit


def test_sha256_hex_is_deterministic_and_8_chars():
    a = _sha256_hex(b"hello world")
    b = _sha256_hex(b"hello world")
    assert a == b, "same bytes must hash to the same value"
    assert len(a) == 8, f"expected 8 hex chars, got {len(a)}: {a!r}"
    assert all(c in "0123456789abcdef" for c in a), f"not lowercase hex: {a!r}"


def test_sha256_hex_changes_with_content():
    assert _sha256_hex(b"hello world") != _sha256_hex(b"hello worle"), \
        "a one-byte change must change the hash"


def test_git_commit_shape():
    gc = _git_commit()
    assert isinstance(gc, dict)
    assert set(gc.keys()) == {"sha", "dirty"}
    assert isinstance(gc["sha"], str)
    assert gc["dirty"] is None or isinstance(gc["dirty"], bool)


def test_build_run_metadata_keys_and_types():
    md = build_run_metadata(
        policy_path=Path(__file__),       # a real file with bytes to hash
        temperature=0,
        blind_enabled=True,
        clause_count=71,
    )
    assert set(md.keys()) == {
        "run_id", "utc_timestamp", "git_commit", "policy_file",
        "policy_sha256", "temperature", "blind_enabled", "clause_count",
    }
    # run_id is a compact UTC timestamp: YYYYMMDDTHHMMSSZ
    assert re.fullmatch(r"\d{8}T\d{6}Z", md["run_id"]), md["run_id"]
    # utc_timestamp is ISO-8601 ending in Z
    assert md["utc_timestamp"].endswith("Z")
    # both come from the same instant: run_id is the timestamp with separators stripped
    compact = md["utc_timestamp"].replace("-", "").replace(":", "")
    assert md["run_id"] == compact, (md["run_id"], md["utc_timestamp"])
    assert isinstance(md["git_commit"], dict)
    assert md["policy_file"] == "test_run_metadata.py"
    assert len(md["policy_sha256"]) == 8
    assert md["temperature"] == 0
    assert md["blind_enabled"] is True
    assert md["clause_count"] == 71


if __name__ == "__main__":
    test_sha256_hex_is_deterministic_and_8_chars()
    test_sha256_hex_changes_with_content()
    test_git_commit_shape()
    test_build_run_metadata_keys_and_types()
    print("OK")
```

- [ ] **Step 2: Run the tests to confirm they FAIL**

Run: `python tests/test_run_metadata.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'utils.run_metadata'`.

- [ ] **Step 3: Implement `utils/run_metadata.py`**

Create `utils/run_metadata.py` with EXACTLY this content:

```python
"""
Run-metadata builder.

Assembles a small provenance block stamped onto every pipeline result so any
output can be traced back to WHEN it ran (utc_timestamp / run_id), WHICH code
version produced it (git_commit), and WHICH exact input it read (policy_sha256).

Pure stdlib. The git lookup degrades gracefully — metadata must never crash a run.
"""

import datetime
import hashlib
import subprocess
from pathlib import Path


def _sha256_hex(data: bytes) -> str:
    """Return the first 8 hex chars of the SHA-256 of `data`."""
    return hashlib.sha256(data).hexdigest()[:8]


def _git_commit() -> dict:
    """
    Return {"sha": <short hash>, "dirty": <bool>} for the current HEAD.

    Degrades to {"sha": "unknown", "dirty": None} if git is unavailable or this
    is not a git repository. Never raises.
    """
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if sha.returncode != 0:
            return {"sha": "unknown", "dirty": None}
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=5,
        )
        dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
        return {"sha": sha.stdout.strip(), "dirty": dirty}
    except Exception:
        return {"sha": "unknown", "dirty": None}


def build_run_metadata(
    policy_path: Path,
    temperature,
    blind_enabled: bool,
    clause_count: int,
) -> dict:
    """
    Build the run_metadata provenance block.

    Args:
        policy_path: Path to the policy file that was analyzed.
        temperature: The label-producing sampling temperature (config.LABELER_TEMPERATURE).
        blind_enabled: Whether the Blind Labeler tier ran this run.
        clause_count: Number of verified clauses evaluated this run.

    Returns:
        A dict with keys: run_id, utc_timestamp, git_commit, policy_file,
        policy_sha256, temperature, blind_enabled, clause_count.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    return {
        "run_id": now.strftime("%Y%m%dT%H%M%SZ"),
        "utc_timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": _git_commit(),
        "policy_file": policy_path.name,
        "policy_sha256": _sha256_hex(policy_path.read_bytes()),
        "temperature": temperature,
        "blind_enabled": blind_enabled,
        "clause_count": clause_count,
    }
```

- [ ] **Step 4: Run the tests to confirm they PASS**

Run: `python tests/test_run_metadata.py`
Expected output: `OK`

- [ ] **Step 5: Commit**

```bash
git add utils/run_metadata.py tests/test_run_metadata.py
git commit -m "feat: add run-metadata builder (run_id, git commit, policy hash)"
```

---

## Task 2: Wire run_metadata into the orchestrator and name files by run_id

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add the import**

In `main.py`, add this import alongside the other `from utils....` / `from agents....` imports near the top (after `from agents.finalizer import run_finalizer`, line ~32):

```python
from utils.run_metadata import build_run_metadata
```

- [ ] **Step 2: Import `LABELER_TEMPERATURE` from config**

In `main.py`, find the existing `from config import ...` line (it currently imports `DEFAULT_AGENT_MODELS`, `DEFAULT_MODEL`, `OPENROUTER_BASE_URL`, `ENABLE_BLIND_LABELER`). Add `LABELER_TEMPERATURE` to that same line. For example it becomes:

```python
from config import DEFAULT_AGENT_MODELS, DEFAULT_MODEL, OPENROUTER_BASE_URL, ENABLE_BLIND_LABELER, LABELER_TEMPERATURE
```

> Read the actual current import line and append `LABELER_TEMPERATURE`, preserving the existing names exactly. Do not duplicate the import.

- [ ] **Step 3: Build `run_metadata` right after verification**

In `run_pipeline` (in `main.py`), locate the verifier block:

```python
    print("\n[Verifier] Checking clause quotes against policy text...")
    verified_clauses, flagged_clauses = verify_clauses(
        extractor_output.get("extracted_clauses", []),
        policy_text,
    )
```

Immediately AFTER that block (and after any existing `print(f"  Verified: ...")` line that follows it), insert:

```python
    # Build run provenance once, now that the verified clause count is known.
    # Used by both the empty-result early return and the normal result below.
    run_metadata = build_run_metadata(
        policy_path=policy_path,
        temperature=LABELER_TEMPERATURE,
        blind_enabled=blind_enabled,
        clause_count=len(verified_clauses),
    )
```

> Note: there is a local variable `clause_count` earlier in `run_pipeline` (line ~76) that counts *extracted* clauses. Do NOT reuse it — the metadata's `clause_count` must be `len(verified_clauses)` (verified count), passed explicitly as shown.

- [ ] **Step 4: Pass run_metadata into the empty-result early return**

In `run_pipeline`, find the early return used when no clauses verify (around line ~94):

```python
        return _empty_result(policy_name, extractor_output, flagged_clauses)
```

Change it to pass the metadata:

```python
        return _empty_result(policy_name, extractor_output, flagged_clauses, run_metadata)
```

Then update the `_empty_result` function definition (around line ~343) from:

```python
def _empty_result(policy_name: str, extractor_output: dict, flagged_clauses: list) -> dict:
    return {
        "policy_name": policy_name,
        "error": "No verified clauses — all extracted clauses failed string-match verification.",
        "extractor_output": extractor_output,
        "flagged_clauses": flagged_clauses,
    }
```

to:

```python
def _empty_result(policy_name: str, extractor_output: dict, flagged_clauses: list,
                  run_metadata: dict) -> dict:
    return {
        "run_metadata": run_metadata,
        "policy_name": policy_name,
        "error": "No verified clauses — all extracted clauses failed string-match verification.",
        "extractor_output": extractor_output,
        "flagged_clauses": flagged_clauses,
    }
```

- [ ] **Step 5: Add run_metadata as the first key of the normal result dict**

In `run_pipeline`, find the normal `return { ... }` dict (around line ~256). Add `"run_metadata": run_metadata,` as the FIRST entry, before `"policy_name": policy_name,`:

```python
    return {
        "run_metadata": run_metadata,
        "policy_name": policy_name,
        "agent_models": agent_models,
        "extractor_output": extractor_output,
        "verified_clauses": verified_clauses,
        "flagged_clauses": flagged_clauses,
        "evaluator_output": evaluator_output,
        "reflector_a_initial": reflector_a_initial,
        "reflector_b_initial": reflector_b_initial,
        "initial_reflector_output": initial_reflector_output,   # merged
        "final_reflector_output": final_reflector_output,       # merged after retries
        "retry_count": retry_count,
        "finalizer_output": finalizer_output,
        "label_panel": label_panel,
        "blind_a_output": blind_a_output,
        "blind_b_output": blind_b_output,
    }
```

> Only the `"run_metadata": run_metadata,` line is added; leave every other key exactly as it is.

- [ ] **Step 6: Name output files by run_id in `save_result`**

In `main.py`, find `save_result` (around line ~277). Replace the two filename-building lines so they use the `run_id` from `run_metadata`, with a `-run{N}` suffix only when `--runs N>1` is used.

Current:

```python
    # JSON — full machine-readable output
    json_path = output_dir / f"{policy_name}_run{run_index}.json"
    json_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    # Markdown — human-readable report
    report_path = output_dir / f"{policy_name}_run{run_index}_report.md"
    generate_report(result, report_path)
```

Change to:

```python
    # Unique, time-based run id from run_metadata (falls back to run{N} if absent).
    run_id = result.get("run_metadata", {}).get("run_id") or f"run{run_index}"
    # Distinguish multiple runs within one invocation (--runs N>1).
    multi_suffix = f"-run{run_index}" if run_index > 1 else ""
    stem = f"{policy_name}_{run_id}{multi_suffix}"

    # JSON — full machine-readable output
    json_path = output_dir / f"{stem}.json"
    json_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    # Markdown — human-readable report
    report_path = output_dir / f"{stem}_report.md"
    generate_report(result, report_path)
```

> Leave the rest of `save_result` (the `_append_model_usage_log(result, output_dir, run_index)` call and the print lines) unchanged.

- [ ] **Step 7: Confirm `main.py` imports cleanly**

Run: `python -c "import main; print('OK')"`
Expected output: `OK`

- [ ] **Step 8: Commit**

```bash
git add main.py
git commit -m "feat: stamp run_metadata into result and name outputs by run_id"
```

---

## Task 3: Render the Run Metadata block in the Markdown report

**Files:**
- Modify: `utils/report_generator.py`

- [ ] **Step 1: Read run_metadata at the top of generate_report**

In `utils/report_generator.py`, inside `generate_report`, add this alongside the other `result.get(...)` lookups near the top (after the `label_panel = result.get("label_panel", {})` line, ~line 24):

```python
    run_metadata = result.get("run_metadata", {})
```

- [ ] **Step 2: Render the Run Metadata block right after the header table**

In `generate_report`, the header table ends with `lines.append(f"")` (the blank line after the `| **Human Review Required** | Yes |` row, ~line 46), immediately before the `## Clause Extraction` section's `lines.append(f"---")`.

Insert the following block at that point — after the header table's trailing blank line and BEFORE the `lines.append(f"---")` that opens Clause Extraction:

```python
    # -----------------------------------------------------------------------
    # Run Metadata (provenance)
    # -----------------------------------------------------------------------
    if run_metadata:
        gc = run_metadata.get("git_commit", {})
        sha = gc.get("sha", "unknown")
        commit_str = f"{sha} (dirty)" if gc.get("dirty") else sha
        lines.append(f"## Run Metadata")
        lines.append(f"")
        lines.append(f"| Field | Value |")
        lines.append(f"|---|---|")
        lines.append(f"| **Run ID** | {run_metadata.get('run_id', 'N/A')} |")
        lines.append(f"| **Timestamp (UTC)** | {run_metadata.get('utc_timestamp', 'N/A')} |")
        lines.append(f"| **Code commit** | `{commit_str}` |")
        lines.append(f"| **Policy file** | {run_metadata.get('policy_file', 'N/A')} |")
        lines.append(f"| **Policy SHA-256** | `{run_metadata.get('policy_sha256', 'N/A')}` |")
        lines.append(f"| **Temperature** | {run_metadata.get('temperature', 'N/A')} |")
        lines.append(f"| **Blind labeler** | {'enabled' if run_metadata.get('blind_enabled') else 'disabled'} |")
        lines.append(f"| **Clause count** | {run_metadata.get('clause_count', 'N/A')} |")
        lines.append(f"")
```

> When `run_metadata` is absent (older results), the block is skipped and the report renders exactly as before.

- [ ] **Step 3: Confirm the module imports**

Run: `python -c "import utils.report_generator; print('OK')"`
Expected output: `OK`

- [ ] **Step 4: Smoke-test the renderer with a synthetic result**

Run:

```bash
python -c "
from pathlib import Path
from utils.report_generator import generate_report
result = {
  'policy_name': 'demo', 'finalizer_output': {}, 'evaluator_output': {}, 'extractor_output': {},
  'final_reflector_output': {}, 'verified_clauses': [], 'flagged_clauses': [], 'label_panel': {},
  'run_metadata': {
    'run_id': '20260607T143022Z', 'utc_timestamp': '2026-06-07T14:30:22Z',
    'git_commit': {'sha': '72d8ed6', 'dirty': False},
    'policy_file': 'policy_short.txt', 'policy_sha256': 'a1b2c3d4',
    'temperature': 0, 'blind_enabled': True, 'clause_count': 71,
  },
}
generate_report(result, Path('output/_demo_run_metadata.md'))
txt = Path('output/_demo_run_metadata.md').read_text(encoding='utf-8')
assert '## Run Metadata' in txt and '20260607T143022Z' in txt and '72d8ed6' in txt and 'a1b2c3d4' in txt
print('OK')
"
```
Expected output: `OK`

Then delete the throwaway file (output/ is gitignored):

```bash
python -c "import os; os.remove('output/_demo_run_metadata.md')"
```

- [ ] **Step 5: Commit**

```bash
git add utils/report_generator.py
git commit -m "feat: render run metadata block in markdown report"
```

---

## Task 4: End-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Run the pipeline (blind labeler OFF to keep it fast/cheap)**

Run: `python main.py --policy data/policies/policy_short.txt --no-blind-labeler`

Expected: pipeline completes; the final `JSON saved to:` line shows a **timestamped** filename like `policy_short_20260607T143022Z.json` (NOT `policy_short_run1.json`).

- [ ] **Step 2: Confirm run_metadata is in the JSON with all keys**

Run:

```bash
python -c "
import json, glob, os
f = max(glob.glob('output/results/policy_short_*.json'), key=os.path.getmtime)
d = json.load(open(f, encoding='utf-8'))
md = d['run_metadata']
print('file:', os.path.basename(f))
print('keys:', sorted(md.keys()))
print('run_id:', md['run_id'])
print('git_commit:', md['git_commit'])
print('policy_sha256:', md['policy_sha256'])
print('blind_enabled:', md['blind_enabled'])
"
```
Expected: `keys:` lists all eight fields (`blind_enabled, clause_count, git_commit, policy_file, policy_sha256, run_id, temperature, utc_timestamp`); `run_id` is a timestamp; `git_commit` has a `sha`; `blind_enabled: False`.

- [ ] **Step 3: Confirm the Markdown report shows the Run Metadata block**

Run:

```bash
python -c "
import glob, os
f = max(glob.glob('output/results/policy_short_*_report.md'), key=os.path.getmtime)
t = open(f, encoding='utf-8').read()
assert '## Run Metadata' in t, 'missing Run Metadata section'
assert 'Run ID' in t and 'Code commit' in t and 'Policy SHA-256' in t
print('report OK:', os.path.basename(f))
"
```
Expected: `report OK: policy_short_<run_id>_report.md`

- [ ] **Step 4: Confirm two runs do NOT overwrite each other**

Run the pipeline a second time, then count distinct result files:

```bash
python main.py --policy data/policies/policy_short.txt --no-blind-labeler
```

Then:

```bash
python -c "
import glob
files = sorted(glob.glob('output/results/policy_short_*.json'))
print('distinct json files:', len(files))
for f in files[-3:]: print('  ', f)
assert len(files) >= 2, 'expected at least 2 distinct run files (overwrite bug should be fixed)'
print('OK - runs are preserved, not overwritten')
"
```
Expected: at least 2 distinct timestamped JSON files; `OK - runs are preserved, not overwritten`.

> If the two runs land in the same wall-clock second and produce the same `run_id`, that is acceptable for a single-invocation safety net only — these are two separate invocations, so their timestamps will differ. If you ever see a same-second collision across separate invocations, note it; it does not block this task.

- [ ] **Step 5: Final commit (cleanup, if any)**

```bash
git add -A
git commit -m "test: verify run metadata stamp and run-id filenames end-to-end" --allow-empty
```

---

## Notes for the implementer

- **No pytest in this repo.** Run test files directly with `python tests/<file>.py`; they print `OK` on success and raise `AssertionError` on failure.
- **Metadata must never crash a run.** `_git_commit()` swallows all errors and returns `{"sha": "unknown", "dirty": None}`. Do not add new failure modes.
- **Do not touch pipeline logic, prompts, agents, the retry loop, or `model_usage_log.md`.** This feature is provenance-only.
- **`clause_count` is the VERIFIED clause count** (`len(verified_clauses)`), not the extracted count — do not reuse the existing `clause_count` local in `run_pipeline`.
- **Backward compatibility:** the report block and filename logic both guard for a missing `run_metadata` so older result JSONs still render and save.
