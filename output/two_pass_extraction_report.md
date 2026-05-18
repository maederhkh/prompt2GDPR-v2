# Two-Pass Extraction: Change Report

**Date:** 2026-04-20  
**Component:** Agent 1 — Extractor  
**Type:** Architectural improvement  

---

## 1. The Problem

During a test run on the Ada Health privacy policy (`policy_long.txt`), clause C15 was extracted from section **3.18 — Using your data to exercise or defend against legal claims**. The Evaluator's justification for C15 stated:

> *"There is no meaningful purpose link between the original health assessment purposes and legal defense… the clause does not consider the sensitive nature of health data in this context, does not assess impact, and **states no safeguards**."*

However, the actual policy section includes a sentence about **encryption, vault storage, and access limitation** — safeguards that are directly relevant to the Stage 2 compatibility assessment. The Evaluator correctly assessed what it was given, but it was given an incomplete quote.

**Root cause:** The Extractor was reading the full policy text in a single pass and quoting only the sentence that stated the purpose, stopping before the safeguard or legal basis text that followed in the same paragraph.

This is not a one-off failure. It is a structural limitation of single-pass extraction over long documents:
- The model scans for purpose language, finds a sentence, quotes it, and moves on.
- Text that follows in the same paragraph — safeguards, conditions, legal basis statements — is silently dropped.
- The Evaluator then assesses an incomplete picture and may reach an incorrect label.

---

## 2. The Old Approach — Single-Pass Extraction

**File:** `agents/extractor.py` (original), `prompts/extractor_prompt.py`

The original `run_extractor` function made **one LLM call** over the entire policy text:

```
Full policy text (all sections mixed together)
        │
        ▼
[Single LLM call: find up to 15 purpose limitation clauses]
        │
        ▼
extracted_clauses (verbatim quotes, but often truncated to one sentence)
```

**Problems with this approach:**

| Problem | Description |
|---|---|
| Sentence-level quoting | Model quoted only the purpose sentence, not the full paragraph |
| Arbitrary cap | Maximum 15 clauses regardless of policy length — long policies were truncated |
| Coverage gaps | Model might miss sections near the end of a long document |
| Mixed context | Model had to scan everything at once, which increases the chance of oversights |

The prompt instruction said: *"Quote each clause verbatim."* But it did not say to include the full paragraph — so the model interpreted "clause" as a single sentence.

---

## 3. The New Approach — Two-Pass Extraction

**Files changed/created:**
- `agents/extractor.py` — rewritten to orchestrate two passes
- `prompts/extractor_prompt.py` — new section-level prompt added
- `prompts/scout_prompt.py` — new file (Pass 1 prompt)
- `utils/section_splitter.py` — new file (section boundary detection)

### Pass 1 — Section Scout

A lightweight LLM call reads the full policy and returns only a list of section headings that are likely to contain purpose limitation content. It does **no extraction** — it only produces a map.

**Input:** Full policy text  
**Output:** `{"relevant_sections": ["3.1 When you access our Services", "3.8 Statistical purposes", "3.18 Legal claims", ...]}`

**Why a separate pass?**  
Asking one model call to both find all relevant sections AND extract all clauses from all of them simultaneously is too much. Separating the two tasks means each step is focused and reliable.

### Section Splitter (Python, no LLM)

After the Scout returns section names, pure Python code (`utils/section_splitter.py`) locates each section's boundaries in the policy text using fuzzy string matching (rapidfuzz). It then slices out the full text of each section.

**No LLM is used here.** This is a deterministic step.

**Input:** Full policy text + list of section names from Scout  
**Output:** `[{"name": "3.18 Legal claims", "text": "We will use data... [full paragraph including safeguards]"}, ...]`

### Pass 2 — Deep Extractor (one call per section)

For each section identified in Pass 1, a focused LLM call extracts purpose limitation clauses. Because the model now receives only one section at a time, and the prompt explicitly says to **quote the complete paragraph**, it cannot stop at the first sentence.

**Input:** Single section text  
**Output:** Extracted clauses with complete paragraph quotes

The new prompt instruction says:

> *"Quote the complete paragraph, not just the sentence that states the purpose. If the purpose statement is followed by a legal basis, safeguard description, or condition in the same paragraph, include all of it in the quote."*

### How the two passes fit together

