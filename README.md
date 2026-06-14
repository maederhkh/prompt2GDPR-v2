# prompt2GDPR-v2

An agentic workflow for assessing privacy policy compliance with **GDPR Article 5(1)(b)  Purpose Limitation**, built as a research extension of a master's thesis at the University of Bologna (2025/2026).

The system replaces single-prompt LLM evaluation with a structured multi-agent pipeline that is more evidence-grounded, more stable, and more explainable than the thesis baseline. Beyond producing a label, it **measures its own reliability**: independent dual auditing, a blind-labeling tier that quantifies anchoring bias, and full per-run provenance.

---

## Background

The original thesis assessed privacy policies against all 7 GDPR Article 5 principles using single-prompt GPT and Grok models. Three critical limitations were identified:

1. **Misplaced evidence**: models cited real but irrelevant policy sections
2. **Prompt-sensitive labels**: compliance labels changed when prompt wording changed
3. **No autonomous reliability**: human expert review remained essential with no structured quality control

This project addresses all three by scoping to Article 5(1)(b) and introducing a multi-agent architecture with self-correction, dual independent auditing, blind-label anchoring measurement, and on-demand legal reference retrieval.

---

## Pipeline Architecture

```
Policy Text (.txt)
      │
      ▼
[Agent 1 · Pass 1: Scout]
      │  Reads the full policy and maps which sections are likely to contain
      │  purpose-limitation content (no extraction, no assessment)
      ▼
[Agent 1 · Pass 2: Deep Extractor]
      │  Extracts verbatim clauses from each scouted section
      ▼
[String-Match Verifier]
      │  Checks every clause quote against the policy text (rapidfuzz ≥ 85%)
      │  → verified_clauses / flagged_clauses
      ▼
[Agent 2: Evaluator]  ← uses get_legal_reference tool (on demand)
      │  Two-stage rubric: Purpose Specification + Compatibility Assessment
      │  Consults primary sources (Art. 5(1)(b), Art. 89, Recitals 39/50/157) first,
      │  secondary sources (WP29 Opinion 03/2013) only if needed
      ▼
[Agent 3A: Reflector A] ──┐
[Agent 3B: Reflector B] ──┴→ [Merge] → unified error report + agreement rate
      │  5 audit checks: phantom clauses, justification grounding,
      │  internal consistency, Article 89 handling, overall-label derivation
      │  If errors found → retry loop (max 2 retries per agent)
      ▼
[Blind Labeler A / B]  (optional tier — toggle with --no-blind-labeler)
      │  Re-label every clause with the SAME rubric but WITHOUT seeing the
      │  evaluator/reflector output → unanchored "blind" labels
      ▼
[Label Panel]
      │  Assembles evaluator + reflector + blind labels per clause,
      │  flags disputed clauses, and computes the anchoring shift rate
      │  (how often an anchored label differs from its blind counterpart)
      ▼
[Agent 4: Finalizer]
      │  Consolidates all outputs into the final compliance report,
      │  sets confidence (high / medium / low), always flags human review
      ▼
Outputs → output/results/
  · <policy>_<run_id>.json            (full result)
  · <policy>_<run_id>_report.md       (readable report)
  · runs_index.md / runs_index.csv    (one summary row per run, cumulative)
```

---

## Agents

| Agent | Role | Tools |
|---|---|---|
| **Scout** (Agent 1, Pass 1) | Maps which policy sections likely contain purpose-limitation content | None |
| **Deep Extractor** (Agent 1, Pass 2) | Extracts verbatim clauses from each scouted section | None |
| **Evaluator** (Agent 2) | Applies the two-stage GDPR rubric per clause | `get_legal_reference` |
| **Reflector A & B** (Agent 3) | Independent parallel audit of Agents 1 & 2; drives the retry loop | None |
| **Blind Labeler A & B** | Re-label each clause blind (no anchoring) for the anchoring measurement | `get_legal_reference` |
| **Finalizer** (Agent 4) | Consolidates outputs into the structured compliance report | None |

---

## Reliability Instrumentation

