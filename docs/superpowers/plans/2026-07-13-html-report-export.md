# HTML Report Export — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an on-demand command that renders a saved run's Markdown report as a self-contained, styled HTML page (`<stem>_report.html`).

**Architecture:** Reuse the existing report markdown rather than re-implement sections. A behavior-preserving refactor exposes `build_report_markdown(result) -> str` in `report_generator.py`; a new `utils/html_report.py` converts that markdown to HTML with a bounded, purpose-built converter and wraps it in a styled self-contained document; a new `report_html.py` CLI drives it. No pipeline change.

**Tech Stack:** Python 3.12, standard library only (`re`, `pathlib`, `argparse`, `json`). Tests are standalone assert scripts (NOT pytest). Dev machine is Windows + PowerShell (chain commands with `;`, never `&&`).

## Global Constraints

- **Offline only.** No LLM/network/API key in any test. Never invoke the real pipeline.
- Tests are **standalone assert scripts**: `tests/test_*.py` inserts the repo root on `sys.path`, defines `test_*()` functions, and a `__main__` block that calls them and prints `OK`; any failure raises and exits non-zero. Run with `python tests/<file>.py`.
- **Self-contained output.** The generated HTML must embed all CSS inline and reference NO external assets (no CDN, fonts, JS) — it must render from a `file://` open with no network.
- **Stdlib only.** No new third-party dependency (no markdown library).
- **Bounded converter.** `md_to_html` supports exactly the constructs the report emits: headings `#`–`####`, tables (`| … |` + `|---|` separator), unordered lists `- `, blockquotes `> `, bold `**…**`, inline code `` `…` ``, horizontal rules `---`, and paragraphs. No links, images, ordered/nested lists.
- **Security:** HTML-escape `&`, `<`, `>` in all text content BEFORE applying inline formatting, so policy text can never inject markup.
- **Canonical labels:** the three compliance labels are exactly `"Compliant"`, `"Partially Compliant"`, `"Non-Compliant"`; color them only inside `<td>`, `<th>`, and `<h4>` elements; match `"Partially Compliant"`/`"Non-Compliant"` before `"Compliant"`.
- `docs/` is gitignored; `utils/`, `tests/`, root `.py`, and `README.md` are tracked normally. Only `git add` the exact files named in each commit step (never `git add -A`). Do NOT stage `.claude/settings.local.json` or `.superpowers/`.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `utils/html_report.py` | Create | `md_to_html` converter (Task 1); `render_html_report` / `_colorize_labels` / `write_html_report` (Task 2). |
| `utils/report_generator.py` | Modify | Extract `build_report_markdown(result) -> str`; `generate_report` writes its return value (Task 2). |
| `report_html.py` | Create | Standalone CLI (Task 3). |
| `tests/test_html_report.py` | Create/extend | Converter tests (Task 1); refactor + renderer tests (Task 2); CLI tests (Task 3). |
| `README.md` | Modify | Document the command and the HTML artifact (Task 4). |

---

## Task 1: The Markdown→HTML converter

**Files:**
- Create: `utils/html_report.py`
- Test: `tests/test_html_report.py` (create)

