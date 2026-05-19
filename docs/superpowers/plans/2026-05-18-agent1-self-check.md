# Agent 1 Self-Check (Pass 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Pass 3 to Agent 1 that detects uncovered paragraphs in Scout-identified sections, judges each with Gemini Flash, re-extracts confirmed gaps with GPT-5.3, and reports everything in a new `self_check_report` key.

**Architecture:** After Pass 2 finishes extracting clauses per section, Python splits each section into paragraphs and fuzzy-matches them against extracted quotes. Uncovered paragraphs go to Gemini Flash for a yes/no gap judgment; confirmed gaps go to GPT-5.3 for re-extraction. Results are merged into the existing clause list and summarised in `self_check_report`.

**Tech Stack:** Python 3.11+, rapidfuzz, openai (OpenRouter client), existing `parse_and_repair` utility.

---

## File Map

| File | Action | What changes |
|---|---|---|
| `prompts/extractor_prompt.py` | Modify | Add `SELF_CHECK_JUDGE_SYSTEM`, `SELF_CHECK_JUDGE_TEMPLATE`, `build_gap_judge_prompt()` |
| `agents/extractor.py` | Modify | Add `_find_uncovered_paragraphs()`, `_judge_paragraph_gap()`, `_reextract_gap()`, `_self_check()`. Wire into `run_extractor()`. |

No other files change.

---

## Task 1: Add gap judge prompt to `prompts/extractor_prompt.py`

**Files:**
- Modify: `prompts/extractor_prompt.py`

- [ ] **Step 1: Append the judge system prompt and template**

Open `prompts/extractor_prompt.py` and add the following at the bottom of the file:

```python
# ---------------------------------------------------------------------------
# Self-check gap judgment prompt (used in Pass 3)
# ---------------------------------------------------------------------------

SELF_CHECK_JUDGE_SYSTEM = """\
You are a GDPR purpose limitation specialist. Your only job is to decide \
whether a single paragraph from a privacy policy contains content relevant \
to GDPR Article 5(1)(b) — purpose limitation — that was NOT already captured \
by a provided list of extracted clauses. Answer yes or no. Be strict: only \
flag genuine gaps, not paragraphs that are already covered."""

SELF_CHECK_JUDGE_TEMPLATE = """\
## Already extracted clauses from this section
The following clauses have already been extracted from this section:

{existing_clauses_json}

## Uncovered paragraph
The paragraph below was NOT matched to any of the above clauses:

\"\"\"{paragraph}\"\"\"

## Your task
Does this paragraph contain purpose limitation content relevant to \
GDPR Article 5(1)(b) that is NOT already captured in the extracted clauses above?

Purpose limitation content includes:
- Stated processing purposes
- Legal basis tied to a specific purpose
- Secondary or further use of already-collected data
- Third-party data sharing with stated purposes
- Research, analytics, profiling, or product development purposes
- Article 89 GDPR exceptions

Return ONLY valid JSON. No prose, no markdown.

{{
  "is_gap": true,
  "reason": "One sentence explaining why this paragraph contains uncaptured purpose limitation content."
}}

or

{{
  "is_gap": false,
  "reason": "One sentence explaining why this paragraph does not contain uncaptured purpose limitation content."
}}
"""


def build_gap_judge_prompt(
    paragraph: str,
    existing_clauses: list[dict],
) -> str:
    """Return the formatted user prompt for the gap judgment call (Pass 3)."""
    import json
    clauses_for_prompt = [
        {k: v for k, v in c.items()
         if k in ("clause_id", "quote", "relevance_type")}
        for c in existing_clauses
    ]
    return SELF_CHECK_JUDGE_TEMPLATE.format(
        existing_clauses_json=json.dumps(clauses_for_prompt, indent=2, ensure_ascii=False),
        paragraph=paragraph,
    )
```

- [ ] **Step 2: Verify the file is valid Python**

```bash
C:/Users/SAZGAR/AppData/Local/Programs/Python/Python313/python.exe -c "import prompts.extractor_prompt; print('OK')"
```

Expected output: `OK`

- [ ] **Step 3: Commit**

```bash
git add prompts/extractor_prompt.py
git commit -m "feat: add self-check gap judge prompt to extractor_prompt.py"
```

---

## Task 2: Add `_find_uncovered_paragraphs()` to `agents/extractor.py`

**Files:**
- Modify: `agents/extractor.py`

- [ ] **Step 1: Add the function**

Add the following function inside `agents/extractor.py` after the `_run_single_pass` function (at the bottom of the file, before the final newline):