Three mechanisms turn the pipeline from "produces a label" into "produces a label *and reports how much to trust it*":

- **Dual reflectors + merge.** Two independent auditors review the extractor and evaluator outputs in parallel; their findings are merged and an **agreement rate** is recorded. Disagreement lowers final confidence.
- **Blind-label anchoring measurement.** The Blind Labelers assign a compliance label to every clause using the same rubric but **without** seeing the anchored (evaluator/reflector) labels. The **Label Panel** compares the two and reports a per-reflector **shift rate** — a direct, quantified measure of anchoring bias. Temperature is fixed at `0` for all label-producing calls so a blind-vs-anchored difference reflects the model, not sampling noise. Toggle the tier off with `--no-blind-labeler`.
- **Dispute detection.** When labelers disagree on a clause, the Label Panel marks it `disputed`, the Finalizer downgrades confidence to `low`, and the clause is surfaced for human review — the Evaluator's label is retained as official but never silently.

---

## Legal Reference Tools

The Evaluator and Blind Labelers retrieve legal sources on demand rather than having them injected statically into the prompt. The model decides what it needs based on the clause content.

**Primary sources** (binding law — consulted first):
- `article_5_1b`: GDPR Article 5(1)(b)
- `article_89`: GDPR Article 89 (research/archiving exceptions)
- `recital_39`: Purpose specification at time of collection
- `recital_50`: Compatible further processing criteria
- `recital_157`: Scientific research and statistical purposes

**Secondary sources** (authoritative, not binding  consulted only if primary is insufficient):
- `wp29_purpose_limitation`  WP29 Opinion 03/2013 (WP203) key excerpts

All references consulted are logged in the evaluator output under `references_used[]`.

---

## Usage

Set your OpenRouter key in a `.env` file at the project root:

```
OPENROUTER_API_KEY=sk-or-...
```

Run the pipeline on a policy:

```bash
python main.py --policy data/policies/policy_short.txt
```

Common options:

| Flag | Purpose |
|---|---|
| `--policy PATH` | Path to the policy `.txt` file (required) |
| `--runs N` | Run the pipeline N times for label-stability measurement (default: 1) |
| `--model SLUG` | Global model for all agents (overridden per-agent below) |
| `--model-scout` / `--model-extractor` / `--model-evaluator` / `--model-reflector-a` / `--model-reflector-b` / `--model-finalizer` | Per-agent model overrides |
| `--no-blind-labeler` | Skip the Blind Labeler tier (2 fewer LLM calls; no anchoring delta) |
| `--output-dir DIR` | Where to write results (default: `output/results/`) |

---

## Output

Each run writes to `output/results/`:

- **`<policy>_<run_id>.json`** — the full result: all agent outputs (scout, extractor, evaluator, both reflectors, blind labelers, finalizer), verified/flagged clauses, the label panel, legal references consulted, inter-reflector agreement, anchoring shift rates, M1–M5 evaluation metrics, and run metadata.
- **`<policy>_<run_id>_report.md`**  a human-readable report, including a Run Metadata block for provenance.
- **`runs_index.md` / `runs_index.csv`**  a cumulative index with **one summary row per run** (run ID, policy, commit, overall label, confidence, clause count, agreement rate, retries, disputed count, blind on/off, anchoring shift A/B). The `.md` is for a quick glance; the `.csv` opens directly in Excel/pandas.

The final compliance label is one of `Compliant` / `Partially Compliant` / `Non-Compliant`, with a confidence level of `high` / `medium` / `low` and always `human_review_recommended: true`.

## Analysis Tools

Two standalone, **on-demand** tools turn the per-run artifacts into research evidence. Both are read-only, make zero LLM calls, and are **never invoked by the pipeline** — run them yourself when you want them. Each prints to the terminal and writes one markdown file you can delete and regenerate anytime.

**Aggregate summary across all runs:**

```bash
python analyze_runs.py
```

Reads `output/results/runs_index.csv` and writes `output/results/runs_summary.md` — Overall and Per-policy statistics (volume & coverage, compliance outcomes, and reliability: agreement rate, disputes, anchoring). Answers "across every run so far, how stable are the verdicts?".