**Interfaces:**
- Produces: `md_to_html(markdown: str) -> str` — returns an HTML **body fragment** (no `<html>`/`<head>`), covering the bounded construct set. Pure; escapes text; applies inline `**bold**`→`<strong>` and `` `code` ``→`<code>`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_html_report.py`:

```python
"""Offline tests for the HTML report export."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.html_report import md_to_html


def test_heading_levels():
    assert md_to_html("# Title") == "<h1>Title</h1>"
    assert md_to_html("#### Sub") == "<h4>Sub</h4>"


def test_hr():
    assert md_to_html("---") == "<hr>"


def test_bold_and_code():
    out = md_to_html("This is **bold** and `code`.")
    assert "<strong>bold</strong>" in out
    assert "<code>code</code>" in out


def test_escaping_blocks_injection():
    out = md_to_html("a < b & c > d")
    assert "&lt;" in out and "&amp;" in out and "&gt;" in out
    assert "<b b" not in out  # no raw tag injected from the text


def test_bullets():
    out = md_to_html("- one\n- two")
    assert "<ul>" in out and out.count("<li>") == 2


def test_blockquote():
    assert md_to_html("> quoted line") == "<blockquote>quoted line</blockquote>"


def test_table():
    out = md_to_html("| A | B |\n|---|---|\n| 1 | 2 |")
    assert "<table>" in out and "<thead>" in out and "<th>A</th>" in out
    assert "<tbody>" in out and "<td>1</td>" in out and "<td>2</td>" in out


def test_table_escaped_pipe_stays_one_cell():
    out = md_to_html("| A | B |\n|---|---|\n| x\\|y | 2 |")
    assert "<td>x|y</td>" in out
    assert out.count("<td>") == 2  # escaped pipe did NOT create a third cell


def test_paragraph():
    assert md_to_html("just text") == "<p>just text</p>"


if __name__ == "__main__":
    test_heading_levels()
    test_hr()
    test_bold_and_code()
    test_escaping_blocks_injection()
    test_bullets()
    test_blockquote()
    test_table()
    test_table_escaped_pipe_stays_one_cell()
    test_paragraph()
    print("OK")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python tests/test_html_report.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'utils.html_report'`. Non-zero exit, no `OK`.

- [ ] **Step 3: Implement the converter**

Create `utils/html_report.py`:

```python
"""Render a saved pipeline run's markdown report as self-contained HTML.

Pure, offline, stdlib-only. The converter supports exactly the markdown
constructs the report generator emits (headings, tables, unordered lists,
blockquotes, bold, inline code, horizontal rules, paragraphs).
"""
import re
from pathlib import Path


_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`([^`]+)`")
_HEADING = re.compile(r"(#{1,4})\s+(.*)")
_SEPARATOR = re.compile(r"\|(?:\s*:?-+:?\s*\|)+")


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline(text: str) -> str:
    """Apply inline formatting to already-escaped text."""
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _CODE.sub(r"<code>\1</code>", text)
    return text


def _fmt(text: str) -> str:
    return _inline(_escape(text))


def _split_row(row: str) -> list:
    """Split a table row on UNescaped pipes; unescape \\| back to | per cell."""
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    cells = re.split(r"(?<!\\)\|", row)
    return [c.strip().replace("\\|", "|") for c in cells]


def _is_separator(line: str) -> bool:
    return bool(_SEPARATOR.fullmatch(line.strip()))


def _is_block_start(s: str) -> bool:
    return (
        s == "---"
        or s.startswith("#")
        or s.startswith(">")
        or s.startswith("- ")
        or s.startswith("|")
    )


def md_to_html(markdown: str) -> str:
    """Convert the report's markdown subset to an HTML body fragment."""
    lines = markdown.split("\n")
    n = len(lines)
    html = []
    i = 0
    while i < n:
        stripped = lines[i].strip()

        if not stripped:
            i += 1
            continue

        if stripped == "---":
            html.append("<hr>")
            i += 1
            continue

        m = _HEADING.match(stripped)
        if m:
            level = len(m.group(1))
            html.append(f"<h{level}>{_fmt(m.group(2))}</h{level}>")
            i += 1
            continue

        if stripped.startswith("|") and i + 1 < n and _is_separator(lines[i + 1]):
            header = _split_row(stripped)
            html.append("<table>")
            html.append(
                "<thead><tr>"
                + "".join(f"<th>{_fmt(c)}</th>" for c in header)
                + "</tr></thead>"
            )
            html.append("<tbody>")
            i += 2
            while i < n and lines[i].strip().startswith("|"):
                cells = _split_row(lines[i].strip())
                html.append(
                    "<tr>" + "".join(f"<td>{_fmt(c)}</td>" for c in cells) + "</tr>"
                )
                i += 1
            html.append("</tbody></table>")
            continue

        if stripped.startswith(">"):
            quote = []
            while i < n and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].strip())
                i += 1
            html.append("<blockquote>" + "<br>".join(_fmt(q) for q in quote) + "</blockquote>")
            continue

        if stripped.startswith("- "):
            items = []
            while i < n and lines[i].strip().startswith("- "):
                items.append(lines[i].strip()[2:])
                i += 1
            html.append("<ul>" + "".join(f"<li>{_fmt(it)}</li>" for it in items) + "</ul>")
            continue

        # Catch-all paragraph. Always consume the current line first so `i`
        # advances even for a stray block-looking line (e.g. a '|' row with no
        # separator) — guarantees progress and cannot infinite-loop.
        para = [stripped]
        i += 1
        while i < n and lines[i].strip() and not _is_block_start(lines[i].strip()):
            para.append(lines[i].strip())
            i += 1
        html.append("<p>" + "<br>".join(_fmt(p) for p in para) + "</p>")

    return "\n".join(html)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python tests/test_html_report.py`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add utils/html_report.py tests/test_html_report.py
git commit -m "feat: add bounded markdown-to-HTML converter for report export"
```

