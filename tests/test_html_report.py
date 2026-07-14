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
    test_build_markdown_matches_generate_report()
    test_render_html_full()
    test_render_html_minimal_does_not_crash()
    test_colorize_only_in_cells_and_headings()
    test_colorize_longest_label_wins()
    print("OK")