**Clause-level diff of two runs:**

```bash
python diff_runs.py <run_a.json> <run_b.json>
```

Compares two run JSONs clause by clause and model by model, writing `output/results/diff_<a>_vs_<b>.md`. Because clause IDs are assigned per run, clauses are matched across runs by their verbatim quote text (exact match first, then fuzzy ≥ 90). The diff reports the overall-label / confidence verdicts, a **Models** table (which agent ran which model in each run), **label changes** on matched clauses, clauses **only in one run** (extraction instability), and an unchanged count. If the two runs are for different policies it still produces the diff but prints a loud warning. This is the measuring instrument for run-to-run stability and model-swap experiments.

### Run metadata & reproducibility

Every result is stamped with provenance so any run can be reproduced and located:

- `run_id`  compact UTC timestamp (`YYYYMMDDTHHMMSSZ`), also the output filename stem
- `utc_timestamp`, `git_commit` (sha + dirty flag), `policy_file`, `policy_sha256`
- `temperature`, `blind_enabled`, `clause_count`

---

## Project Structure

```
prompt2gdpr_v2/
├── main.py                        # Orchestrator + CLI
├── config.py                      # Models, token budgets, feature toggles, temperature
├── analyze_runs.py                # On-demand: aggregate summary over all runs
├── diff_runs.py                   # On-demand: clause-level diff of two runs
├── agents/
│   ├── extractor.py               # Agent 1 (Scout Pass 1 + Deep Extractor Pass 2)
│   ├── evaluator.py               # Agent 2 (tool-calling loop)
│   ├── reflector.py               # Agent 3 (called as A and B)
│   ├── blind_labeler.py           # Blind labeling tier (anchoring measurement)
│   └── finalizer.py               # Agent 4
├── prompts/
│   ├── scout_prompt.py
│   ├── extractor_prompt.py
│   ├── evaluator_prompt.py
│   ├── reflector_prompt.py
│   ├── blind_labeler_prompt.py
│   ├── finalizer_prompt.py
│   └── rubric.py                  # Shared two-stage rubric block
├── utils/
│   ├── section_splitter.py        # Splits policy into sections for the two-pass extractor
│   ├── verifier.py                # String-match clause verification (rapidfuzz)
│   ├── schema_validator.py        # JSON parse + repair + validate
│   ├── reflector_merge.py         # Dual-reflector merge logic
│   ├── label_panel.py             # Per-clause label panel + anchoring/dispute computation
│   ├── legal_tools.py             # Legal reference tool definitions + executor
│   ├── run_metadata.py            # Per-run provenance (run_id, git, policy hash)
│   ├── runs_index.py              # Cumulative runs index (md + csv)
│   ├── runs_summary.py            # Aggregate runs summary (analyze_runs.py)
│   ├── run_diff.py                # Clause-level run comparison (diff_runs.py)
│   └── report_generator.py        # Markdown report rendering
├── evaluation/
│   └── metrics.py                 # M1–M5 evaluation metrics
├── data/
│   ├── policies/                  # Input policy text files (.txt)
│   └── legal_refs/
│       ├── primary/               # GDPR articles and recitals
│       └── secondary/             # WP29/EDPB opinion excerpts
└── output/
    └── results/                   # Per-run JSON, markdown reports, runs index
```

---

## Known Limitations

- **Human review required**: The system is designed as decision support, not a replacement for legal expert judgment. `human_review_recommended` is always `true` in the final report.
- **Coverage signalling**: When the extractor cannot confidently cover a long policy in full, `coverage_complete: false` is set in the output and flagged for human review.

---

## Research Context

This project is a direct extension of:

> Rahmanikhalili, M. (2026). *Assessing Privacy Policy Compliance with GDPR Article 5 Using Large Language Models*. Master's thesis, University of Bologna.

The agentic approach directly addresses the three limitations identified in the thesis and introduces a dual-reflector architecture, a blind-label anchoring measurement, and on-demand legal reference retrieval as novel contributions.
