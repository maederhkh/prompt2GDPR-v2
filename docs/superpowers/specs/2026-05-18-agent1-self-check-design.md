# Design Spec: Agent 1 Self-Check (Pass 3)

**Date:** 2026-05-18  
**Component:** Agent 1 — Extractor  
**Type:** New feature — completeness self-check  

---

## 1. Problem

After Pass 2 (Deep Extractor), some paragraphs inside relevant sections may be silently skipped. The Deep Extractor reads one section at a time and extracts purpose limitation clauses, but it may not quote every paragraph that contains relevant content. These missed paragraphs never reach Agent 2 (Evaluator), making the compliance assessment incomplete.

The String-Match Verifier catches fabricated quotes but does not detect missed content — it only checks what Agent 1 did extract, not what it failed to extract.

---

## 2. Solution

Add **Pass 3: Self-Check** as a third internal pass inside `agents/extractor.py`. After Pass 2 completes, Pass 3 automatically:

1. Detects which paragraphs inside Scout-identified sections were not covered by any extracted clause
2. Asks Gemini Flash to judge whether each uncovered paragraph contains missed purpose limitation content
3. Re-extracts confirmed gap paragraphs using GPT-5.3
4. Reports everything — fixed and unfixed — in a new `self_check_report` key in the output

The public interface of `run_extractor()` is unchanged. No modifications to `main.py` or any downstream component.

---

## 3. Architecture

```
Pass 1: Scout              → finds relevant section headings (Gemini Flash)
Pass 2: Deep Extractor     → extracts clauses per section (GPT-5.3)
Pass 3: Self-Check (NEW)   → finds and fills coverage gaps
        ↓
Output with self_check_report → String-Match Verifier (unchanged)
```

### Three filters that limit what Gemini Flash sees in Pass 3

| Filter | What it removes |
|---|---|
| Scout (Pass 1) | All sections not identified as relevant |
| Deep Extractor output (Pass 2) | All paragraphs already covered by extracted clauses |
| Fuzzy match (Pass 3 Python) | All paragraphs with ≥60% similarity to any extracted clause |

By the time Gemini Flash sees anything, it is looking only at uncovered paragraphs inside already-relevant sections.

---

## 4. Pass 3 — Detailed Steps

### Step 1 — Paragraph Coverage Detection (Python only, no LLM)

For each section processed in Pass 2:

1. Split the section text into paragraphs by double newline (`\n\n`)
2. For each paragraph, compute fuzzy similarity against all extracted clause quotes from that section using `fuzz.partial_ratio` (threshold: 60%)
3. Paragraphs below 60% similarity to any clause quote → flagged as uncovered

**Why 60%?** Loose enough to handle minor whitespace and formatting differences between the section text and the extracted quote, while still flagging genuinely skipped paragraphs.

**Output:**
```python
uncovered = [
    {"section_name": "3.18 Legal claims", "paragraph": "All data is encrypted..."},
    {"section_name": "3.8 Statistical", "paragraph": "We aggregate usage data..."},
]
```

---

### Step 2 — Gap Judgement (Gemini Flash, one call per uncovered paragraph)

For each uncovered paragraph, one Gemini Flash call asks:

> *"Does this paragraph contain purpose limitation content not already covered by the extracted clauses?"*

**Input to Gemini:**
- The uncovered paragraph text
- Already-extracted clauses from that section (to prevent false positives)
- The yes/no question

**Output:**
```json
{
    "is_gap": true,
    "reason": "Paragraph describes safeguards for legal claims processing — relevant to Stage 2 compatibility assessment but not captured."
}
```

**Routing:**
- `is_gap = true` → send to GPT-5.3 for re-extraction
- `is_gap = false` → skip, not purpose limitation content

**Why Gemini Flash?** This is a binary yes/no judgment on a single paragraph. A cheap, fast model is sufficient. The expensive model (GPT-5.3) is reserved for the next step.

---

### Step 3 — Re-extraction (GPT-5.3, one call per confirmed gap)

For each paragraph where Gemini confirmed `is_gap = true`:

**Input to GPT-5.3:**
- The gap paragraph text
- The section name
- Already-extracted clauses from that section
- Starting clause ID (continues from where Pass 2 left off)
- Instruction to quote verbatim and not re-extract already-captured content

**Output:**
```json
{
    "extracted_clauses": [
        {
            "clause_id": "C17",
            "quote": "All data is encrypted in a secure vault with strict access controls.",
            "section_reference": "3.18 Legal claims",
            "relevance_type": "secondary_use"
        }
    ]
}
```

**Routing:**
- New clauses found → add to `all_clauses`, increment clause counter, record as `gap_filled`
- No clauses found → record as `gap_unresolved`, flag for human reviewer

---

### Step 4 — Build `self_check_report`

After all uncovered paragraphs are processed, build the report:

```json
{
    "self_check_report": {
        "paragraphs_checked": 12,
        "gaps_found": 3,
        "gaps_filled": 2,
        "gaps_unresolved": 1,
        "new_clauses_added": ["C17", "C23"],
        "unresolved_gaps": [
            {
                "section_name": "3.18 Legal claims",
                "paragraph": "All data is encrypted...",
                "reason": "GPT-5.3 found no extractable purpose limitation content after re-extraction."
            }
        ],
        "human_review_note": "1 paragraph gap could not be resolved. Human reviewer should manually check section 3.18 Legal claims."
    }
}
```

When no gaps are found:
```json
{
    "self_check_report": {
        "paragraphs_checked": 8,
        "gaps_found": 0,
        "gaps_filled": 0,
        "gaps_unresolved": 0,
        "new_clauses_added": [],
        "unresolved_gaps": [],
        "human_review_note": null
    }
}
```

---

## 5. Models Used in Pass 3

| Step | Model | Reason |
|---|---|---|
| Gap judgement | `google/gemini-3-flash-preview` | Binary yes/no judgment — cheap and fast |
| Re-extraction | `openai/gpt-5.3-chat` | Same model as Pass 2 — consistent extraction quality |

Both models are passed into `run_extractor()` via existing parameters — no new config changes needed.

---

## 6. Files Changed

| File | Change |
|---|---|
| `agents/extractor.py` | Add `_self_check()`, `_judge_paragraph_gap()`, `_reextract_gap()` internal functions. Call `_self_check()` after Pass 2 inside `run_extractor()`. |
| `prompts/extractor_prompt.py` | Add `SELF_CHECK_JUDGE_TEMPLATE` and `build_gap_judge_prompt()` for Gemini Flash gap judgment prompt. |
| No other files | `main.py`, verifier, evaluator, reflector, finalizer — all unchanged |

---

## 7. How Downstream Agents Use `self_check_report`

| Component | How it uses the report |
|---|---|
| String-Match Verifier | Verifies new clauses from `new_clauses_added` exactly like Pass 2 clauses |
| Reflector | Sees `unresolved_gaps` and `human_review_note` — can flag for human review |
| Finalizer | Surfaces `human_review_note` in final report if not null |
| Human reviewer | Reads `unresolved_gaps` to know exactly which paragraphs to check manually |

---

## 8. Error Handling

| Failure | Behaviour |
|---|---|
| Gemini Flash call fails | Log warning, treat paragraph as `is_gap = false`, continue |
| GPT-5.3 re-extraction fails | Log warning, record paragraph as `gap_unresolved`, continue |
| No uncovered paragraphs found | Skip Pass 3 entirely, `self_check_report` shows all zeros |
| Single-pass fallback active | Skip Pass 3 entirely — no section boundaries available |

Pass 3 never causes the pipeline to crash. All failures are recorded in `self_check_report` and flagged for human review.

---

## 9. LLM Call Count Impact

| Scenario | Additional calls from Pass 3 |
|---|---|
| No uncovered paragraphs | 0 |
| N uncovered paragraphs, none confirmed as gaps | N (Gemini Flash only) |
| N uncovered paragraphs, M confirmed as gaps | N (Gemini) + M (GPT-5.3) |

In practice, most sections will have few or no uncovered paragraphs — Pass 3 is lightweight in normal operation.

---


