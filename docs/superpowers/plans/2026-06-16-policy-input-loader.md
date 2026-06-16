# Policy Input Loader (Multi-Format Ingestion) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `--policy` accept HTML, PDF, and DOCX policies (in addition to `.txt`/`.md`) by converting each to clean plain text before the pipeline runs.

**Architecture:** One new module `utils/policy_loader.py` with a single public function `load_policy_text(path) -> str` that dispatches on the file extension, converts the file to plain text, and applies light normalization. `main.py` swaps its one `read_text(...)` call for `load_policy_text(...)` and gains a fast-fail check for unsupported formats. The LLM pipeline (Scout → … → outputs) is untouched.

**Tech Stack:** Python 3.12; new libs `beautifulsoup4` (HTML), `pypdf` (PDF), `python-docx` (DOCX). `reportlab` (already installed on this machine) is used **once** to generate a committed test fixture — it is NOT a project dependency. No pytest — tests are standalone `assert` scripts run with `python tests/<file>.py` that print `OK`. Windows + PowerShell (chain with `;`). Git LF→CRLF warnings are cosmetic. `docs/` is gitignored (use `git add -f` only for docs; code/test/fixture files stage normally).

**Spec:** `docs/superpowers/specs/2026-06-16-policy-input-loader-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `utils/policy_loader.py` | Create | Detect format by extension, convert PDF/HTML/DOCX/TXT → clean text, normalize |
| `tests/test_policy_loader.py` | Create | Standalone assert tests over sample files |
| `tests/fixtures/sample_policy.pdf` | Create | Tiny born-digital PDF fixture for the PDF test |
| `main.py` | Modify | Call the loader instead of `read_text`; fast-fail on unsupported format; update `--policy` help |
| `pyproject.toml` | Modify | Add the three libraries |

Key facts for the implementer (verified against the codebase):
- `main.py` reads the policy at line 61 inside `run_pipeline`: `policy_text = policy_path.read_text(encoding="utf-8", errors="replace")`. `policy_name = policy_path.stem` (line 60) stays as-is.
- `main()` checks `policy_path.exists()` at lines 407–410, then checks the API key at 412, then calls `run_pipeline` at 443–445 inside a `for run_i in range(1, args.runs + 1)` loop.
- The `--policy` help text is at line 341.
- `utils/section_splitter.py` matches headings by **line**, so keeping headings on their own text line matters — the HTML/DOCX handlers must preserve that.
- `utils/verifier.py` matches quotes fuzzily (≥ 85, case-insensitive), so light normalization is safe as long as it does not change the **words**.
- Do NOT commit `.claude/settings.local.json` (intentionally modified, must stay unstaged). Only `git add` the exact files named in each commit step.
- Do NOT modify the pipeline agents, prompts, verifier, evaluator, reflectors, finalizer, metrics, or the output/analysis tools.

---

## Task 1: Add dependencies + create the PDF fixture

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/fixtures/sample_policy.pdf`

- [ ] **Step 1: Add the three libraries to `pyproject.toml`**

Replace the `dependencies` list (lines 7–13) so it reads EXACTLY:

```toml
dependencies = [
    "beautifulsoup4>=4.12.0",
    "json-repair>=0.25.0",
    "openai>=1.0.0",
    "pydantic>=2.0.0",
    "pypdf>=4.0.0",
    "python-docx>=1.1.0",
    "python-dotenv>=1.0.0",
    "rapidfuzz>=3.0.0",
]
```

- [ ] **Step 2: Install the libraries**

Run: `python -m pip install "beautifulsoup4>=4.12.0" "pypdf>=4.0.0" "python-docx>=1.1.0"`
Expected: ends with `Successfully installed ...` (or "Requirement already satisfied").

Verify the imports resolve:
Run: `python -c "import bs4, pypdf, docx; print('libs OK')"`
Expected: `libs OK`

- [ ] **Step 3: Generate the committed PDF fixture**

This uses `reportlab` (already installed on this machine) ONCE to author a tiny born-digital PDF. `reportlab` is not added to `pyproject.toml` — the committed `.pdf` is what the tests read (via `pypdf`).

Run:

```
python -c "import os; from reportlab.pdfgen import canvas; os.makedirs('tests/fixtures', exist_ok=True); c = canvas.Canvas('tests/fixtures/sample_policy.pdf'); c.drawString(72, 720, 'We process your personal data to provide the service.'); c.save(); print('fixture written')"
```

Expected: `fixture written`.

- [ ] **Step 4: Verify the fixture is a real-text PDF that `pypdf` can read**

Run: `python -c "from pypdf import PdfReader; print('provide the service' in (PdfReader('tests/fixtures/sample_policy.pdf').pages[0].extract_text() or ''))"`
Expected: `True`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/fixtures/sample_policy.pdf
git commit -m "build: add html/pdf/docx deps and PDF test fixture"
```

Confirm `.claude/settings.local.json` was NOT committed:
Run: `git status --short`
Expected: the only listed file is ` M .claude/settings.local.json`.

---

## Task 2: The loader module (all formats + normalization)

**Files:**
- Create: `tests/test_policy_loader.py`
- Create: `utils/policy_loader.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_policy_loader.py` with EXACTLY this content:

```python
"""Standalone assert tests for the policy input loader."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from docx import Document

from utils.policy_loader import load_policy_text, SUPPORTED_EXTENSIONS

FIXTURES = Path(__file__).parent / "fixtures"
KNOWN = "We process your personal data to provide the service."


def test_supported_extensions():
    for ext in (".txt", ".md", ".html", ".htm", ".pdf", ".docx"):
        assert ext in SUPPORTED_EXTENSIONS


def test_txt():
    d = Path(tempfile.mkdtemp())
    try:
        f = d / "p.txt"
        f.write_text(KNOWN, encoding="utf-8")
        assert KNOWN in load_policy_text(f)
    finally:
        shutil.rmtree(d)


def test_html_strips_tags_and_keeps_headings():
    d = Path(tempfile.mkdtemp())
    try:
        f = d / "p.html"
        f.write_text(
            "<html><head><style>body{color:red}</style>"
            "<script>var x=1;</script></head><body>"
            "<h2>Purpose of Processing</h2>"
            f"<p>{KNOWN}</p></body></html>",
            encoding="utf-8",
        )
        out = load_policy_text(f)
        assert KNOWN in out
        assert "Purpose of Processing" in out
        assert "<" not in out and ">" not in out      # tags gone
        assert "var x" not in out                      # script contents gone
        # heading sits on its own line (section splitter is line-based)
        assert any(line.strip() == "Purpose of Processing" for line in out.splitlines())
    finally:
        shutil.rmtree(d)


def test_pdf_fixture():
    out = load_policy_text(FIXTURES / "sample_policy.pdf")
    assert "provide the service" in out


def test_docx_generated():
    d = Path(tempfile.mkdtemp())
    try:
        f = d / "p.docx"
        doc = Document()
        doc.add_heading("Purpose of Processing", level=2)
        doc.add_paragraph(KNOWN)
        doc.save(str(f))
        out = load_policy_text(f)
        assert KNOWN in out
        assert "Purpose of Processing" in out
    finally:
        shutil.rmtree(d)


def test_unsupported_extension():
    d = Path(tempfile.mkdtemp())
    try:
        f = d / "p.rtf"
        f.write_text("hello", encoding="utf-8")
        try:
            load_policy_text(f)
            assert False, "expected ValueError for unsupported extension"
        except ValueError as exc:
            assert ".rtf" in str(exc)
    finally:
        shutil.rmtree(d)


def test_normalization():
    d = Path(tempfile.mkdtemp())
    try:
        f = d / "p.txt"
        # CRLF line endings, a non-breaking space, and a run of 4 blank lines
        raw = "line one  \r\n" + "x y\r\n" + "\n\n\n\n" + "end"
        f.write_bytes(raw.encode("utf-8"))
        out = load_policy_text(f)
        assert "\r" not in out                 # CRLF -> LF
        assert " " not in out             # nbsp removed
        assert "x y" in out                    # nbsp became a normal space
        assert "line one\n" in out             # trailing spaces stripped
        assert "\n\n\n" not in out             # 3+ blank lines collapsed
    finally:
        shutil.rmtree(d)


if __name__ == "__main__":
    test_supported_extensions()
    test_txt()
    test_html_strips_tags_and_keeps_headings()
    test_pdf_fixture()
    test_docx_generated()
    test_unsupported_extension()
    test_normalization()
    print("OK")
```

- [ ] **Step 2: Run the tests to confirm they FAIL**

Run: `python tests/test_policy_loader.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'utils.policy_loader'`.

- [ ] **Step 3: Create `utils/policy_loader.py`**

Create `utils/policy_loader.py` with EXACTLY this content:

```python
"""
Policy input loader — multi-format ingestion.

