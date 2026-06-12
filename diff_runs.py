"""Compare two pipeline run JSONs clause by clause.

Usage:  python diff_runs.py <run_a.json> <run_b.json>
Prints the diff to the terminal and writes
output/results/diff_<a>_vs_<b>.md. The run JSONs are never modified.
"""
import sys

from utils.run_diff import main

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python diff_runs.py <run_a.json> <run_b.json>")
        sys.exit(0)
    sys.exit(main(sys.argv[1], sys.argv[2]))
