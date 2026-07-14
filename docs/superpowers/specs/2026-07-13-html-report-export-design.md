# HTML Report Export — Design Spec

**Date:** 2026-07-13
**Status:** Awaiting user review
**Scope:** A standalone, on-demand command that renders a saved run's Markdown report as a self-contained, styled HTML page. No pipeline change. Reuses the existing report markdown via a small behavior-preserving refactor plus a bounded Markdown→HTML converter. Offline, no LLM calls.

---

## 1. Goal

Every per-run report today is **Markdown** — ideal for GitHub, but not something you can hand to a non-technical reviewer (e.g. a thesis supervisor) and have them simply open and read. This feature adds an **HTML output format**: a single self-contained `.html` file (all CSS inlined, no external assets) that opens in any browser, with color-coded compliance labels. It is produced **on demand** from any saved run JSON — the pipeline is unchanged.

## 2. Background — what already exists and is reused

- **`utils/report_generator.py`** builds the full report as a list of markdown lines and writes `"\n".join(lines)` to a file in `generate_report(result, out_path)`. This feature extracts a `build_report_markdown(result) -> str` (the joined markdown) so the same content can be converted to HTML; `generate_report` then simply writes what that function returns — identical behavior.
- **The report's markdown subset** (verified from the generator) is bounded: headings `#`/`##`/`###`/`####`; tables (`| … |` rows with a `|---|…|` separator); unordered lists (`- `); blockquotes (`> `, used for clause quotes); bold `**…**`; inline code `` `…` ``; horizontal rules `---`; and blank-line-separated paragraphs. There are **no** links, images, ordered lists, or nested lists.
- Table cells are sanitized by the generator's `_cell` helpers, which escape a literal pipe as `\|` and flatten newlines — the converter must respect that escaping (see §4.2).
- **`review_run.py`** and **`diff_runs.py`** establish the standalone read-only CLI pattern: load one run JSON, render, write one artifact, print the path, and on a missing/invalid/not-a-run JSON print a readable message and return exit code `0` (forgiving).

## 3. Approaches considered

### 3.1 Recommended: reuse the markdown + a bounded converter
Extract `build_report_markdown`, write a small `md_to_html` covering exactly the constructs above, and wrap the result in a styled self-contained template.

Benefits: DRY — the HTML tracks any future change to the markdown report automatically; no new heavy dependency; fully offline and testable; the converter's input is our own regular, machine-generated markdown, so its subset is bounded.

Trade-off: we own a small markdown converter. Mitigated by the bounded, known input and thorough unit tests.

### 3.2 Parallel HTML renderer from the result dict
Re-implement every report section directly in HTML. Rejected: duplicates ~470 lines of section logic and drifts out of sync with the markdown report on every future change.

### 3.3 Embed a JavaScript markdown library
Ship raw markdown in the page and render it client-side with an inlined `marked.js`. Rejected: bloats the page and breaks the project's stdlib-only, offline, self-contained ethos.

## 4. Feature design

### 4.1 Files

| File | Action | Responsibility |
|---|---|---|
| `utils/report_generator.py` | Modify | Extract `build_report_markdown(result) -> str`; `generate_report` writes its return value (behavior-preserving). |
| `utils/html_report.py` | Add | `md_to_html(markdown) -> str` (bounded converter → HTML body fragment); `render_html_report(result) -> str` (build markdown → convert → colorize labels → wrap in styled document); `write_html_report(result, path) -> None`. |
| `report_html.py` | Add | Standalone CLI: load one run JSON, write `<stem>_report.html`, print the path; forgiving (exit 0) on missing/invalid/not-a-run JSON. |
| `tests/test_html_report.py` | Add | Offline tests for the converter, the renderer, the CLI, and the refactor. |
| `README.md` | Modify | Document the `report_html.py` command and the HTML output artifact. |

### 4.2 `md_to_html(markdown: str) -> str`

A line-oriented converter that returns the HTML **body fragment** (not a full document). Rules:

1. **Escape first.** Escape `&`, `<`, `>` in all text content *before* applying inline formatting, so policy text can never inject markup while `**`/`` ` `` still work.
2. **Inline formatting** (applied to text within paragraphs, list items, blockquotes, and table cells): `**bold**` → `<strong>bold</strong>`; `` `code` `` → `<code>code</code>`.
3. **Block parsing** (line by line, with one-line lookahead for tables):
   - `# ` / `## ` / `### ` / `#### ` → `<h1>`…`<h4>` (inline formatting applied to the heading text).
   - A line that is exactly `---` → `<hr>`.
   - Consecutive `> ` lines → a single `<blockquote>` (lines joined; inline formatting applied).
   - Consecutive `- ` lines → `<ul><li>…</li></ul>` (inline formatting per item).
   - **Table:** a `| … |` line immediately followed by a separator line matching `|---|…|` opens a `<table>`; the first row becomes `<thead><th>`, subsequent consecutive `| … |` rows become `<tbody><td>`. Cells are split on **unescaped** `|` only, then each cell has `\|` unescaped back to `|` and inline formatting applied.
   - Blank line → block separator.
   - Any other non-empty line → paragraph text; consecutive plain lines are joined into one `<p>` (separated by `<br>`).