Converts a policy file (plain text, HTML, PDF, or DOCX) into clean plain text
for the pipeline. This is the only place that knows about file formats; the
Scout, Extractor, verifier, evaluator, reflectors, finalizer, and outputs all
keep receiving a plain string exactly as before. Read-only; offline; no LLM
calls; no OCR (scanned/image-only PDFs are reported, not read).
"""

import re
import unicodedata
from pathlib import Path

from bs4 import BeautifulSoup
from docx import Document
from pypdf import PdfReader

SUPPORTED_EXTENSIONS = {".txt", ".md", ".html", ".htm", ".pdf", ".docx"}


def _normalize(text: str) -> str:
    """Light cleanup that never changes the words of the text: unify line
    endings, turn unicode spaces into a normal space, strip trailing spaces per
    line, and collapse runs of 3+ blank lines down to a single blank line."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Any unicode space separator (incl. non-breaking space) -> regular space.
    text = "".join(" " if unicodedata.category(ch) == "Zs" else ch for ch in text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _load_html(raw: str) -> str:
    """Strip <script>/<style>, then extract text with block-level line breaks
    so headings and paragraphs land on their own lines."""
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text(separator="\n")


def _load_pdf(path: Path) -> str:
    """Extract text from a born-digital PDF, page by page. Warns (and returns
    "") on a scanned/image-only PDF; raises ValueError on a corrupt file."""
    try:
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:                       # corrupt/unreadable PDF
        raise ValueError(f"could not read PDF: {path} ({exc})")
    text = "\n\n".join(pages)
    if not text.strip():
        print(
            f"  [policy_loader] WARNING: no text extracted from {path} — this "
            "looks like a scanned/image-only PDF; OCR is not supported."
        )
    return text


def _load_docx(path: Path) -> str:
    """Join the document's paragraphs (headings included) by line breaks."""
    try:
        doc = Document(str(path))
    except Exception as exc:                        # corrupt/unreadable DOCX
        raise ValueError(f"could not read DOCX: {path} ({exc})")
    return "\n".join(p.text for p in doc.paragraphs)


def load_policy_text(path) -> str:
    """
    Read one policy file and return clean plain text. Dispatches on the
    lowercased file extension. Raises ValueError for an unsupported extension
    or a corrupt file.
    """
    p = Path(path)
    ext = p.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"unsupported policy format '{ext}'; supported: "
            + " ".join(sorted(SUPPORTED_EXTENSIONS))
        )
    if ext in (".txt", ".md"):
        text = p.read_text(encoding="utf-8", errors="replace")
    elif ext in (".html", ".htm"):
        text = _load_html(p.read_text(encoding="utf-8", errors="replace"))
    elif ext == ".pdf":
        text = _load_pdf(p)
    else:  # ".docx"
        text = _load_docx(p)
    return _normalize(text)
```

- [ ] **Step 4: Run the tests to confirm they PASS**

Run: `python tests/test_policy_loader.py`
Expected output: `OK`

- [ ] **Step 5: Commit**

```bash
git add utils/policy_loader.py tests/test_policy_loader.py
git commit -m "feat: add multi-format policy input loader (txt/md/html/pdf/docx)"
```

---

## Task 3: Wire the loader into `main.py`

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add the import**

In `main.py`, add this line alongside the other `from utils...` imports near the top of the file:

```python
from utils.policy_loader import load_policy_text, SUPPORTED_EXTENSIONS
```

- [ ] **Step 2: Use the loader inside `run_pipeline`**

In `main.py`, replace line 61:

```python
    policy_text = policy_path.read_text(encoding="utf-8", errors="replace")
