# prompt2GDPR-v2

An agentic workflow for assessing privacy policy compliance with **GDPR Article 5(1)(b) — Purpose Limitation**, built as a research extension of a master's thesis at the University of Bologna (2025/2026).

The system replaces single-prompt LLM evaluation with a structured 4-agent pipeline that is more evidence-grounded, more stable, and more explainable than the thesis baseline.

---

## Background

The original thesis assessed privacy policies against all 7 GDPR Article 5 principles using single-prompt GPT and Grok models. Three critical limitations were identified:

1. **Misplaced evidence**: models cited real but irrelevant policy sections
2. **Prompt-sensitive labels**: compliance labels changed when prompt wording changed
3. **No autonomous reliability**: human expert review remained essential with no structured quality control

This project addresses all three by scoping to Article 5(1)(b) and introducing a multi-agent architecture with self-correction, dual independent auditing, and on-demand legal reference retrieval.

---

## Pipeline Architecture

```
Policy Text (.txt)
      │
      ▼
[Agent 1: Extractor]
      │  Extracts all verbatim clauses relevant to purpose limitation (3 steps)
      ▼
[String-Match Verifier]
      │  Checks clause quotes against policy text (rapidfuzz ≥ 85% threshold)
      │  → verified_clauses / flagged_clauses
      ▼
[Agent 2: Evaluator]  ← uses get_legal_reference tool (on demand)
      │  Applies two-stage rubric: Purpose Specification + Compatibility Assessment
      │  Retrieves primary sources (Art. 5(1)(b), Art. 89, Recitals 39/50/157) first
      │  Falls back to secondary sources (WP29 Opinion 03/2013) only if needed
      ▼
[Agent 3A: Reflector A] ──┐
[Agent 3B: Reflector B] ──┴→ [Merge] → unified error report + agreement rate
      │  5 audit checks: phantom clauses, justification grounding,
      │  internal consistency, Article 89 handling, overall label derivation
      │  If errors found → retry loop (max 2 retries per agent)
      ▼
[Agent 4: Finalizer]
      │  Consolidates all outputs into final compliance report
      │  Sets confidence: high / medium / low
      │  Always flags for human expert review
      ▼
JSON output → output/results/
```

---

## Agents

| Agent | Role | Tools |
|---|---|---|
| **Extractor** | Finds and quotes all purpose limitation clauses (max 15) | None |
| **Evaluator** | Applies two-stage GDPR rubric per clause | `get_legal_reference` |
| **Reflector A & B** | Independent parallel audit of Agents 1 & 2 | None |
| **Finalizer** | Consolidates outputs into structured compliance report | None |

---

## Legal Reference Tools

The Evaluator agent retrieves legal sources on demand rather than having them injected statically into the prompt. The model decides what it needs based on the clause content.

**Primary sources** (binding law — consulted first):
- `article_5_1b` — GDPR Article 5(1)(b)
- `article_89` — GDPR Article 89 (research/archiving exceptions)
- `recital_39` — Purpose specification at time of collection
- `recital_50` — Compatible further processing criteria
- `recital_157` — Scientific research and statistical purposes

**Secondary sources** (authoritative, not binding — consulted only if primary is insufficient):
- `wp29_purpose_limitation` — WP29 Opinion 03/2013 (WP203) key excerpts

All references consulted are logged in the evaluator output under `references_used[]`.

---

## Project Structure

```
prompt2gdpr_v2/
├── main.py                        # Orchestrator
├── config.py                      # Models, token limits, per-agent defaults
├── agents/
│   ├── extractor.py               # Agent 1
│   ├── evaluator.py               # Agent 2 (tool-calling loop)
│   ├── reflector.py               # Agent 3 (called as A and B)
│   └── finalizer.py               # Agent 4
├── prompts/
│   ├── extractor_prompt.py
│   ├── evaluator_prompt.py
│   ├── reflector_prompt.py
│   └── finalizer_prompt.py
├── utils/
│   ├── verifier.py                # String-match clause verification
│   ├── schema_validator.py        # JSON parse + repair + validate
│   ├── reflector_merge.py         # Dual reflector merge logic
│   └── legal_tools.py             # Legal reference tool definitions + executor
├── data/
│   ├── policies/                  # Input policy text files (.txt)
│   └── legal_refs/
│       ├── primary/               # GDPR articles and recitals
│       └── secondary/             # WP29/EDPB opinion excerpts
└── output/
    └── results/                   # Per-run JSON outputs
```

