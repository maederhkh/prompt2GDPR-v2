"""Print and write an aggregate summary of all pipeline runs.

Usage:  python analyze_runs.py
Reads output/results/runs_index.csv and writes output/results/runs_summary.md.
The runs index itself is never modified.
"""
import sys

from utils.runs_summary import main

if __name__ == "__main__":
    sys.exit(main())
