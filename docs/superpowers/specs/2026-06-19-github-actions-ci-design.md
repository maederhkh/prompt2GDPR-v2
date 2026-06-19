# GitHub Actions CI for Offline Tests — Design Spec

**Date:** 2026-06-19
**Status:** Approved for planning
**Scope:** Add Continuous Integration that automatically runs the project's offline test suites on GitHub every time code is pushed or a pull request is opened, and surface the result as a status badge in the README. No change to the pipeline, the application code, or the tests themselves.

---

## 1. Goal

Today the only thing preventing a broken change from reaching `main` is the developer remembering to run the test suites by hand:

```
python tests/test_policy_loader.py
python tests/test_run_diff.py
... (9 suites total)
```

This is easy to forget, especially during a run of quick merges. There is also no outward signal that the project is tested.

This feature makes GitHub run all offline test suites automatically on every push and pull request, fail visibly when any suite breaks, and show a live pass/fail badge in the README. It is a safety net, not a new capability — the pipeline is untouched.

## 2. Background — how testing works today

- Tests are **standalone assert scripts**, not pytest. Each file is run directly: `python tests/<file>.py`, and prints `OK` on success. On failure an `AssertionError` (or import error) is raised, giving a non-zero exit code.
- Each test file inserts the repo root on `sys.path` (`sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))`), so the suites import `utils.*`, `agents.*`, etc. **without the project being installed as a package**.
- There are currently 9 suites in `tests/` matching `test_*.py`:
  `test_policy_loader.py`, `test_run_diff.py`, `test_runs_summary.py`,
  `test_runs_index.py`, `test_extraction_mode.py`, `test_label_panel.py`,
  `test_rubric_extraction.py`, `test_run_metadata.py`, and any future additions.
- All suites are **offline**: no network, no API key, no LLM calls. The extractor/evaluator tests use a `FakeClient`. This is what makes them safe and free to run in CI.
- Dependencies are declared in `pyproject.toml` under `[project].dependencies`. There is **no `[build-system]`** table and the layout is flat (top-level modules plus `agents/`, `utils/`, `prompts/`, `evaluation/`), so `pip install .` is not relied upon.
- Repository is **public** (`https://github.com/maederhkh/prompt2GDPR-v2`), so GitHub Actions minutes are free and unlimited.

## 3. Feature design

### 3.1 Files

| File | Action | Responsibility |
|---|---|---|
| `.github/workflows/tests.yml` | Create | The CI workflow GitHub executes on push / pull_request |
| `README.md` | Modify | Add a CI status badge near the top |

No other files change. `.github/` is **not** gitignored, so it commits normally (unlike `docs/`).

### 3.2 Workflow triggers

Run on:
- **`push`** — every push to any branch.
- **`pull_request`** — every PR opened or updated.

This gives a check both when work is saved and before any branch merges into `main`.

### 3.3 Workflow job

A single job on `ubuntu-latest`:

1. **Checkout** the repository (`actions/checkout`).
2. **Set up Python 3.12** (`actions/setup-python`), with pip caching for speed.
3. **Install dependencies** — install the 8 libraries from `pyproject.toml` directly (see §3.4). The project is not installed as a package; the test suites' `sys.path` shim makes the modules importable from the repo root.
4. **Run all offline test suites** — auto-discover every `tests/test_*.py` and run each with `python`. The step uses a shell loop under `set -e` (or equivalent) so that the first non-zero exit fails the whole job. Auto-discovery means new test files are picked up with no workflow edit.

### 3.4 Dependency installation (and the one trade-off)

The install step installs the same 8 libraries listed in `pyproject.toml`:

```
beautifulsoup4 json-repair openai pydantic pypdf python-docx python-dotenv rapidfuzz
```

This duplicates the dependency list (it lives in both `pyproject.toml` and the workflow). This is an accepted, deliberate trade-off: the alternative — adding `[build-system]` config so `pip install .` reads the single source of truth — is more complexity than this research repo warrants, and the flat layout makes `pip install .` fragile (setuptools "multiple top-level packages" pitfall). If a dependency is added to `pyproject.toml` later and not to the workflow, **CI fails loudly with an `ImportError`**, so the drift is self-correcting rather than silent. The workflow will carry a comment noting it mirrors `pyproject.toml`.

### 3.5 README badge

Add a status badge near the top of `README.md` (under the title) linking to the Actions workflow:

```
![Tests](https://github.com/maederhkh/prompt2GDPR-v2/actions/workflows/tests.yml/badge.svg)
```

It renders green when the latest run on the default branch passed, red when it failed.

## 4. What it deliberately does NOT do

- **No live pipeline run.** CI never calls `main.py`, never uses an API key, never spends money. Only the offline suites run.
- **No secrets.** No `OPENROUTER_API_KEY` or any secret is added to the repo or the workflow.
- **No change to the pipeline, prompts, agents, tests, or any application code.**
- **No matrix.** Python 3.12 only (the project's required version).
- **No packaging changes** to `pyproject.toml`.

## 5. Error handling / behavior

| Condition | Behavior |
|---|---|
| All suites pass | Job succeeds → green check on the commit/PR, badge green. |
| Any suite raises (assert/import/runtime) | That `python tests/test_*.py` exits non-zero → the loop stops under `set -e` → job fails → red ❌ + email, badge red. |
| A dependency is missing from the install step | The suite import fails → job fails loudly (self-correcting drift signal). |
| A new `tests/test_*.py` is added | Picked up automatically by the glob — no workflow change needed. |

## 6. Testing / verification

This feature is verified by observation, not by a new test suite:

1. After committing the workflow + badge and pushing, open the repo's **Actions** tab and confirm the run appears and goes **green**.
2. Confirm the **badge** renders in the README on GitHub.
3. (Optional sanity check) Temporarily break one assertion on a throwaway branch, push, and confirm the job goes **red** — then discard that branch. This is optional and must not land on `main`.

## 7. Out of scope

- Running the real LLM pipeline in CI (needs a paid API key; cost and secret-management concerns).
- pytest migration or any change to how tests are written.
- Linting / formatting / type-checking gates (could be a separate future workflow).
- Coverage reporting.
- Multi-OS or multi-Python matrices.
- Auto-deploy / release automation (Pages already deploys via its own built-in flow).