Then `git status --short` and confirm only those two files were staged.

---

## Task 2: Refactor the report generator and render the HTML document

**Files:**
- Modify: `utils/report_generator.py` (extract `build_report_markdown`)
- Modify: `utils/html_report.py` (add `_colorize_labels`, `render_html_report`, `write_html_report`)
- Test: `tests/test_html_report.py` (extend)

**Interfaces:**
- Consumes: `md_to_html` (Task 1); `build_report_markdown(result) -> str` (this task).
- Produces: `build_report_markdown(result: dict) -> str` in `report_generator.py`; `render_html_report(result: dict) -> str` and `write_html_report(result: dict, out_path) -> None` in `html_report.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_html_report.py` (add these functions above the `__main__` block, and add their calls into `__main__`):

```python
def test_build_markdown_matches_generate_report():
    from utils.report_generator import generate_report, build_report_markdown
    result = {"policy_name": "policy_x",
              "finalizer_output": {"overall_label": "Compliant", "confidence": "high"}}
    d = Path(tempfile.mkdtemp())
    try:
        p = d / "r.md"
        generate_report(result, p)
        assert p.read_text(encoding="utf-8") == build_report_markdown(result)
    finally:
        shutil.rmtree(d)


def test_render_html_full():
    from utils.html_report import render_html_report
    result = {"policy_name": "policy_x",
              "finalizer_output": {"overall_label": "Partially Compliant", "confidence": "medium"}}
    html = render_html_report(result)
    assert html.startswith("<!doctype html>")
    assert "<title>GDPR Assessment — policy_x</title>" in html
    assert "<style>" in html
    assert "<table>" in html
    assert 'class="label label-partial"' in html


def test_render_html_minimal_does_not_crash():
    from utils.html_report import render_html_report
    html = render_html_report({"policy_name": "p", "finalizer_output": {}})
    assert "<html" in html and "</html>" in html


def test_colorize_only_in_cells_and_headings():
    from utils.html_report import _colorize_labels
    body = "<p>Compliant policies vary</p><td><strong>Compliant</strong></td>"
    out = _colorize_labels(body)
    assert '<td><strong><span class="label label-compliant">Compliant</span></strong></td>' in out
    assert "<p>Compliant policies vary</p>" in out  # prose untouched


def test_colorize_longest_label_wins():
    from utils.html_report import _colorize_labels
    out = _colorize_labels("<h4>C1 — Non-Compliant</h4>")
    assert 'class="label label-noncompliant">Non-Compliant</span>' in out
    assert "label-compliant\"" not in out  # 'Compliant' inside 'Non-Compliant' not separately wrapped
```

Add to the `__main__` block:

```python
    test_build_markdown_matches_generate_report()
    test_render_html_full()
    test_render_html_minimal_does_not_crash()
    test_colorize_only_in_cells_and_headings()
    test_colorize_longest_label_wins()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python tests/test_html_report.py`
Expected: FAIL — `ImportError: cannot import name 'build_report_markdown'` (and `render_html_report`/`_colorize_labels`). Non-zero exit.

- [ ] **Step 3: Extract `build_report_markdown` in `report_generator.py`**

In `utils/report_generator.py`, the function currently is:

```python
def generate_report(result: dict, out_path: Path) -> None:
    """
    Generate a human-readable markdown report from a pipeline result dict
    and write it to out_path.
    """
    finalizer = result.get("finalizer_output", {})
    ...
    out_path.write_text("\n".join(lines), encoding="utf-8")
```

Make two edits:

(a) Rename the function line and change its docstring, so the body (everything from `finalizer = result.get(...)` down to the `lines` assembly) now builds and returns the string. Change:

```python
def generate_report(result: dict, out_path: Path) -> None:
    """
    Generate a human-readable markdown report from a pipeline result dict
    and write it to out_path.
    """
    finalizer = result.get("finalizer_output", {})
```

to:

```python
def build_report_markdown(result: dict) -> str:
    """
    Build the human-readable markdown report from a pipeline result dict and
    return it as a string. Pure: writes nothing.
    """
    finalizer = result.get("finalizer_output", {})
```

(b) Replace the final line of that function:

```python
    out_path.write_text("\n".join(lines), encoding="utf-8")
```

with:

```python
    return "\n".join(lines)


def generate_report(result: dict, out_path: Path) -> None:
    """Write the markdown report for `result` to out_path."""
    out_path.write_text(build_report_markdown(result), encoding="utf-8")
```

The section-building body in between is unchanged.

- [ ] **Step 4: Add the renderer to `utils/html_report.py`**

Append to `utils/html_report.py` (after `md_to_html`):

```python
from utils.report_generator import build_report_markdown


_LABEL_CLASS = {
    "Partially Compliant": "label-partial",
    "Non-Compliant": "label-noncompliant",
    "Compliant": "label-compliant",
}
# Longest phrases first so 'Compliant' does not pre-empt the compound labels.
_LABEL_RE = re.compile(r"Partially Compliant|Non-Compliant|Compliant")
# Labels are colored only where they appear: summary/clause table cells and clause headings.
_LABEL_ELEMENT_RE = re.compile(r"(<(td|th|h4)\b[^>]*>)(.*?)(</\2>)", re.S)


def _colorize_labels(html: str) -> str:
    """Wrap canonical compliance labels in colored badges, only inside
    <td>/<th>/<h4> elements (the report's label locations)."""
    def _wrap_phrase(pm):
        phrase = pm.group(0)
        return f'<span class="label {_LABEL_CLASS[phrase]}">{phrase}</span>'

    def _wrap_element(em):
        open_tag, _tag, inner, close_tag = em.group(1), em.group(2), em.group(3), em.group(4)
        return open_tag + _LABEL_RE.sub(_wrap_phrase, inner) + close_tag

    return _LABEL_ELEMENT_RE.sub(_wrap_element, html)


_STYLE = """<style>
  :root { --fg:#1a1a1a; --muted:#5a5a5a; --border:#d0d0d0; --bg:#fff;
          --header-bg:#f5f5f5; --zebra:#fafafa; --accent:#2c5aa0; --code-bg:#f0f0f0; }
  body { margin:0; background:var(--bg); color:var(--fg);
         font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; line-height:1.55; }
  main.report { max-width:900px; margin:0 auto; padding:2rem 1.25rem; }
  h1 { font-size:1.8rem; border-bottom:2px solid var(--border); padding-bottom:.3rem; }
  h2 { font-size:1.4rem; margin-top:2rem; border-bottom:1px solid var(--border); padding-bottom:.2rem; }
  h3 { font-size:1.15rem; margin-top:1.5rem; }
  h4 { font-size:1rem; margin-top:1.2rem; }
  table { border-collapse:collapse; width:100%; margin:1rem 0; font-size:.95rem; }
  th, td { border:1px solid var(--border); padding:.4rem .6rem; text-align:left; vertical-align:top; }
  thead th { background:var(--header-bg); }
  tbody tr:nth-child(even) { background:var(--zebra); }
  blockquote { margin:.8rem 0; padding:.5rem .9rem; border-left:4px solid var(--accent);
               background:var(--zebra); color:var(--muted); }
  code { background:var(--code-bg); padding:.1rem .3rem; border-radius:3px;
         font-family:ui-monospace,Consolas,Menlo,monospace; font-size:.9em; }
  hr { border:none; border-top:1px solid var(--border); margin:2rem 0; }
  ul { padding-left:1.4rem; }
  .label { display:inline-block; padding:.05rem .5rem; border-radius:999px; font-size:.85em; font-weight:600; }
  .label-compliant { background:#e3f4e4; color:#1b6b2a; }
  .label-partial { background:#fdf0d5; color:#8a5a00; }
  .label-noncompliant { background:#fbe3e3; color:#a11111; }
</style>"""


def render_html_report(result: dict) -> str:
    """Render a saved pipeline result as a self-contained styled HTML page."""
    policy_name = (result or {}).get("policy_name", "unknown")
    body = _colorize_labels(md_to_html(build_report_markdown(result)))
    title = _escape(f"GDPR Assessment — {policy_name}")
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{title}</title>\n"
        f"{_STYLE}\n"
        "</head>\n<body>\n"
        f'<main class="report">\n{body}\n</main>\n'
        "</body>\n</html>\n"
    )


def write_html_report(result: dict, out_path) -> None:
    """Write the HTML report for `result` to out_path."""
    Path(out_path).write_text(render_html_report(result), encoding="utf-8")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python tests/test_html_report.py`
