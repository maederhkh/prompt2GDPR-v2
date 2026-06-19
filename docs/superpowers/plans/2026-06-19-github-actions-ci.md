# GitHub Actions CI for Offline Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make GitHub automatically run the project's offline test suites on every push and pull request, and show a pass/fail badge in the README.

**Architecture:** Add one GitHub Actions workflow file (`.github/workflows/tests.yml`) that, on a fresh Ubuntu runner, installs Python 3.12 + the project's declared dependencies and runs every `tests/test_*.py` (auto-discovered) so any failing suite fails the job. Add a status badge to `README.md`. No application code, pipeline, or test is changed.

**Tech Stack:** GitHub Actions (`actions/checkout@v4`, `actions/setup-python@v5`), Python 3.12, the 8 dependencies from `pyproject.toml`. The repo is public, so Actions minutes are free. Dev machine is Windows + PowerShell; the CI runner is Ubuntu (bash). `docs/` is gitignored (use `git add -f` for docs only); `.github/` is NOT gitignored and stages normally.

## Global Constraints

- Python version: **3.12 only** (the project requires `>=3.12`). No matrix.
- Triggers: **`push` and `pull_request`** (both).
- **Offline only.** CI must never run `main.py`, never use an API key, never add a secret, never make an LLM/network-paid call. Only the offline `tests/test_*.py` suites run.
- Tests are **standalone assert scripts** run as `python tests/<file>.py` (NOT pytest); they print `OK` and exit non-zero on failure.
- Test discovery must be a **glob over `tests/test_*.py`** so new test files are picked up with no workflow edit.
- The dependency install list **mirrors `[project].dependencies` in `pyproject.toml`** verbatim: `beautifulsoup4 json-repair openai pydantic pypdf python-docx python-dotenv rapidfuzz`. Carry a comment saying so. (Accepted trade-off: list lives in two places; drift fails CI loudly with an ImportError.)
- Do NOT install the project as a package (`pip install .`): there is no `[build-system]` and the layout is flat. The test suites' `sys.path` shim makes modules importable from the repo root.
- Do NOT commit `.claude/settings.local.json` (intentionally modified, must stay unstaged). Only `git add` the exact files named in each commit step.
- Do NOT modify the pipeline, agents, prompts, utils, or any existing test.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `.github/workflows/tests.yml` | Create | The CI workflow GitHub runs on push / pull_request |
| `README.md` | Modify | Add the CI status badge near the top |

Repo facts for the implementer (verified):
- Repository: `https://github.com/maederhkh/prompt2GDPR-v2` (public). Default branch `main`.
- `tests/` currently contains these 9 suites (all offline, all print `OK`): `test_policy_loader.py`, `test_run_diff.py`, `test_runs_summary.py`, `test_runs_index.py`, `test_extraction_mode.py`, `test_label_panel.py`, `test_rubric_extraction.py`, `test_run_metadata.py` — plus any added later (the glob handles them).
- `README.md` line 1 is the title `# prompt2GDPR-v2`; line 3 begins the description. The badge goes between them.

---

## Task 1: Create the CI workflow

**Files:**
- Create: `.github/workflows/tests.yml`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: a workflow named `tests` with a job `test`; the README badge in Task 2 references the workflow file path `tests.yml`.

- [ ] **Step 1: Create `.github/workflows/tests.yml`**

Create the file with EXACTLY this content:

```yaml
name: tests

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Check out the repository
        uses: actions/checkout@v4

      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install dependencies
        # Mirrors [project].dependencies in pyproject.toml. The project is not
        # installed as a package (no [build-system], flat layout); the test
        # suites add the repo root to sys.path themselves. If a dependency is
        # added to pyproject.toml, add it here too — otherwise CI fails with an
        # ImportError, which is the intended self-correcting signal.
        run: |
          python -m pip install --upgrade pip
          python -m pip install beautifulsoup4 json-repair openai pydantic pypdf python-docx python-dotenv rapidfuzz

      - name: Run offline test suites
        # Auto-discovers every tests/test_*.py; set -e makes the first failing
        # suite fail the whole job.
        run: |
          set -e
          for f in tests/test_*.py; do
            echo "=== $f ==="
            python "$f"
          done
```

- [ ] **Step 2: Verify the YAML parses**

The dev machine is Windows; use the Bash tool for this check.

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/tests.yml')); print('yaml OK')"`
Expected: `yaml OK`.

