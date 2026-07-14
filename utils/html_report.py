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