Expected: `OK`.

- [ ] **Step 6: Confirm the report generator still imports and the full suite passes**

```powershell
python -c "from utils.report_generator import generate_report, build_report_markdown; print('IMPORT OK')"
Get-ChildItem tests/test_*.py | ForEach-Object { Write-Host "=== $($_.Name) ==="; python $_.FullName; if ($LASTEXITCODE -ne 0) { throw "FAILED: $($_.Name)" } }
```
Expected: `IMPORT OK`, then every suite prints `OK`; no `FAILED:` thrown. (The existing report-section tests exercise the unchanged body via the render helpers; they must still pass.)

- [ ] **Step 7: Commit**

```bash
git add utils/report_generator.py utils/html_report.py tests/test_html_report.py
git commit -m "feat: render a saved run as a self-contained styled HTML report"
```

Then `git status --short` and confirm only those three files were staged.

---

## Task 3: The standalone CLI

**Files:**
- Create: `report_html.py`
- Test: `tests/test_html_report.py` (extend)

**Interfaces:**
- Consumes: `write_html_report(result, out_path)` (Task 2).
- Produces: `report_html.main(path, output=None) -> int` — loads one run JSON, writes `<stem>_report.html`, prints the path; returns `0`. Forgiving: missing/invalid/not-a-run JSON prints a readable message, returns `0`, writes nothing.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_html_report.py` (functions above `__main__`, calls into `__main__`):

```python
def test_cli_writes_html():
    import json
    import report_html
    d = Path(tempfile.mkdtemp())
    try:
        j = d / "policy_x_20260101T000000Z.json"
        j.write_text(json.dumps({"policy_name": "policy_x",
                                 "finalizer_output": {"overall_label": "Compliant", "confidence": "high"}}),
                     encoding="utf-8")
        rc = report_html.main(str(j))
        assert rc == 0
        out = d / "policy_x_20260101T000000Z_report.html"
        assert out.exists()
        assert "<html" in out.read_text(encoding="utf-8")
    finally:
        shutil.rmtree(d)


def test_cli_missing_file_is_forgiving():
    import report_html
    assert report_html.main("does_not_exist_12345.json") == 0


def test_cli_not_a_run_json_writes_nothing():
    import json
    import report_html
    d = Path(tempfile.mkdtemp())
    try:
        j = d / "bad.json"
        j.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
        rc = report_html.main(str(j))
        assert rc == 0
        assert not (d / "bad_report.html").exists()
    finally:
        shutil.rmtree(d)
```

Add to `__main__`:

```python
    test_cli_writes_html()
    test_cli_missing_file_is_forgiving()
    test_cli_not_a_run_json_writes_nothing()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python tests/test_html_report.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'report_html'`. Non-zero exit.

- [ ] **Step 3: Implement the CLI**

Create `report_html.py`:

```python
"""Standalone command for rendering a saved pipeline run as an HTML report."""

import argparse
import json
import sys
from pathlib import Path

from utils.html_report import write_html_report

REQUIRED_KEYS = ("policy_name", "finalizer_output")


def load_run(path) -> dict:
    """Load one saved pipeline run JSON from disk."""
    p = Path(path)
    display_path = path if isinstance(path, str) else str(path)
    if not p.exists():
        raise ValueError(f"file not found: {display_path}")
    try:
        with p.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid JSON: {display_path} ({exc})")
    if not isinstance(data, dict) or any(key not in data for key in REQUIRED_KEYS):
        raise ValueError(f"not a pipeline run JSON (missing required keys): {display_path}")
    return data