---

## Setup

**1. Clone the repo:**
```bash
git clone https://github.com/maederhkh/prompt2GDPR-v2.git
cd prompt2GDPR-v2
```

**2. Install dependencies:**
```bash
pip install openai pydantic rapidfuzz python-dotenv json-repair
```

**3. Add your OpenRouter API key:**

Create a `.env` file in the project root:
```
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxx
```

Get a free API key at [openrouter.ai](https://openrouter.ai).

**4. Add policy files:**

Place plain text (`.txt`) privacy policy files in `data/policies/`.

**5. Add legal reference texts:**

Fill in the files under `data/legal_refs/primary/` and `data/legal_refs/secondary/` with the official GDPR text and WP29 excerpts. Sources:
- Articles and recitals: [gdpr-info.eu](https://gdpr-info.eu)
- WP29 Opinion 03/2013: [EC archive](https://ec.europa.eu/justice/article-29/documentation/opinion-recommendation/files/2013/wp203_en.pdf)

---

## Usage

**Basic run (default model — Claude Sonnet 4.5):**
```bash
python main.py --policy data/policies/policy_long.txt
```

**Specify a model:**
```bash
python main.py --policy data/policies/policy_long.txt --model openai/gpt-4o
```

**Use different models per agent:**
```bash
python main.py --policy data/policies/policy_long.txt \
  --model-extractor 
  --model-evaluator 
  --model-reflector-a
  --model-reflector-b 
  --model-finalizer 

**Run multiple times to measure label stability (M3):**
```bash
python main.py --policy data/policies/policy_long.txt --runs 3
```

**All CLI options:**
```
--policy            Path to policy text file (required)
--runs              Number of runs for M3 stability (default: 1)
--model             Global model for all agents (default: anthropic/claude-sonnet-4-5)
--model-extractor   Model override for Agent 1
--model-evaluator   Model override for Agent 2
--model-reflector-a Model override for Agent 3A
--model-reflector-b Model override for Agent 3B
--model-finalizer   Model override for Agent 4
--output-dir        Output directory (default: output/results/)
```

Model slugs follow OpenRouter format: `provider/model-name`
Full list at [openrouter.ai/models](https://openrouter.ai/models).

---

## Output

Each run produces a JSON file in `output/results/` containing:
- All agent outputs (extractor, evaluator, both reflectors, finalizer)
- Verified and flagged clauses
- Legal references consulted by the Evaluator
- Inter-reflector agreement statistics
- M1–M5 evaluation metrics
- Final compliance label: `Compliant` / `Partially Compliant` / `Non-Compliant`
- Confidence level: `high` / `medium` / `low`
- Human review notes and unresolved flags

---

## Known Limitations

- **Extraction cap**: The Extractor retrieves a maximum of 15 clauses. For long policies with more relevant content, `coverage_complete: false` is set in the output and flagged for human review. Full coverage via chunked extraction is planned as a future extension.
- **Human review required**: The system is designed as decision support, not a replacement for legal expert judgment. `human_review_recommended` is always `true` in the final report.

---

## Research Context

This project is a direct extension of:

> Rahmanikhalili, M. (2026). *Assessing Privacy Policy Compliance with GDPR Article 5 Using Large Language Models*. Master's thesis, University of Bologna.

The agentic approach directly addresses the three limitations identified in the thesis and introduces a dual-reflector architecture and on-demand legal reference retrieval as novel contributions.
