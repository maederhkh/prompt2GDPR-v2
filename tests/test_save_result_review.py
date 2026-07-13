"""Offline tests for automatic review-brief generation in save_result."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import main


def _min_result() -> dict:
    # The renderer is defensive; policy_name + finalizer_output is enough.
    return {
        "policy_name": "policy_x",
        "finalizer_output": {"overall_label": "Compliant", "confidence": "high"},
    }


def test_write_review_brief_creates_file():
    d = Path(tempfile.mkdtemp())
    try:
        path = main._write_review_brief(_min_result(), d, "policy_x_run")
        assert path is not None
        assert path.exists()
        assert path.name == "policy_x_run_review.md"
        assert "# Human Review Brief" in path.read_text(encoding="utf-8")
    finally:
        shutil.rmtree(d)


def test_write_review_brief_never_raises():
    # A broken renderer must be swallowed so a good run still succeeds.
    d = Path(tempfile.mkdtemp())
    original = main.write_review_report

    def _boom(*args, **kwargs):
        raise RuntimeError("render failed")

    try:
        main.write_review_report = _boom
        path = main._write_review_brief(_min_result(), d, "policy_x_run")
        assert path is None
    finally:
        main.write_review_report = original
        shutil.rmtree(d)


if __name__ == "__main__":
    test_write_review_brief_creates_file()
    test_write_review_brief_never_raises()
    print("OK")