def default_output_path(input_path) -> Path:
    """Return the default HTML output path for one run JSON."""
    input_path = Path(input_path)
    return input_path.with_name(f"{input_path.stem}_report.html")


def main(path, output=None) -> int:
    """Render an HTML report for one saved pipeline run."""
    try:
        result = load_run(path)
    except ValueError as exc:
        print(f"Cannot generate HTML report: {exc}")
        return 0

    out_path = Path(output) if output is not None else default_output_path(path)
    write_html_report(result, out_path)
    print(f"HTML report written to {out_path}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a saved pipeline run as a self-contained HTML report."
    )
    parser.add_argument("path", help="Path to a saved pipeline run JSON file.")
    parser.add_argument("--output", help="Optional output HTML path.")
    return parser


if __name__ == "__main__":
    parsed = _build_parser().parse_args()
    sys.exit(main(parsed.path, parsed.output))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python tests/test_html_report.py`
Expected: `OK`.

- [ ] **Step 5: Run the full offline suite**

```powershell
Get-ChildItem tests/test_*.py | ForEach-Object { Write-Host "=== $($_.Name) ==="; python $_.FullName; if ($LASTEXITCODE -ne 0) { throw "FAILED: $($_.Name)" } }
```
Expected: every suite prints `OK`.

- [ ] **Step 6: Commit**

```bash
git add report_html.py tests/test_html_report.py
git commit -m "feat: add report_html.py CLI for on-demand HTML report export"
```

Then `git status --short` and confirm only those two files were staged.

---

## Task 4: Document the HTML export in the README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add the artifact to the Output section**

In `README.md`, under `## Output`, after the `<policy>_<run_id>_review.md` bullet (the Human Review Brief), add:

```markdown
- **`<policy>_<run_id>_report.html`**  a self-contained, browser-viewable HTML rendering of the full report — inlined CSS (no external assets), zebra-striped tables, and color-coded compliance labels. Produced **on demand** (not automatically); see Analysis Tools below.
```

- [ ] **Step 2: Document the command under Analysis Tools**

In `## Analysis Tools`, after the `review_run.py` block, add:

```markdown
**Render a run as a shareable HTML page:**

```bash
python report_html.py output/results/<run>.json
```

Renders the full per-run report as a single self-contained HTML file (`<run>_report.html`) that opens in any browser with no network — ideal for sharing with reviewers. Read-only, zero LLM calls; reuses the exact Markdown report content, so the HTML stays in step with the `.md`. Pass `--output PATH` to choose a different destination. If the file is missing or is not a pipeline-run JSON, it prints a readable message and exits cleanly.
```

- [ ] **Step 3: Verify and commit**

Run: `git diff --stat README.md` (additions only), and confirm both fenced code blocks are properly closed.

```bash
git add README.md
git commit -m "docs: document the HTML report export and report_html.py"
```

---

## Notes for the implementer

- **No pytest.** Run a suite directly: `python tests/<file>.py`; success prints `OK`.
- **Offline only.** Never invoke the real pipeline. All tests use small fake result dicts and temp dirs.
- **The refactor in Task 2 must be behavior-preserving** — the section-building body of the old `generate_report` moves verbatim into `build_report_markdown`; only the function name/docstring and the final write line change. `test_build_markdown_matches_generate_report` guards this.
- **Escaping order matters:** `_escape` runs before `_inline` so `**`/`` ` `` still work while raw `<`/`>`/`&` in policy text cannot inject markup.
- **Label coloring is bounded** to `<td>`/`<th>`/`<h4>` via `_LABEL_ELEMENT_RE`, and the alternation `_LABEL_RE` lists the compound labels first so `Non-Compliant` is never mis-split into a separate `Compliant` badge (guarded by `test_colorize_longest_label_wins`).
- **`_STYLE` is a plain (non-f) string** so its CSS braces are literal; only `render_html_report` interpolates the title and body.
- The em dash `—` in the `<title>` and headings is intentional; the file is written UTF-8 with a `<meta charset="utf-8">`.
