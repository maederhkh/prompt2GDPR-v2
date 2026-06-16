# Policy Input Loader (Multi-Format Ingestion) — Design Spec

**Date:** 2026-06-16
**Status:** Approved for planning
**Scope:** A small, isolated input layer that lets `--policy` accept HTML, PDF, and DOCX policies in addition to plain text, by converting each to clean plain text before the pipeline runs. The LLM pipeline is untouched. No OCR.

---

## 1. Goal

Today the pipeline only truly works on hand-prepared `.txt`. `main.py` reads the
policy with a single `policy_path.read_text(encoding="utf-8", errors="replace")`
call, so any non-text file (PDF, HTML page) is read as raw bytes/markup and the
downstream Scout cannot find sections. Real privacy policies are almost always
**web pages (HTML)** or **born-digital PDFs**, so testing a real policy currently
requires manually copy-pasting it into a `.txt` file first.

This feature adds a format-aware loader so the same command works on the files
policies actually ship as:

```
python main.py --policy data/policies/some_policy.pdf
python main.py --policy data/policies/some_policy.html
python main.py --policy data/policies/some_policy.docx
```

Key properties:

- **Pipeline-transparent.** The loader returns plain text; the Scout, Extractor,
  verifier, evaluator, reflectors, finalizer, and all outputs are unchanged. They
  keep receiving a plain string exactly as before.
- **One-line integration.** `main.py` swaps `read_text(...)` for
  `load_policy_text(policy_path)`. Nothing else in `main.py` logic changes.
- **Read-only** with respect to the input file.
- **Offline.** PDF/HTML/DOCX parsing uses small local libraries; no network, no
  API calls, no LLM calls.
- **No OCR.** Scanned, image-only PDFs are out of scope (see §6).

## 2. Background — how input works today

- `main.py` argument: `--policy PATH` (currently advertised as `.txt`).
- `main.py` reads the policy once: `policy_text = policy_path.read_text(encoding="utf-8", errors="replace")`.
- `policy_name = policy_path.stem` (filename without extension) — unchanged by this feature.
- The Scout returns section headings; `utils/section_splitter.py` locates each
  heading by **line-based** fuzzy matching (`partial_ratio >= 60`). So heading
  text appearing on its own line matters for good sectioning.
- `utils/verifier.py` checks each extracted quote against the policy text with
  rapidfuzz (`>= 85`), case-insensitive, with a partial/sliding-window fallback.
  Minor formatting differences are already tolerated; the loader must not alter
  the actual **words** of the text.

## 3. Feature design

### 3.1 Files

| File | Action | Responsibility |
|---|---|---|
| `utils/policy_loader.py` | Create | Detect format by extension, convert to clean plain text, light-normalize |
| `tests/test_policy_loader.py` | Create | Standalone assert tests over sample files |
| `tests/fixtures/sample_policy.pdf` | Create | Tiny born-digital PDF fixture for the PDF test |
| `main.py` | Modify | Call `load_policy_text(policy_path)` instead of `read_text`; update `--policy` help text; catch loader `ValueError` |
| `pyproject.toml` | Modify | Add `beautifulsoup4`, `pypdf`, `python-docx` |

### 3.2 `utils/policy_loader.py` — public function

- **`load_policy_text(path) -> str`**
  Reads one policy file, dispatching on the **lowercased file extension**, and
  returns normalized plain text. Raises `ValueError` (with a readable message)
  for an unsupported extension.

  Dispatch table:

  | Extension | Handler | Library |
  |---|---|---|
  | `.txt`, `.md` | read UTF-8 (`errors="replace"`) — same as today | stdlib |
  | `.html`, `.htm` | strip tags, keep readable text with block-level line breaks | `beautifulsoup4` |
  | `.pdf` | extract text page by page, joined by blank lines | `pypdf` |
  | `.docx` | join paragraph text (incl. headings) by line breaks | `python-docx` |

  All handler outputs pass through the same normalization step (§3.4) before
  return.

### 3.3 HTML extraction detail

- Parse with BeautifulSoup; remove `<script>` and `<style>` elements entirely.
- Extract text such that block-level elements (headings, paragraphs, list items)
  are separated by newlines, so a heading like `<h2>Purpose of Processing</h2>`
  becomes its own text line. This preserves the section structure the splitter
  relies on.

### 3.4 Normalization (applied to every format)

Light only — must not change the words of any quote:

1. Normalize line endings: `\r\n` and `\r` → `\n`.
2. Replace non-breaking spaces (` `) and other unicode space separators with
   a regular space.
3. Strip trailing whitespace from each line.
4. Collapse runs of 3+ consecutive blank lines down to a single blank line.
5. Strip leading/trailing whitespace from the whole document.

Rationale: the verifier and splitter already tolerate minor formatting via fuzzy
matching; this cleanup improves line-based heading detection without altering
clause wording.

### 3.5 `main.py` integration

- Replace the single `read_text` call with `load_policy_text(policy_path)`.
- Update the `--policy` help text from "Path to the privacy policy text file
  (.txt)" to indicate supported formats (`.txt/.md/.html/.htm/.pdf/.docx`).
- Wrap the loader call so a `ValueError` (unsupported format) prints a friendly
  error to stderr and exits non-zero, mirroring the existing missing-file path.
- The existing file-existence check (`policy_path.exists()`) is retained.
- `policy_name` continues to be `policy_path.stem` — unchanged.

## 4. Error handling

| Condition | Behavior |
|---|---|
| Unsupported extension | `ValueError("unsupported policy format '<ext>'; supported: .txt .md .html .htm .pdf .docx")`; `main.py` prints it and exits non-zero. Nothing run. |
| File does not exist | Existing `main.py` check handles it (unchanged). |
| PDF/DOCX/HTML yields empty text (e.g. scanned, image-only PDF) | Return the empty string and print a clear warning: "no text extracted — this looks like a scanned/image-only PDF; OCR is not supported." The pipeline then proceeds and naturally produces an empty/flagged result. Never crashes. |
| Malformed/corrupt file the library cannot parse | The library's parse error is wrapped in a `ValueError` with a readable message; `main.py` reports it and exits non-zero. |

## 5. Testing

Standalone assert script (`python tests/test_policy_loader.py`, prints `OK`;
`sys.path` shim; no pytest).

- `.txt`: written inline in a temp dir → returns the known sentence.
- `.html`: written inline (with `<script>`, a heading, and paragraphs) → returns
  the known sentence, the heading appears on its own line, and no HTML tags
  (`<`, `>`, `script` contents) remain.
- `.docx`: generated in-test with `python-docx` (it is a declared dependency) →
  returns the known sentence.
- `.pdf`: read from the committed tiny born-digital fixture
  `tests/fixtures/sample_policy.pdf` → returns its known sentence.
- Unsupported extension (e.g. `.rtf`) → raises `ValueError`.
- Normalization: a string with `\r\n`, a non-breaking space, and 3+ blank lines
  comes back with `\n` only, a normal space, and no run of 3+ blank lines.

## 6. Out of scope

- **OCR** for scanned/image-only PDFs (would need a heavy engine like Tesseract,
  is slow and error-prone, and would corrupt verbatim quote matching; scanned
  policies are rare). Could be a separate future project.
- Fetching policies from a URL (the user passes a local file).
- Smarter or LLM-based sectioning (the splitter is unchanged).
- Any change to the pipeline agents, prompts, verifier, evaluator, reflectors,
  finalizer, metrics, or the output/analysis tools.
