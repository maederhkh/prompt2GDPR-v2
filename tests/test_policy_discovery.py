"""Standalone assert tests for discover_policy_files."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.policy_loader import discover_policy_files


def _touch(d: Path, name: str):
    (d / name).write_text("x", encoding="utf-8")


def test_finds_supported_sorted_case_insensitive():
    d = Path(tempfile.mkdtemp())
    try:
        _touch(d, "Bravo.txt")
        _touch(d, "alpha.PDF")        # uppercase extension still supported
        _touch(d, "charlie.docx")
        _touch(d, "notes.xyz")        # unsupported -> skipped
        _touch(d, "image.png")        # unsupported -> skipped
        names = [p.name for p in discover_policy_files(d)]
        # alpha.PDF, Bravo.txt, charlie.docx — case-insensitive name sort
        assert names == ["alpha.PDF", "Bravo.txt", "charlie.docx"], names
    finally:
        shutil.rmtree(d)


def test_non_recursive_skips_subfolders():
    d = Path(tempfile.mkdtemp())
    try:
        _touch(d, "top.txt")
        sub = d / "nested"
        sub.mkdir()
        _touch(sub, "deep.txt")       # in a subfolder -> not discovered
        names = [p.name for p in discover_policy_files(d)]
        assert names == ["top.txt"], names
    finally:
        shutil.rmtree(d)


def test_empty_or_all_unsupported_returns_empty_list():
    d = Path(tempfile.mkdtemp())
    try:
        _touch(d, "readme.xyz")
        assert discover_policy_files(d) == []
    finally:
        shutil.rmtree(d)


if __name__ == "__main__":
    test_finds_supported_sorted_case_insensitive()
    test_non_recursive_skips_subfolders()
    test_empty_or_all_unsupported_returns_empty_list()
    print("OK")