```
Full policy text
        │
        ▼
[Pass 1: Section Scout]  ← one LLM call, cheap and fast
        │
        ▼
List of relevant section headings
        │
        ▼ (Python — no LLM)
[Section Splitter]  ← locates boundaries using fuzzy matching
        │
        ▼
Section chunks: [{name, full_text}, {name, full_text}, ...]
        │
        ├── Section 1 → [Pass 2: Deep Extractor] → clauses C1, C2
        ├── Section 2 → [Pass 2: Deep Extractor] → clause C3
        ├── Section 3 → [Pass 2: Deep Extractor] → clauses C4, C5, C6
        └── Section N → [Pass 2: Deep Extractor] → clause CN
                │
                ▼
All clauses merged → verified_clauses (complete paragraph quotes)
```

---

## 4. What Changed in Each File

### `agents/extractor.py` — Complete rewrite

| Before | After |
|---|---|
| One function: `run_extractor` | `run_extractor` orchestrates two passes |
| One LLM call over full policy | Pass 1 (Scout) + Pass 2 (one call per section) |
| Returns after one call | Merges results from all section calls |
| Falls back to nothing on failure | Falls back to original single-pass if Scout fails |

New internal functions added:
- `_run_scout()` — makes the Pass 1 Scout call
- `_extract_from_section()` — makes one Pass 2 call for a single section
- `_run_single_pass()` — the original logic, kept as a fallback

The public interface (`run_extractor`) is **unchanged** — `main.py` does not need any modification.

### `prompts/extractor_prompt.py` — Extended

The original single-pass prompt (`EXTRACTOR_USER_TEMPLATE`, `build_extractor_prompt`) is kept intact and still used as the fallback.

A new section-level prompt was added:
- `SECTION_EXTRACTOR_USER_TEMPLATE` — instructs the model to quote complete paragraphs
- `build_section_extractor_prompt(section_name, section_text, clause_id_start)` — formats the prompt for one section, injecting the correct starting clause ID

### `prompts/scout_prompt.py` — New file

Contains the Pass 1 prompt:
- `SCOUT_SYSTEM` — tells the model its only job is to identify sections, not extract or assess
- `SCOUT_USER_TEMPLATE` — lists what types of content make a section relevant
- `build_scout_prompt(policy_text)` — formats the prompt

### `utils/section_splitter.py` — New file

Contains the Python section boundary logic:
- `split_sections(policy_text, section_names)` — uses `rapidfuzz.fuzz.partial_ratio` to match each Scout-returned section name to a line in the policy, then extracts full section text between consecutive matched lines
- Handles edge cases: no sections found → returns full policy as one section; duplicate line matches → deduplicates

---

## 5. What Is Better Now

| Aspect | Before | After |
|---|---|---|
| Paragraph quoting | Often single sentence | Full paragraph including safeguards |
| Clause cap | Hard limit of 15 | No cap — all sections fully processed |
| Coverage | May miss sections | All Scout-identified sections processed |
| C15 safeguards problem | Safeguards text dropped | Safeguards text included in quote |
| `coverage_complete` | Sometimes `false` | Always `true` for two-pass runs |

---

## 6. What Is Still a Limitation

- **Scout misses a section:** If Pass 1 fails to identify a relevant section, Pass 2 never sees it. The Scout prompt is written to be inclusive (err on the side of including sections), but it can still miss content in very unstructured policies.
- **Section splitter on poorly formatted policies:** The fuzzy matching requires at least some section headings to be present in the text. Policies with no headings fall back to single-pass.
- **More LLM calls:** Two-pass makes N+1 calls (1 Scout + N section calls) instead of 1. For a policy with 10 relevant sections, this is 11 calls. Each call is smaller and cheaper per token, but the total latency is higher.

---

## 7. Connection to Thesis

This change directly addresses two limitations documented in the thesis baseline:

1. **Misplaced or incomplete evidence** (thesis limitation 1): The old single-pass approach was vulnerable to the same problem the thesis identified in single-prompt GPT — the model cited real policy text but not the complete relevant content. Two-pass extraction forces complete paragraph capture.

2. **Extraction cap and coverage gaps**: The thesis baseline had no structured extraction step at all (single prompt, full output). The original agentic system improved on this but still had a 15-clause cap. Two-pass removes the cap entirely.

The two-pass architecture can be described in the thesis as: *"A section-aware extraction pipeline that separates section identification (Pass 1) from content extraction (Pass 2), enabling complete paragraph-level quoting without an arbitrary clause cap."*
