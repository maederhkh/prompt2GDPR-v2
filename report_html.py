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
