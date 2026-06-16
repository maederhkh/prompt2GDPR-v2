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