```python
def _find_uncovered_paragraphs(
    sections: list[dict],
    all_clauses: list[dict],
) -> list[dict]:
    """
    For each section, split its text into paragraphs and check whether
    each paragraph is covered by at least one extracted clause quote.

    A paragraph is considered covered if its best fuzzy match score
    against any clause quote from the same section is >= 60.

    Args:
        sections: List of {"name": str, "text": str} dicts from the splitter.
        all_clauses: All clauses extracted in Pass 2.

    Returns:
        List of {"section_name": str, "paragraph": str,
                 "section_clauses": list[dict]} dicts — one per uncovered paragraph.
    """
    from rapidfuzz import fuzz

    uncovered = []

    for section in sections:
        section_name = section["name"]
        section_text = section["text"]

        # Clauses extracted from this specific section
        section_clauses = [
            c for c in all_clauses
            if c.get("section_reference") == section_name
        ]

        # Split section into paragraphs
        paragraphs = [
            p.strip()
            for p in section_text.split("\n\n")
            if p.strip() and len(p.strip()) > 30  # skip very short fragments
        ]

        for paragraph in paragraphs:
            if not section_clauses:
                # No clauses at all from this section — every paragraph is uncovered
                uncovered.append({
                    "section_name": section_name,
                    "paragraph": paragraph,
                    "section_clauses": [],
                })
                continue

            # Check best match against all clause quotes from this section
            best_score = max(
                fuzz.partial_ratio(paragraph.lower(), c.get("quote", "").lower())
                for c in section_clauses
            )

            if best_score < 60:
                uncovered.append({
                    "section_name": section_name,
                    "paragraph": paragraph,
                    "section_clauses": section_clauses,
                })

    return uncovered
```

- [ ] **Step 2: Verify the file is valid Python**

```bash
C:/Users/SAZGAR/AppData/Local/Programs/Python/Python313/python.exe -c "import agents.extractor; print('OK')"
```

Expected output: `OK`

- [ ] **Step 3: Commit**

```bash
git add agents/extractor.py
git commit -m "feat: add _find_uncovered_paragraphs to extractor"
```

---

## Task 3: Add `_judge_paragraph_gap()` to `agents/extractor.py`

**Files:**
- Modify: `agents/extractor.py`

- [ ] **Step 1: Add the import at the top of extractor.py**

The file already imports from `prompts.extractor_prompt`. Add `build_gap_judge_prompt` and `SELF_CHECK_JUDGE_SYSTEM` to the existing import:

```python
from prompts.extractor_prompt import (
    EXTRACTOR_SYSTEM,
    build_extractor_prompt,
    build_section_extractor_prompt,
    SELF_CHECK_JUDGE_SYSTEM,
    build_gap_judge_prompt,
)
```

- [ ] **Step 2: Add the judgment function**

Add this function at the bottom of `agents/extractor.py`:

```python
def _judge_paragraph_gap(
    client: OpenAI,
    paragraph: str,
    section_clauses: list[dict],
    model: str,
) -> dict:
    """
    Pass 3 Step 2: ask the model whether an uncovered paragraph contains
    purpose limitation content not already captured.

    Args:
        client: OpenRouter-configured OpenAI client.
        paragraph: The uncovered paragraph text.
        section_clauses: Already-extracted clauses from the same section.
        model: Model slug for gap judgment (Gemini Flash).

    Returns:
        {"is_gap": bool, "reason": str} — defaults to is_gap=False on failure.
    """
    try:
        user_prompt = build_gap_judge_prompt(
            paragraph=paragraph,
            existing_clauses=section_clauses,
        )
        response = client.chat.completions.create(
            model=model,
            max_tokens=256,
            messages=[
                {"role": "system", "content": SELF_CHECK_JUDGE_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
        )
        raw = response.choices[0].message.content or ""
        data = parse_and_repair(raw)
        if isinstance(data, dict) and "is_gap" in data:
            return {
                "is_gap": bool(data["is_gap"]),
                "reason": str(data.get("reason", "")),
            }
    except Exception as e:
        print(f"    [Self-Check] Warning: gap judgment failed ({e}). Treating as no gap.")
    return {"is_gap": False, "reason": "judgment call failed — treated as no gap"}
```

- [ ] **Step 3: Verify the file is valid Python**

```bash
C:/Users/SAZGAR/AppData/Local/Programs/Python/Python313/python.exe -c "import agents.extractor; print('OK')"
```

Expected output: `OK`

- [ ] **Step 4: Commit**

```bash
git add agents/extractor.py prompts/extractor_prompt.py
git commit -m "feat: add _judge_paragraph_gap to extractor"
```

---

## Task 4: Add `_reextract_gap()` to `agents/extractor.py`

**Files:**
- Modify: `agents/extractor.py`

- [ ] **Step 1: Add the re-extraction function**

Add this function at the bottom of `agents/extractor.py`:

```python
def _reextract_gap(
    client: OpenAI,
    paragraph: str,
    section_name: str,
    existing_clauses: list[dict],
    clause_id_start: int,
    model: str,
) -> list[dict]:
    """
    Pass 3 Step 3: re-extract purpose limitation clauses from a confirmed
    gap paragraph using GPT-5.3.

    Args:
        client: OpenRouter-configured OpenAI client.
        paragraph: The gap paragraph text to re-extract from.
        section_name: Name of the section this paragraph belongs to.
        existing_clauses: Already-extracted clauses from this section
                          (to avoid duplicate extraction).
        clause_id_start: Starting clause ID number for new clauses.
        model: Model slug for re-extraction (GPT-5.3).

    Returns:
        List of newly extracted clause dicts, or [] on failure.
    """
    import json

    # Build a targeted extraction prompt for just this paragraph,
    # telling the model what has already been extracted to avoid duplicates
    existing_summary = json.dumps(
        [{"clause_id": c.get("clause_id"), "quote": c.get("quote")}
         for c in existing_clauses],
        indent=2, ensure_ascii=False
    )

    user_prompt = (
        f"## Already extracted clauses from section '{section_name}'\n"
        f"Do NOT re-extract any of the following — they are already captured:\n"
        f"{existing_summary}\n\n"
        f"---\n\n"
        + build_section_extractor_prompt(
            section_name=section_name,
            section_text=paragraph,
            clause_id_start=clause_id_start,
        )
    )

    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=MAX_TOKENS["extractor"],
            messages=[
                {"role": "system", "content": EXTRACTOR_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
        )
        raw = response.choices[0].message.content or ""
        data = parse_and_repair(raw)
        clauses = data.get("extracted_clauses", [])
        if isinstance(clauses, list):
            return clauses
    except Exception as e:
        print(f"    [Self-Check] Warning: re-extraction failed for section "
              f"'{section_name}' ({e}).")
    return []
```

- [ ] **Step 2: Verify the file is valid Python**

```bash
C:/Users/SAZGAR/AppData/Local/Programs/Python/Python313/python.exe -c "import agents.extractor; print('OK')"
```

Expected output: `OK`

- [ ] **Step 3: Commit**

```bash
git add agents/extractor.py
git commit -m "feat: add _reextract_gap to extractor"
```

---

## Task 5: Add `_self_check()` orchestrator to `agents/extractor.py`

**Files:**
- Modify: `agents/extractor.py`

- [ ] **Step 1: Add the orchestrator function**

Add this function at the bottom of `agents/extractor.py`:

```python
def _self_check(
    client: OpenAI,
    sections: list[dict],
    all_clauses: list[dict],
    clause_counter: int,
    model: str,
    scout_model: str,
) -> tuple[list[dict], dict]:
    """
    Pass 3: self-check orchestrator.

    Finds uncovered paragraphs, judges each with Gemini Flash, re-extracts
    confirmed gaps with GPT-5.3, and builds the self_check_report.

    Args:
        client: OpenRouter-configured OpenAI client.
        sections: Section chunks from the splitter (name + text).
        all_clauses: All clauses produced by Pass 2.
        clause_counter: Next available clause ID number.
        model: Model slug for re-extraction (GPT-5.3).
        scout_model: Model slug for gap judgment (Gemini Flash).

    Returns:
        Tuple of (new_clauses, self_check_report).
        new_clauses: list of newly found clause dicts (may be empty).
        self_check_report: dict with full Pass 3 summary.
    """
    print("    [Self-Check] Pass 3: checking paragraph coverage...")

    uncovered = _find_uncovered_paragraphs(sections, all_clauses)
    print(f"    [Self-Check] {len(uncovered)} uncovered paragraph(s) found.")

    new_clauses: list[dict] = []
    gaps_found = 0
    gaps_filled = 0
    unresolved_gaps: list[dict] = []

    for item in uncovered:
        section_name = item["section_name"]
        paragraph = item["paragraph"]
        section_clauses = item["section_clauses"]

        # Step 2: judge whether this is a real gap
        judgment = _judge_paragraph_gap(
            client=client,
            paragraph=paragraph,
            section_clauses=section_clauses,
            model=scout_model,
        )

        if not judgment["is_gap"]:
            continue

        gaps_found += 1
        print(f"    [Self-Check] Gap confirmed in '{section_name}': {judgment['reason'][:60]}")

        # Step 3: re-extract from the gap paragraph
        gap_clauses = _reextract_gap(
            client=client,
            paragraph=paragraph,
            section_name=section_name,
            existing_clauses=section_clauses + new_clauses,
            clause_id_start=clause_counter,
            model=model,
        )

        if gap_clauses:
            new_clauses.extend(gap_clauses)
            clause_counter += len(gap_clauses)
            gaps_filled += 1
            print(f"    [Self-Check] Gap filled: {len(gap_clauses)} new clause(s) added.")
        else:
            unresolved_gaps.append({
                "section_name": section_name,
                "paragraph": paragraph,
                "reason": (
                    "Re-extraction found no extractable purpose limitation "
                    "content in this paragraph."
                ),
            })
            print(f"    [Self-Check] Gap unresolved in '{section_name}'.")

    # Build human_review_note
    if unresolved_gaps:
        sections_with_gaps = list({g["section_name"] for g in unresolved_gaps})
        human_review_note = (
            f"{len(unresolved_gaps)} paragraph gap(s) could not be resolved after "
            f"re-extraction. Human reviewer should manually check: "
            f"{', '.join(sections_with_gaps)}."
        )
    else:
        human_review_note = None

    self_check_report = {
        "paragraphs_checked": len(uncovered),
        "gaps_found": gaps_found,
        "gaps_filled": gaps_filled,
        "gaps_unresolved": len(unresolved_gaps),
        "new_clauses_added": [c.get("clause_id") for c in new_clauses],
        "unresolved_gaps": unresolved_gaps,
        "human_review_note": human_review_note,
    }

    return new_clauses, self_check_report
```