If it errors with `ModuleNotFoundError: No module named 'yaml'`, install PyYAML just for this check (it is NOT added to the project deps): `python -m pip install pyyaml`, then re-run. Expected: `yaml OK`.

- [ ] **Step 3: Pre-flight the exact test-discovery logic locally**

Confirm the same "run every `tests/test_*.py`, fail on first non-zero" logic the workflow uses actually passes on the current suites. On Windows/PowerShell run:

```powershell
Get-ChildItem tests/test_*.py | ForEach-Object { Write-Host "=== $($_.Name) ==="; python $_.FullName; if ($LASTEXITCODE -ne 0) { throw "FAILED: $($_.Name)" } }
```

Expected: each suite prints `OK`; no `FAILED:` is thrown; the command completes. (This proves the CI command logic against the real suites before pushing.)

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/tests.yml
git commit -m "ci: run offline test suites on push and pull request"
```

Then confirm `.claude/settings.local.json` was NOT committed:
Run: `git status --short`
Expected: the only listed file is ` M .claude/settings.local.json`.

---

## Task 2: Add the CI status badge to the README

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: the workflow file `tests.yml` created in Task 1 (the badge URL points at it).
- Produces: nothing downstream.

- [ ] **Step 1: Insert the badge under the title**

In `README.md`, the file starts with:

```markdown
# prompt2GDPR-v2

An agentic workflow for assessing privacy policy compliance with **GDPR Article 5(1)(b)  Purpose Limitation**, built as a research extension of a master's thesis at the University of Bologna (2025/2026).
```

Insert the badge line so it reads EXACTLY:

```markdown
# prompt2GDPR-v2

![Tests](https://github.com/maederhkh/prompt2GDPR-v2/actions/workflows/tests.yml/badge.svg)

An agentic workflow for assessing privacy policy compliance with **GDPR Article 5(1)(b)  Purpose Limitation**, built as a research extension of a master's thesis at the University of Bologna (2025/2026).
```

(The change adds the `![Tests](...)` line and one surrounding blank line; do not alter the title or the description text.)

- [ ] **Step 2: Verify the badge line is present and correct**

Run: `python -c "t=open('README.md',encoding='utf-8').read(); print('badge OK' if 'actions/workflows/tests.yml/badge.svg' in t else 'MISSING')"`
Expected: `badge OK`.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add CI status badge to the README"
```

Then confirm only the intended change is staged:
Run: `git status --short`
Expected: the only listed file is ` M .claude/settings.local.json`.

---

## Task 3: Verify CI on GitHub (post-merge / post-push)

**Files:** none (observation only).

This task can only be verified after the branch is merged and pushed to GitHub (CI runs remotely). It is done by the controller/human at branch finish, not by an offline implementer subagent. There is no code change and no local command that can substitute for it.

- [ ] **Step 1: Trigger CI**

Merge the feature branch to `main` and push (`git push origin main`), per the project's normal finish flow. The push event triggers the `tests` workflow.

- [ ] **Step 2: Confirm the run is green**

Open `https://github.com/maederhkh/prompt2GDPR-v2/actions` and confirm the latest `tests` run for the pushed commit completes with a green check (all suites printed `OK`, job succeeded).

Expected: the run status is success (green ✅).

- [ ] **Step 3: Confirm the badge renders**

Open `https://github.com/maederhkh/prompt2GDPR-v2` and confirm the **Tests** badge under the title shows passing (green).

Expected: badge renders and reads passing.

> If the run is red: open the failed step's log in the Actions tab, read which `tests/test_*.py` failed (or whether an `ImportError` indicates a dependency missing from the workflow's install list), fix the cause, and push again. Do not disable the workflow to make it green.

---

## Notes for the implementer

- **No pytest.** Suites are run directly: `python tests/<file>.py`; success prints `OK`, failure exits non-zero.
- **Offline only.** Never add `OPENROUTER_API_KEY` or any secret; never run `main.py` in CI.
- **`.github/` is not gitignored** — it commits normally. Only `docs/` needs `git add -f` (and this plan touches no docs files in Tasks 1–2).
- **The dependency list is duplicated on purpose** (pyproject.toml + workflow). If you add a dep to one, add it to the other; a miss fails CI loudly with an ImportError.
- **Do not commit `.claude/settings.local.json`.** Only `git add` the exact files listed in each commit step.