```

with:

```python
    policy_text = load_policy_text(policy_path)
```

- [ ] **Step 3: Fast-fail on an unsupported format in `main()`**

In `main.py`, immediately AFTER the existing existence check (the block ending with `sys.exit(1)` at line 410), insert:

```python
    if policy_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        print(
            f"ERROR: unsupported policy format '{policy_path.suffix}'; "
            f"supported: {' '.join(sorted(SUPPORTED_EXTENSIONS))}",
            file=sys.stderr,
        )
        sys.exit(1)
```

- [ ] **Step 4: Guard the `run_pipeline` call against a corrupt file**

In `main.py`, replace the call (lines 443–445):

```python
        result = run_pipeline(
            client, policy_path, agent_models=agent_models, blind_enabled=blind_enabled
        )
```

with:

```python
        try:
            result = run_pipeline(
                client, policy_path, agent_models=agent_models, blind_enabled=blind_enabled
            )
        except ValueError as exc:
            print(f"ERROR: could not read policy: {exc}", file=sys.stderr)
            sys.exit(1)
```

- [ ] **Step 5: Update the `--policy` help text**

In `main.py`, change the `--policy` help string (line 341) from:

```python
        help="Path to the privacy policy text file (.txt)",
```

to:

```python
        help="Path to the privacy policy file (.txt/.md/.html/.htm/.pdf/.docx)",
```

- [ ] **Step 6: Smoke-test the no-API paths (these exit before any API call)**

Unsupported format (a file that exists but has an unsupported extension):

Run:
```
python -c "open('tmp_smoke.rtf','w').write('hi')" ; python main.py --policy tmp_smoke.rtf ; echo "exit=$LASTEXITCODE" ; python -c "import os; os.remove('tmp_smoke.rtf')"
```
Expected: prints `ERROR: unsupported policy format '.rtf'; supported: .docx .htm .html .md .pdf .txt` and `exit=1`.

Missing file (regression — must still work):

Run: `python main.py --policy does_not_exist.txt ; echo "exit=$LASTEXITCODE"`
Expected: prints `ERROR: Policy file not found: does_not_exist.txt` and `exit=1`.

- [ ] **Step 7: Commit**

```bash
git add main.py
git commit -m "feat: load policies via the multi-format loader in main.py"
```

---

## Task 4: Whole-feature verification (offline)

**Files:** none (verification only)

- [ ] **Step 1: Run the loader test suite**

Run: `python tests/test_policy_loader.py`
Expected: `OK`

- [ ] **Step 2: Confirm nothing else regressed**

Run each existing standalone suite:
```
python tests/test_run_diff.py ; python tests/test_runs_summary.py ; python tests/test_runs_index.py ; python tests/test_extraction_mode.py
```
Expected: each prints `OK`.

- [ ] **Step 3: Confirm only intended files changed**

Run: `git status --short`
Expected: the ONLY modified tracked file is ` M .claude/settings.local.json` (pre-existing; do NOT stage or commit it). Everything from Tasks 1–3 is already committed.

- [ ] **Step 4: Final marker commit (allow empty)**

```bash
git commit --allow-empty -m "test: verify policy input loader end-to-end (offline)"
```

> Do NOT `git add` anything in this step. If you accidentally staged a file, unstage it with `git restore --staged <file>` before committing.

---

## Notes for the implementer

- **No pytest.** Run a test file directly: `python tests/test_policy_loader.py`; it prints `OK` on success.
- **The loader is the only format-aware code.** `main.py` just calls `load_policy_text(...)`; the LLM pipeline is untouched.
- **Normalization must never change the words** — only whitespace/line-ending/unicode-space cleanup. The verifier matches quotes verbatim (fuzzily), so altering words would break grounding.
- **No OCR.** A scanned/image-only PDF yields empty text → a warning is printed and `""` is returned; the run does not crash.
- **`reportlab` is a one-off fixture generator**, not a project dependency. The committed `tests/fixtures/sample_policy.pdf` is what the tests read (via `pypdf`).
- **Do not commit `.claude/settings.local.json`.** Only `git add` the exact files listed in each commit step.