- [ ] **Step 2: Verify the file is valid Python**

```bash
C:/Users/SAZGAR/AppData/Local/Programs/Python/Python313/python.exe -c "import agents.extractor; print('OK')"
```

Expected output: `OK`

- [ ] **Step 3: Commit**

```bash
git add agents/extractor.py
git commit -m "feat: add _self_check orchestrator to extractor"
```

---

## Task 6: Wire Pass 3 into `run_extractor()`

**Files:**
- Modify: `agents/extractor.py`

- [ ] **Step 1: Replace the Pass 2 result block in `run_extractor()`**

Find this block in `run_extractor()`:

```python
    notes = (
        f"Two-pass extraction: {len(sections)} section(s) processed "
        f"({', '.join(s['name'] for s in sections)})."
    )

    result = {
        "policy_name": policy_name,
        "extracted_clauses": all_clauses,
        "extraction_notes": notes,
        "coverage_complete": True,
        "sections_processed": [s["name"] for s in sections],
    }

    errors = validate_extractor_output(result)
    if errors:
        raise ValueError(
            "Extractor output failed validation:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    return result
```

Replace it with:

```python
    # ------------------------------------------------------------------
    # Pass 3: Self-check — find and fill paragraph coverage gaps
    # ------------------------------------------------------------------
    new_clauses, self_check_report = _self_check(
        client=client,
        sections=sections,
        all_clauses=all_clauses,
        clause_counter=clause_counter,
        model=_model,
        scout_model=_scout_model,
    )
    all_clauses.extend(new_clauses)

    notes = (
        f"Two-pass extraction with self-check: {len(sections)} section(s) processed "
        f"({', '.join(s['name'] for s in sections)}). "
        f"Self-check added {len(new_clauses)} clause(s)."
    )

    result = {
        "policy_name": policy_name,
        "extracted_clauses": all_clauses,
        "extraction_notes": notes,
        "coverage_complete": True,
        "sections_processed": [s["name"] for s in sections],
        "self_check_report": self_check_report,
    }

    errors = validate_extractor_output(result)
    if errors:
        raise ValueError(
            "Extractor output failed validation:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    return result
```

- [ ] **Step 2: Update the docstring of `run_extractor()`**

Find the docstring line:
```python
    Pass 1 identifies relevant sections; Pass 2 extracts complete
    paragraphs from each section. Falls back to single-pass if the
    Scout returns no usable sections.
```

Replace with:
```python
    Pass 1 identifies relevant sections; Pass 2 extracts complete
    paragraphs from each section; Pass 3 self-checks for uncovered
    paragraphs and fills gaps. Falls back to single-pass if the
    Scout returns no usable sections.
```

- [ ] **Step 3: Verify the file is valid Python**

```bash
C:/Users/SAZGAR/AppData/Local/Programs/Python/Python313/python.exe -c "import agents.extractor; print('OK')"
```

Expected output: `OK`

- [ ] **Step 4: Run the pipeline to confirm end-to-end**

```bash
C:/Users/SAZGAR/AppData/Local/Programs/Python/Python313/python.exe main.py --policy data/policies/policy_long.txt 2>&1
```

Expected: pipeline runs, terminal shows `[Self-Check]` lines, output JSON contains `self_check_report` key.

- [ ] **Step 5: Commit**

```bash
git add agents/extractor.py
git commit -m "feat: wire Pass 3 self-check into run_extractor"
```
