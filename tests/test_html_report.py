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
