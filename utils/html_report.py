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