The converter is pure and deterministic; it returns a string and mutates nothing.

### 4.3 `render_html_report(result: dict) -> str`

1. `markdown = build_report_markdown(result)`
2. `body = md_to_html(markdown)`
3. `body = _colorize_labels(body)` — wrap the three canonical compliance labels (`"Compliant"`, `"Partially Compliant"`, `"Non-Compliant"`) in a `<span class="label label-{compliant|partial|noncompliant}">…</span>` **only where they appear inside a `<td>`, `<th>`, or `<h4>` element** (the report's label locations: the summary table, the clause table, and the clause-detail headings). Matching is bounded to those elements to avoid coloring the words in prose. `"Partially Compliant"`/`"Non-Compliant"` are matched before `"Compliant"` so the longer phrases win.
4. Wrap in a full document: `<!doctype html>`, `<head>` with `<meta charset="utf-8">`, a `<meta name="viewport">`, a `<title>` of `GDPR Assessment — {policy_name}`, and an inlined `<style>` block (§4.5); `<body>` contains a centered container with the converted fragment.

### 4.4 `report_html.py` (CLI)

Mirror `review_run.py`:
- `argparse`: positional `path`, optional `--output`.
- `load_run(path)` reuses the same forgiving contract with `REQUIRED_KEYS = ("policy_name", "finalizer_output")`: missing file / invalid JSON / not-a-run JSON → print `Cannot generate HTML report: <reason>` and `return 0`, writing nothing.
- Default output path: `<input-stem>_report.html` next to the JSON (or `--output PATH`).
- On success: `write_html_report(result, out_path)` and print `HTML report written to <path>`; `return 0`.
- No network, no LLM calls.

### 4.5 Styling (inlined CSS, self-contained)

Light theme, no external fonts/CSS/JS. System font stack; a `max-width` centered container with comfortable line-height; `<table>` with collapsed borders, a shaded header row, and zebra-striped body rows; `<blockquote>` with a left accent border and muted background; `<code>` monospace with a subtle background; a clear `h1`–`h4` hierarchy; and label badges — `.label-compliant` (green), `.label-partial` (amber), `.label-noncompliant` (red) — rendered as small rounded pills. Everything must render correctly from a `file://` open with no network.

## 5. Error handling

- The CLI is forgiving (exit `0`) on missing/invalid/not-a-run JSON, matching `diff_runs.py`.
- `md_to_html` is pure and defensive: it HTML-escapes all text (so policy content cannot break the page) and treats any unrecognized line as paragraph text rather than raising.
- `render_html_report` tolerates a minimal/older result the same way the markdown generator does (it consumes that generator's output).
- No new failure mode touches the pipeline — this is a separate, read-only command.

## 6. Testing and verification

Offline tests only (no API key, no LLM, no network). `tests/test_html_report.py`:

1. **Converter units:** a heading, a table (asserts `<table>`, `<thead>`, `<th>`, `<tbody>`, `<td>`), a bullet block (`<ul><li>`), a blockquote (`<blockquote>`), `**bold**` (`<strong>`), inline `` `code` `` (`<code>`), `---` (`<hr>`), and a paragraph. Assert `<`, `>`, `&` in text are escaped, and that an escaped table pipe `\|` renders as a literal `|` inside the cell (not a new column).
2. **Full render:** `render_html_report(fake_full_result)` contains `<!doctype html>`, `<title>GDPR Assessment — …`, the `<style>` block, a `<table>`, and a color-coded label span (e.g. `class="label label-partial"`) for the overall label.
3. **Minimal render:** `render_html_report({"policy_name": …, "finalizer_output": …})` returns valid HTML without crashing.
4. **CLI:** `report_html.main` against a temp JSON writes `<stem>_report.html` containing `<html`; a missing file and a not-a-run JSON each print a readable message, return `0`, and write nothing.
5. **Refactor guard:** writing via `generate_report(result, tmp)` yields exactly `build_report_markdown(result)` — proves the extraction is behavior-preserving.

Manual verification:

```bash
python tests/test_html_report.py
python report_html.py output/results/<existing-run>.json   # then open the .html in a browser
```

## 7. Out of scope

- No auto-generation in `save_result` (on-demand only).
- No HTML for the runs index, runs summary, batch comparison, or review brief — per-run report only.
- No PDF, no external CSS/JS/fonts, no dark mode.
- No change to the markdown report's content, the per-run JSON, or the pipeline.
- No general-purpose markdown support beyond the bounded subset the report emits.
