# Label Panel & Anchoring Measurement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-clause Label Panel that records compliance labels from the Evaluator, both Reflectors (anchored), and two new same-model Blind Labelers (unanchored), then measures and reports the anchoring shift per model — in both JSON and Markdown output, with an on/off toggle.

**Architecture:** Two new Blind Labeler agents reuse the Reflectors' models but never see the Evaluator's output, giving a within-model blind-vs-anchored comparison. A pure-Python builder assembles all labels per clause, flags disagreements, and computes the anchoring shift. The Evaluator's label stays official; disputes are non-destructive (surfaced to human review + confidence). A shared rubric constant keeps wording identical across labelers, and temperature 0 removes sampling noise.

**Tech Stack:** Python 3.x, `openai` SDK (OpenRouter base URL), existing `parse_and_repair` / `legal_tools` utilities. No test framework in this repo — pure-Python code is tested with standalone `assert` scripts run via `python`; LLM-calling code is verified with import checks and a final end-to-end run. The user runs Python as `python` on PATH.

**Spec:** `docs/superpowers/specs/2026-05-21-label-panel-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `prompts/rubric.py` | Create | Single source of truth for the GDPR rubric text (`RUBRIC_BLOCK`) |
| `prompts/blind_labeler_prompt.py` | Create | System prompt + user-prompt builder for blind labeling |
| `agents/blind_labeler.py` | Create | `run_blind_labeler()` — tool loop, batching, temperature 0; returns labels |
| `utils/label_panel.py` | Create | `build_label_panel()` + `annotate_finalizer_with_disputes()` — pure Python |
| `tests/test_label_panel.py` | Create | Standalone assert tests for the pure-Python builder |
| `prompts/evaluator_prompt.py` | Modify | Use shared `RUBRIC_BLOCK` instead of inlined rubric (no wording change) |
| `prompts/reflector_prompt.py` | Modify | Add `clause_labels` output field + instruction |
| `utils/schema_validator.py` | Modify | Tolerate `clause_labels` (reflector) and `labels` (blind labeler) |
| `config.py` | Modify | Add `ENABLE_BLIND_LABELER`, `blind_a`/`blind_b` model slots, `LABELER_TEMPERATURE` |
| `agents/evaluator.py` | Modify | Pass `temperature=LABELER_TEMPERATURE` on its calls |
| `agents/reflector.py` | Modify | Pass `temperature=LABELER_TEMPERATURE` on its call |
| `main.py` | Modify | `--no-blind-labeler` flag; run blind labelers; build panel; annotate finalizer; add `label_panel` to result |
| `utils/report_generator.py` | Modify | Render Label Panel table + anchoring summary in Markdown |

---

## Task 1: Create shared rubric module and refactor evaluator to use it

**Files:**
- Create: `prompts/rubric.py`
- Modify: `prompts/evaluator_prompt.py`

- [ ] **Step 1: Create `prompts/rubric.py`**

Open `prompts/evaluator_prompt.py`. Locate the contiguous block inside `EVALUATOR_USER_TEMPLATE` that starts with the line `## Two-stage rubric` and ends with the last line of the `## Criterion answer values` section (the line `- partial = criterion is partly met but not fully`). This block contains the Stage 1 table, Stage 2 table, Article 89 branch, label decision rules, and criterion answer values.

Create `prompts/rubric.py` and paste that exact block verbatim as a string constant:

```python
"""
Shared GDPR Article 5(1)(b) purpose-limitation rubric.

Single source of truth imported by both the Evaluator and the Blind Labeler so
their judgments use identical wording. Changing the rubric here changes it for
every labeler at once — this is intentional (removes prompt-wording as a
confound when comparing labels across models).
"""

RUBRIC_BLOCK = """\
## Two-stage rubric

### Stage 1 — Purpose Specification
Apply to every clause. Assess whether the stated purpose is:

| Criterion | Key question | Compliant example | Non-compliant example |
|---|---|---|---|
| specific | Does the clause name a concrete processing activity? | "to generate personalised health assessments via the Ada app" | "to improve our products and services" |
| explicit | Is the purpose stated in plain language a data subject can understand? | "to send you appointment reminders by email" | "for operational purposes" |
| legitimate | Is the purpose legally permissible under EU law? | Any clearly lawful purpose | Purposes contrary to law or public policy |
| determined_at_collection | Was (or could) the purpose be known at or before data collection? | Purpose tied to the service the user signed up for | Post-hoc purpose defined after data is collected |

### Stage 2 — Compatibility Assessment
Apply only if the clause describes further or secondary use of already-collected data.
Assess whether the further use is compatible with the original purpose by checking:

| Criterion | Key question |
|---|---|
| purpose_link | Is there a meaningful connection between the original and secondary purpose? |
| context_consistent | Would a data subject reasonably expect this further use given the collection context? |
| data_nature_considered | Does the clause acknowledge the nature of the data (especially health/special category)? |
| impact_assessed | Does the clause address the potential impact on data subjects? |
| safeguards_present | Are technical/organisational safeguards stated (pseudonymisation, access controls, consent)? |

### Article 89 Exception Branch
Apply only if the clause explicitly invokes research, archiving, or statistical purposes.
Check:
- Is the Article 89 exception explicitly claimed (not merely implied)?
- Are appropriate safeguards stated (pseudonymisation, anonymisation, functional separation, access controls)?
- Is the purpose genuinely archiving/scientific/statistical (not a disguised commercial use)?

---

## Label decision rules

### Per-clause label
- **Compliant**: All applicable Stage 1 criteria are met (yes or partial-but-sufficient); \
Stage 2 criteria met if applicable; or Article 89 exception properly invoked with safeguards stated.
- **Partially Compliant**: At least one Stage 1 criterion is met but at least one is missing \
(e.g. specific but not explicit); Stage 2 partially addressed; or Article 89 invoked \
without full safeguard specification.
- **Non-Compliant**: No specific purpose stated; vague catch-all language only \
(e.g. "to improve services", "for business purposes"); further processing incompatible \
with original purpose without justification; or Article 89 invoked without any safeguards.

**IMPORTANT — no other labels are permitted.** You must use exactly one of: \
"Compliant", "Partially Compliant", or "Non-Compliant". \
Do NOT use "Not Applicable", "N/A", or any other value. \
Every clause that was extracted and verified is relevant to purpose limitation; \
if a clause contains no purpose limitation language at all, label it "Non-Compliant".

### Overall policy label (derived from clause labels)
- All clauses Compliant → **Compliant**
- Mix of Compliant + Partially Compliant (no Non-Compliant) → **Partially Compliant**
- Any Non-Compliant clause → **Non-Compliant**
  (Exception: if the Non-Compliant clause is fully covered by a proper Article 89 exception, \
  it does not force a Non-Compliant overall label.)

---

## Criterion answer values
Use exactly: "yes", "no", or "partial"
- yes = criterion is clearly met
- no = criterion is clearly not met
- partial = criterion is partly met but not fully"""
```

> If the wording in `evaluator_prompt.py` differs from the above (e.g. small edits since this plan was written), the file's actual text wins — copy the real block verbatim. The anchors are the headings `## Two-stage rubric` and `## Criterion answer values`.

- [ ] **Step 2: Refactor `evaluator_prompt.py` to insert the shared block**

In `prompts/evaluator_prompt.py`, add the import near the top (after the module docstring):

```python
from prompts.rubric import RUBRIC_BLOCK
```

Replace the verbatim rubric block inside `EVALUATOR_USER_TEMPLATE` (the same `## Two-stage rubric` … `- partial = criterion is partly met but not fully` span) with the single placeholder line:

```
{rubric_block}
```

Then, in `build_evaluator_prompt()`, add `rubric_block=RUBRIC_BLOCK` to the existing `.format(...)` call. For example it becomes:

```python
    return EVALUATOR_USER_TEMPLATE.format(
        rubric_block=RUBRIC_BLOCK,
        clauses_json=json.dumps(clauses_for_prompt, indent=2, ensure_ascii=False),
    )
```

> Note: the `{rubric_block}` placeholder must be the only new brace-expression added. The rubric text itself contains no `{`/`}`, so it is safe inside `.format()`.

- [ ] **Step 3: Write a verification test for no content loss**

Create `tests/test_rubric_extraction.py`:

```python
"""Verify the evaluator prompt still contains all rubric content after extraction."""
from prompts.evaluator_prompt import build_evaluator_prompt

CLAUSES = [{"clause_id": "C1", "quote": "x", "section_reference": "s", "relevance_type": "purpose_statement"}]
rendered = build_evaluator_prompt(CLAUSES)

required_phrases = [
    "## Two-stage rubric",
    "Stage 1 — Purpose Specification",
    "determined_at_collection",
    "Stage 2 — Compatibility Assessment",
    "Article 89 Exception Branch",
    "no other labels are permitted",
    "Criterion answer values",
    '"yes", "no", or "partial"',
    "{",  # the JSON schema braces must still be present below the rubric
]
for phrase in required_phrases:
    assert phrase in rendered, f"MISSING after extraction: {phrase!r}"

print("OK")
```

- [ ] **Step 4: Run the verification test**

Run: `python tests/test_rubric_extraction.py`
Expected output: `OK`

- [ ] **Step 5: Confirm modules import**

Run: `python -c "import prompts.rubric, prompts.evaluator_prompt; print('OK')"`
Expected output: `OK`

- [ ] **Step 6: Commit**

```bash
git add prompts/rubric.py prompts/evaluator_prompt.py tests/test_rubric_extraction.py
git commit -m "refactor: extract shared rubric block into prompts/rubric.py"
```

---

## Task 2: Add config entries for blind labeler and temperature

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Add the toggle, model slots, and temperature constant**

In `config.py`, add `blind_a` and `blind_b` keys to `DEFAULT_AGENT_MODELS` (mirroring the two reflector models so each blind labeler shares its reflector's model):

```python
    "blind_a":     "openai/gpt-4o-mini",                         # mirrors reflector_a — blind label for anchoring delta
    "blind_b":     "google/gemini-2.0-flash-001",                # mirrors reflector_b — blind label for anchoring delta
```

> Set each blind slot to the **same slug** as its paired reflector at all times — that pairing is what makes the anchoring measurement within-model.

After the `MAX_TOKENS` dict, add:

```python
# Feature toggle: Blind Labeler tier (Pass for anchoring measurement).
# When False, the two blind-labeler calls are skipped and the label panel
# still records evaluator + reflector labels (no blind labels, no anchoring delta).
ENABLE_BLIND_LABELER = True

# Temperature for all label-producing calls (evaluator, reflectors, blind labelers).
# Fixed at 0 so a blind-vs-anchored label difference reflects the model, not sampling noise.
LABELER_TEMPERATURE = 0
```

Also add a `MAX_TOKENS` entry for the blind labeler (same budget as the evaluator, since it produces labels for up to a batch of clauses):

```python
    "blind_labeler": 16000,  # same budget style as evaluator — labels for a full batch
```

- [ ] **Step 2: Confirm config imports and values**

Run:
```bash
python -c "import config; print(config.ENABLE_BLIND_LABELER, config.LABELER_TEMPERATURE, config.DEFAULT_AGENT_MODELS['blind_a'], config.DEFAULT_AGENT_MODELS['blind_b'], config.MAX_TOKENS['blind_labeler'])"
```
Expected output: `True 0 openai/gpt-4o-mini google/gemini-2.0-flash-001 16000`

- [ ] **Step 3: Commit**

```bash
git add config.py
git commit -m "feat: add blind-labeler config (toggle, model slots, temperature)"
```

---

## Task 3: Create the blind labeler prompt

**Files:**
- Create: `prompts/blind_labeler_prompt.py`

- [ ] **Step 1: Create the prompt module**

Create `prompts/blind_labeler_prompt.py`:

```python
"""
Prompt for the Blind Labeler.

The Blind Labeler assigns a purpose-limitation compliance label to each clause
using the SAME rubric as the Evaluator, but it never sees the Evaluator's output.
This produces an unanchored ("blind") label for the anchoring measurement.

It has access to the same legal-reference tool as the Evaluator so that tool
access is not a confound between labelers.
"""

from prompts.rubric import RUBRIC_BLOCK

BLIND_LABELER_SYSTEM = """\
You are a senior GDPR legal analyst specialising in Article 5(1)(b) — the purpose \
limitation principle. You assign a compliance label to each clause using rigorous, \
evidence-based legal reasoning grounded in the exact clause text provided. You do not \
make assumptions about what the policy might say elsewhere.

You have access to a legal reference tool. Use primary sources (GDPR articles and \
recitals) first; use secondary sources only if primary sources are insufficient. \
Do not call the same reference twice.

You are labeling independently. No other analyst's assessment is provided to you, \
and you must form your own judgment solely from the clause text and the rubric."""

BLIND_LABELER_USER_TEMPLATE = """\
## Your task
Assign a purpose-limitation compliance label to each clause below, using the rubric.

Before labeling, retrieve the legal sources you need using the get_legal_reference \
tool. At minimum, retrieve article_5_1b.

---

{rubric_block}

---

## Clauses to label
{clauses_json}

---

## Output format
Return ONLY valid JSON matching this exact schema. No prose, no markdown, no explanation.

{{
  "labels": [
    {{ "clause_id": "C1", "label": "Compliant|Partially Compliant|Non-Compliant" }}
  ]
}}

Include exactly one entry per clause provided. Use only the three permitted label values.
"""


def build_blind_labeler_prompt(verified_clauses: list[dict]) -> str:
    """Return the formatted user prompt for the Blind Labeler."""
    import json
    clauses_for_prompt = [
        {k: v for k, v in c.items()
         if k in ("clause_id", "quote", "section_reference", "relevance_type")}
        for c in verified_clauses
    ]
    return BLIND_LABELER_USER_TEMPLATE.format(
        rubric_block=RUBRIC_BLOCK,
        clauses_json=json.dumps(clauses_for_prompt, indent=2, ensure_ascii=False),
    )
```

> The clause field selection (`clause_id`, `quote`, `section_reference`, `relevance_type`) is identical to `build_evaluator_prompt()` — same input format, a deliberate confound control.

- [ ] **Step 2: Confirm import and rendering**

Run:
```bash
python -c "from prompts.blind_labeler_prompt import build_blind_labeler_prompt; p = build_blind_labeler_prompt([{'clause_id':'C1','quote':'we process data to deliver the service','section_reference':'1','relevance_type':'purpose_statement'}]); print('Two-stage rubric' in p and 'C1' in p)"
```
Expected output: `True`

- [ ] **Step 3: Commit**

```bash
git add prompts/blind_labeler_prompt.py
git commit -m "feat: add blind labeler prompt"
```

---

## Task 4: Create the blind labeler agent

**Files:**
- Create: `agents/blind_labeler.py`

- [ ] **Step 1: Create the agent module**

Create `agents/blind_labeler.py`. It mirrors the Evaluator's tool-calling loop and batching, but produces only labels, runs at temperature 0, and never receives evaluator output:

```python
"""
Blind Labeler agent.

Assigns a purpose-limitation compliance label to each verified clause using the
same rubric and the same legal-reference tool as the Evaluator — but without ever
seeing the Evaluator's output. Its labels are the "blind" (unanchored) condition
in the anchoring measurement.

Runs at temperature 0 and batches large clause sets exactly like the Evaluator,
so the only difference from the Evaluator is the absence of evaluator output.
"""

import json

from openai import OpenAI

from config import MAX_TOKENS, LABELER_TEMPERATURE
from prompts.blind_labeler_prompt import BLIND_LABELER_SYSTEM, build_blind_labeler_prompt
from utils.schema_validator import parse_and_repair
from utils.legal_tools import LEGAL_TOOLS, execute_tool_call

MAX_TOOL_ITERATIONS = 6
BLIND_LABELER_BATCH_SIZE = 15  # match the evaluator's batch size (confound control)


def run_blind_labeler(
    client: OpenAI,
    verified_clauses: list[dict],
    model: str,
) -> dict:
    """
    Assign a blind compliance label to each verified clause.

    Args:
        client: OpenRouter-configured OpenAI client.
        verified_clauses: Clauses that passed the string-match verifier.
        model: OpenRouter model slug — MUST match the paired reflector's model.

    Returns:
        {"labels": [{"clause_id": str, "label": str}, ...]} — one entry per clause.
        On total failure, returns {"labels": []}; callers treat missing labels as null.
    """
    if not verified_clauses:
        return {"labels": []}

    if len(verified_clauses) > BLIND_LABELER_BATCH_SIZE:
        return _run_batched(client, verified_clauses, model)

    user_prompt = build_blind_labeler_prompt(verified_clauses)
    messages = [
        {"role": "system", "content": BLIND_LABELER_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]

    raw = ""
    for _ in range(MAX_TOOL_ITERATIONS):
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=MAX_TOKENS["blind_labeler"],
                temperature=LABELER_TEMPERATURE,
                messages=messages,
                tools=LEGAL_TOOLS,
                tool_choice="auto",
            )
        except Exception as e:
            print(f"    [Blind Labeler] Warning: call failed ({e}). Returning no labels.")
            return {"labels": []}

        message = response.choices[0].message

        if not message.tool_calls:
            raw = message.content or ""
            break

        assistant_turn = {"role": "assistant", "content": message.content or ""}
        assistant_turn["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in message.tool_calls
        ]
        messages.append(assistant_turn)

        for tc in message.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}
            ref_id = args.get("reference_id", "")
            result_text = execute_tool_call(tc.function.name, args)
            print(f"    [Blind Labeler] get_legal_reference({ref_id!r})")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_text})
    else:
        # Tool cap reached — ask for the final answer without tools
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=MAX_TOKENS["blind_labeler"],
                temperature=LABELER_TEMPERATURE,
                messages=messages,
            )
            raw = response.choices[0].message.content or ""
        except Exception as e:
            print(f"    [Blind Labeler] Warning: final call failed ({e}). Returning no labels.")
            return {"labels": []}

    try:
        data = parse_and_repair(raw)
    except Exception as e:
        print(f"    [Blind Labeler] Warning: could not parse output ({e}). Returning no labels.")
        return {"labels": []}

    labels = data.get("labels", []) if isinstance(data, dict) else []
    if not isinstance(labels, list):
        labels = []
    # Keep only well-formed entries
    clean = [
        {"clause_id": str(x.get("clause_id")), "label": str(x.get("label"))}
        for x in labels
        if isinstance(x, dict) and x.get("clause_id") and x.get("label")
    ]
    return {"labels": clean}


def _run_batched(client: OpenAI, verified_clauses: list[dict], model: str) -> dict:
    """Split into batches of BLIND_LABELER_BATCH_SIZE and merge label lists."""
    total = len(verified_clauses)
    batches = [
        verified_clauses[i:i + BLIND_LABELER_BATCH_SIZE]
        for i in range(0, total, BLIND_LABELER_BATCH_SIZE)
    ]
    print(f"  [Blind Labeler] {total} clauses -> {len(batches)} batch(es).")

    all_labels: list[dict] = []
    for idx, batch in enumerate(batches, start=1):
        print(f"    [Blind Labeler] Batch {idx}/{len(batches)} ({len(batch)} clauses)")
        result = run_blind_labeler(client, batch, model)
        all_labels.extend(result.get("labels", []))
    return {"labels": all_labels}
```

- [ ] **Step 2: Confirm the module imports**

Run: `python -c "import agents.blind_labeler; print('OK')"`
Expected output: `OK`

- [ ] **Step 3: Commit**

```bash
git add agents/blind_labeler.py
git commit -m "feat: add blind labeler agent"
```

---

## Task 5: Apply temperature 0 to evaluator and reflector calls

**Files:**
- Modify: `agents/evaluator.py`
- Modify: `agents/reflector.py`

- [ ] **Step 1: Import the temperature constant in the evaluator**

In `agents/evaluator.py`, change the config import line:

```python
from config import MAX_TOKENS
```
to:
```python
from config import MAX_TOKENS, LABELER_TEMPERATURE
```

- [ ] **Step 2: Add `temperature` to all three evaluator `create()` calls**

In `agents/evaluator.py` there are three `client.chat.completions.create(` calls (the tool loop call, the post-cap final call, and none in the batched function — it recurses into `run_evaluator`). Add `temperature=LABELER_TEMPERATURE,` to each call, immediately after the `max_tokens=MAX_TOKENS["evaluator"],` line. Both calls become, for example:

```python
        response = client.chat.completions.create(
            model=model,
            max_tokens=MAX_TOKENS["evaluator"],
            temperature=LABELER_TEMPERATURE,
            messages=messages,
            tools=LEGAL_TOOLS,
            tool_choice="auto",
        )
```
and the post-cap one:
```python
        response = client.chat.completions.create(
            model=model,
            max_tokens=MAX_TOKENS["evaluator"],
            temperature=LABELER_TEMPERATURE,
            messages=messages,
        )
```

- [ ] **Step 3: Import and apply temperature in the reflector**

In `agents/reflector.py`, change:
```python
from config import MAX_TOKENS
```
to:
```python
from config import MAX_TOKENS, LABELER_TEMPERATURE
```

Add `temperature=LABELER_TEMPERATURE,` to the single `create()` call, after `max_tokens=MAX_TOKENS["reflector"],`:

```python
    response = client.chat.completions.create(
        model=model,
        max_tokens=MAX_TOKENS["reflector"],
        temperature=LABELER_TEMPERATURE,
        messages=[
            {"role": "system", "content": REFLECTOR_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
    )
```

- [ ] **Step 4: Confirm both modules import**

Run: `python -c "import agents.evaluator, agents.reflector; print('OK')"`
Expected output: `OK`

- [ ] **Step 5: Commit**

```bash
git add agents/evaluator.py agents/reflector.py
git commit -m "feat: pin temperature 0 on evaluator and reflector label calls"
```

---

## Task 6: Add anchored `clause_labels` to the reflector

**Files:**
- Modify: `prompts/reflector_prompt.py`
- Modify: `utils/schema_validator.py`

- [ ] **Step 1: Add the instruction and schema field to the reflector prompt**

In `prompts/reflector_prompt.py`, inside `REFLECTOR_USER_TEMPLATE`, find the output-format JSON schema block (the one with `"review_status"`, `"errors"`, `"reflector_notes"`). Add a `clause_labels` array to that schema so it becomes:

```
{{
  "review_status": "clean|errors_found",
  "errors": [
    {{
      "error_type": "phantom_clause|unjustified_label|inconsistent_assessment|missing_article89_check|other",
      "responsible_agent": "1|2",
      "clause_id": "<clause_id or null if not clause-specific>",
      "description": "One precise sentence describing the problem."
    }}
  ],
  "clause_labels": [
    {{ "clause_id": "C1", "label": "Compliant|Partially Compliant|Non-Compliant" }}
  ],
  "reflector_notes": "Overall observation about output quality in 1-2 sentences, or null."
}}
```

Immediately above the `## Output format` heading, add a new instruction section:

```
---

## Your own verdict label (required)
In addition to flagging errors, independently state the compliance label YOU would
assign to each verified clause, based on the clause text and your own judgment.
Populate "clause_labels" with exactly one entry per verified clause, using only
"Compliant", "Partially Compliant", or "Non-Compliant". This is your verdict — it may
agree or disagree with the Evaluator's label.
```

- [ ] **Step 2: Make the schema validator tolerant of `clause_labels`**

In `utils/schema_validator.py`, locate `validate_reflector_output`. It currently only requires `review_status`. Add a lenient check that, **if** `clause_labels` is present, it must be a list (absence is allowed so older outputs/retries don't break):

```python
def validate_reflector_output(data: dict) -> list[str]:
    """Validate the Reflector (Agent 3) output structure."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["Root must be a JSON object."]
    if "review_status" not in data:
        errors.append("Missing required field: review_status")
    elif data["review_status"] not in {"clean", "errors_found", "errors_unresolved"}:
        errors.append(f"Invalid review_status: '{data['review_status']}'.")
    if "clause_labels" in data and not isinstance(data["clause_labels"], list):
        errors.append("clause_labels must be a list when present.")
    return errors
```

- [ ] **Step 3: Confirm modules import**

Run: `python -c "import prompts.reflector_prompt, utils.schema_validator; print('OK')"`
Expected output: `OK`

- [ ] **Step 4: Commit**

```bash
git add prompts/reflector_prompt.py utils/schema_validator.py
git commit -m "feat: reflector emits anchored clause_labels"
```

---

## Task 7: Create the label panel builder (pure Python, TDD)

**Files:**
- Create: `utils/label_panel.py`
- Create: `tests/test_label_panel.py`

- [ ] **Step 1: Write the failing tests first**

Create `tests/test_label_panel.py`:

```python
"""Standalone assert tests for the pure-Python label panel builder."""
from utils.label_panel import build_label_panel, annotate_finalizer_with_disputes


def _labels(items):
    return [{"clause_id": cid, "label": lab} for cid, lab in items]


def test_agreement_not_disputed():
    evaluator = {"evaluations": [{"clause_id": "C1", "clause_label": "Compliant"}]}
    refa = {"clause_labels": _labels([("C1", "Compliant")])}
    refb = {"clause_labels": _labels([("C1", "Compliant")])}
    blinda = {"labels": _labels([("C1", "Compliant")])}
    blindb = {"labels": _labels([("C1", "Compliant")])}
    models = {"evaluator": "E", "reflector_a": "Ra", "reflector_b": "Rb",
              "blind_a": "Ra", "blind_b": "Rb"}
    panel = build_label_panel(evaluator, refa, refb, blinda, blindb, models, blind_enabled=True)
    row = panel["per_clause"][0]
    assert row["disputed"] is False
    assert row["evaluator"] == {"label": "Compliant", "model": "E"}
    assert panel["disputed_count"] == 0


def test_single_dissent_is_disputed():
    evaluator = {"evaluations": [{"clause_id": "C1", "clause_label": "Compliant"}]}
    refa = {"clause_labels": _labels([("C1", "Non-Compliant")])}
    refb = {"clause_labels": _labels([("C1", "Compliant")])}
    blinda = {"labels": _labels([("C1", "Compliant")])}
    blindb = {"labels": _labels([("C1", "Compliant")])}
    models = {"evaluator": "E", "reflector_a": "Ra", "reflector_b": "Rb",
              "blind_a": "Ra", "blind_b": "Rb"}
    panel = build_label_panel(evaluator, refa, refb, blinda, blindb, models, blind_enabled=True)
    assert panel["per_clause"][0]["disputed"] is True
    assert panel["disputed_count"] == 1


def test_anchoring_shift_detected():
    # reflector_a (anchored) differs from blind_a (blind) for the same model -> changed
    evaluator = {"evaluations": [{"clause_id": "C1", "clause_label": "Compliant"}]}
    refa = {"clause_labels": _labels([("C1", "Compliant")])}       # anchored: agrees w/ evaluator
    refb = {"clause_labels": _labels([("C1", "Compliant")])}
    blinda = {"labels": _labels([("C1", "Non-Compliant")])}        # blind: disagrees
    blindb = {"labels": _labels([("C1", "Compliant")])}
    models = {"evaluator": "E", "reflector_a": "Ra", "reflector_b": "Rb",
              "blind_a": "Ra", "blind_b": "Rb"}
    panel = build_label_panel(evaluator, refa, refb, blinda, blindb, models, blind_enabled=True)
    row = panel["per_clause"][0]
    assert row["anchoring_shift"]["reflector_a_vs_blind_a"] == "changed"
    assert row["anchoring_shift"]["reflector_b_vs_blind_b"] == "no_change"
    summary = panel["anchoring_summary"]["reflector_a"]
    assert summary["clauses_changed"] == 1
    assert summary["total"] == 1
    assert summary["shift_rate"] == 1.0


def test_blind_disabled_skips_blind_columns():
    evaluator = {"evaluations": [{"clause_id": "C1", "clause_label": "Compliant"}]}
    refa = {"clause_labels": _labels([("C1", "Non-Compliant")])}
    refb = {"clause_labels": _labels([("C1", "Compliant")])}
    models = {"evaluator": "E", "reflector_a": "Ra", "reflector_b": "Rb",
              "blind_a": "Ra", "blind_b": "Rb"}
    panel = build_label_panel(evaluator, refa, refb, None, None, models, blind_enabled=False)
    row = panel["per_clause"][0]
    assert row["blind_a"] is None
    assert row["blind_b"] is None
    assert row["anchoring_shift"] == "not measured (blind labeler disabled)"
    assert panel["blind_labeler_enabled"] is False
    # disputed still computed from evaluator + reflectors
    assert row["disputed"] is True


def test_missing_label_is_null_not_dispute_driver():
    # reflector_b has no label for C1 -> recorded null, not counted as a dissent
    evaluator = {"evaluations": [{"clause_id": "C1", "clause_label": "Compliant"}]}
    refa = {"clause_labels": _labels([("C1", "Compliant")])}
    refb = {"clause_labels": []}  # missing C1
    blinda = {"labels": _labels([("C1", "Compliant")])}
    blindb = {"labels": _labels([("C1", "Compliant")])}
    models = {"evaluator": "E", "reflector_a": "Ra", "reflector_b": "Rb",
              "blind_a": "Ra", "blind_b": "Rb"}
    panel = build_label_panel(evaluator, refa, refb, blinda, blindb, models, blind_enabled=True)
    row = panel["per_clause"][0]
    assert row["reflector_b"] is None
    assert row["disputed"] is False  # all PRESENT labels agree


def test_annotate_finalizer_with_disputes():
    finalizer = {"confidence": "high", "unresolved_flags": []}
    panel = {"per_clause": [{"clause_id": "C1", "disputed": True}], "disputed_count": 1}
    annotate_finalizer_with_disputes(finalizer, panel)
    assert finalizer["confidence"] == "low"
    assert any("C1" in f for f in finalizer["unresolved_flags"])


if __name__ == "__main__":
    test_agreement_not_disputed()
    test_single_dissent_is_disputed()
    test_anchoring_shift_detected()
    test_blind_disabled_skips_blind_columns()
    test_missing_label_is_null_not_dispute_driver()
    test_annotate_finalizer_with_disputes()
    print("OK")
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `python tests/test_label_panel.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'utils.label_panel'` (the module does not exist yet).

- [ ] **Step 3: Implement `utils/label_panel.py`**

Create `utils/label_panel.py`:

```python
"""
Label Panel builder (pure Python, no LLM).

Assembles, per clause, the compliance labels from the Evaluator, both Reflectors
(anchored), and both Blind Labelers (unanchored). Flags disagreement and computes
the per-model anchoring shift (blind vs anchored). Also annotates the Finalizer
output with disputed clauses (non-destructive — the evaluator label stays official).
"""


def _index_evaluator(evaluator_output: dict) -> dict:
    """clause_id -> label from the evaluator's evaluations list."""
    out = {}
    for ev in evaluator_output.get("evaluations", []):
        cid = ev.get("clause_id")
        if cid:
            out[str(cid)] = ev.get("clause_label")
    return out


def _index_labels(output: dict, key: str) -> dict:
    """clause_id -> label from a list under `key` ('clause_labels' or 'labels')."""
    out = {}
    if not isinstance(output, dict):
        return out
    for item in output.get(key, []) or []:
        if isinstance(item, dict) and item.get("clause_id"):
            out[str(item["clause_id"])] = item.get("label")
    return out


def _cell(label, model):
    """Build a {label, model} cell, or None if no label is available."""
    if label is None:
        return None
    return {"label": label, "model": model}


def build_label_panel(
    evaluator_output: dict,
    reflector_a: dict,
    reflector_b: dict,
    blind_a: dict | None,
    blind_b: dict | None,
    models: dict,
    blind_enabled: bool,
) -> dict:
    """
    Build the label panel.

    Args:
        evaluator_output: Agent 2 output (uses "evaluations"[].clause_label).
        reflector_a / reflector_b: Reflector outputs (use "clause_labels").
        blind_a / blind_b: Blind labeler outputs (use "labels"); None if disabled.
        models: dict with keys evaluator, reflector_a, reflector_b, blind_a, blind_b.
        blind_enabled: whether the blind labeler tier ran.

    Returns:
        {"per_clause": [...], "anchoring_summary": {...},
         "disputed_count": int, "blind_labeler_enabled": bool}
    """
    eval_labels = _index_evaluator(evaluator_output)
    ra_labels = _index_labels(reflector_a, "clause_labels")
    rb_labels = _index_labels(reflector_b, "clause_labels")
    ba_labels = _index_labels(blind_a, "labels") if blind_enabled else {}
    bb_labels = _index_labels(blind_b, "labels") if blind_enabled else {}

    per_clause = []
    a_changed = a_total = 0
    b_changed = b_total = 0
    disputed_count = 0

    for cid in eval_labels:  # iterate in evaluator order
        ev_label = eval_labels.get(cid)
        ra_label = ra_labels.get(cid)
        rb_label = rb_labels.get(cid)
        ba_label = ba_labels.get(cid) if blind_enabled else None
        bb_label = bb_labels.get(cid) if blind_enabled else None

        row = {
            "clause_id": cid,
            "evaluator":   _cell(ev_label, models.get("evaluator")),
            "reflector_a": _cell(ra_label, models.get("reflector_a")),
            "reflector_b": _cell(rb_label, models.get("reflector_b")),
            "blind_a":     _cell(ba_label, models.get("blind_a")) if blind_enabled else None,
            "blind_b":     _cell(bb_label, models.get("blind_b")) if blind_enabled else None,
        }

        # Dispute = any disagreement among the labels that are PRESENT (non-null)
        present = [l for l in (ev_label, ra_label, rb_label, ba_label, bb_label) if l is not None]
        row["disputed"] = len(set(present)) > 1
        if row["disputed"]:
            disputed_count += 1

        # Anchoring shift (only when blind tier ran)
        if blind_enabled:
            shift = {}
            if ra_label is not None and ba_label is not None:
                a_total += 1
                changed = ra_label != ba_label
                if changed:
                    a_changed += 1
                shift["reflector_a_vs_blind_a"] = "changed" if changed else "no_change"
            else:
                shift["reflector_a_vs_blind_a"] = "unavailable"
            if rb_label is not None and bb_label is not None:
                b_total += 1
                changed = rb_label != bb_label
                if changed:
                    b_changed += 1
                shift["reflector_b_vs_blind_b"] = "changed" if changed else "no_change"
            else:
                shift["reflector_b_vs_blind_b"] = "unavailable"
            row["anchoring_shift"] = shift
        else:
            row["anchoring_shift"] = "not measured (blind labeler disabled)"

        per_clause.append(row)

    if blind_enabled:
        anchoring_summary = {
            "reflector_a": {
                "model": models.get("reflector_a"),
                "clauses_changed": a_changed,
                "total": a_total,
                "shift_rate": round(a_changed / a_total, 4) if a_total else None,
            },
            "reflector_b": {
                "model": models.get("reflector_b"),
                "clauses_changed": b_changed,
                "total": b_total,
                "shift_rate": round(b_changed / b_total, 4) if b_total else None,
            },
        }
    else:
        anchoring_summary = None

    return {
        "per_clause": per_clause,
        "anchoring_summary": anchoring_summary,
        "disputed_count": disputed_count,
        "blind_labeler_enabled": blind_enabled,
    }


def annotate_finalizer_with_disputes(finalizer_output: dict, label_panel: dict) -> None:
    """
    Non-destructive: append disputed clause IDs to the finalizer's unresolved_flags
    and downgrade confidence to 'low' if any clause is disputed. Mutates in place.
    """
    disputed_ids = [
        row["clause_id"] for row in label_panel.get("per_clause", [])
        if row.get("disputed")
    ]
    if not disputed_ids:
        return
    flag = (
        f"Label disputed on {len(disputed_ids)} clause(s) "
        f"({', '.join(disputed_ids)}): independent labelers did not agree. "
        f"Human reviewer should check these clauses. The Evaluator's label is retained as official."
    )
    finalizer_output.setdefault("unresolved_flags", [])
    if flag not in finalizer_output["unresolved_flags"]:
        finalizer_output["unresolved_flags"].append(flag)
    finalizer_output["confidence"] = "low"
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `python tests/test_label_panel.py`
Expected output: `OK`

- [ ] **Step 5: Commit**

```bash
git add utils/label_panel.py tests/test_label_panel.py
git commit -m "feat: add label panel builder with anchoring measurement (tested)"
```

---

## Task 8: Wire the blind labelers and panel into the orchestrator

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add imports**

In `main.py`, add to the imports near the top (alongside the other agent imports):

```python
from agents.blind_labeler import run_blind_labeler
from utils.label_panel import build_label_panel, annotate_finalizer_with_disputes
from config import ENABLE_BLIND_LABELER
```

> `DEFAULT_AGENT_MODELS`, `DEFAULT_MODEL`, and `OPENROUTER_BASE_URL` are already imported from `config` — add `ENABLE_BLIND_LABELER` to that existing import line instead of duplicating it if you prefer.

- [ ] **Step 2: Add the `--no-blind-labeler` CLI flag**

In `main()`, after the existing `--model-finalizer` argument block, add:

```python
    parser.add_argument(
        "--no-blind-labeler",
        action="store_true",
        help="Disable the Blind Labeler tier for this run (skips 2 LLM calls; "
             "label panel still records evaluator + reflector labels).",
    )
```

- [ ] **Step 3: Resolve blind-labeler models and thread the toggle into the pipeline**

In `main()`, extend the `agent_models` dict with the two blind slots (after the `finalizer` line):

```python
        "blind_a":     _resolve("blind_a",     None),
        "blind_b":     _resolve("blind_b",     None),
```

Then compute the effective toggle and pass it into `run_pipeline`. Change the call:

```python
        result = run_pipeline(client, policy_path, agent_models=agent_models)
```
to:
```python
        blind_enabled = ENABLE_BLIND_LABELER and not args.no_blind_labeler
        result = run_pipeline(
            client, policy_path, agent_models=agent_models, blind_enabled=blind_enabled
        )
```

- [ ] **Step 4: Update `run_pipeline` signature and run the blind labelers**

Change the `run_pipeline` signature:

```python
def run_pipeline(client: OpenAI, policy_path: Path, agent_models: dict) -> dict:
```
to:
```python
def run_pipeline(client: OpenAI, policy_path: Path, agent_models: dict,
                 blind_enabled: bool = True) -> dict:
```

In `run_pipeline`, insert the blind-labeling + panel build **immediately after the initial dual-reflector merge** (right after `initial_reflector_output = merge_reflector_outputs(...)` and its print, and **before** the `if initial_reflector_output.get("review_status") == "errors_found":` retry block). This placement is required: a retry can reassign `verified_clauses`, but the panel must measure anchoring on the **same initial clause set** that `reflector_a_initial` / `reflector_b_initial` labeled.

Insert:

```python
    # ------------------------------------------------------------------
    # Blind Labelers + Label Panel
    # ------------------------------------------------------------------
    blind_a_output = None
    blind_b_output = None
    if blind_enabled:
        print("\n[Blind Labeler A] Independent (unanchored) labeling...")
        blind_a_output = run_blind_labeler(
            client, verified_clauses, model=agent_models["blind_a"]
        )
        print(f"  Blind A labeled {len(blind_a_output.get('labels', []))} clause(s).")

        print("\n[Blind Labeler B] Independent (unanchored) labeling...")
        blind_b_output = run_blind_labeler(
            client, verified_clauses, model=agent_models["blind_b"]
        )
        print(f"  Blind B labeled {len(blind_b_output.get('labels', []))} clause(s).")
    else:
        print("\n[Blind Labeler] Disabled for this run.")

    label_panel = build_label_panel(
        evaluator_output=evaluator_output,
        reflector_a=reflector_a_initial,
        reflector_b=reflector_b_initial,
        blind_a=blind_a_output,
        blind_b=blind_b_output,
        models=agent_models,
        blind_enabled=blind_enabled,
    )
    print(f"  [Label Panel] {label_panel['disputed_count']} disputed clause(s).")
    if blind_enabled and label_panel.get("anchoring_summary"):
        for ref_key in ("reflector_a", "reflector_b"):
            s = label_panel["anchoring_summary"][ref_key]
            rate = s["shift_rate"]
            rate_str = f"{rate:.0%}" if rate is not None else "n/a"
            print(f"  [Anchoring] {ref_key} ({s['model']}): "
                  f"{s['clauses_changed']}/{s['total']} changed ({rate_str}).")
```

> The `label_panel` local variable built here is used later (Step 5) after the Finalizer runs. Building it before the retry loop guarantees it reflects the initial clause set.

- [ ] **Step 5: Annotate the finalizer with disputes and add the panel to the result**

After the `finalizer_output = run_finalizer(...)` call in `run_pipeline` (which is after the retry loop), add:

```python
    annotate_finalizer_with_disputes(finalizer_output, label_panel)
```

In the `return { ... }` dict of `run_pipeline`, add two keys (place them after `"finalizer_output": finalizer_output,`):

```python
        "label_panel": label_panel,
        "blind_a_output": blind_a_output,
        "blind_b_output": blind_b_output,
```

- [ ] **Step 6: Confirm `main.py` imports and `--help` works**

Run: `python -c "import main; print('OK')"`
Expected output: `OK`

Run: `python main.py --help`
Expected: help text includes `--no-blind-labeler`.

- [ ] **Step 7: Commit**

```bash
git add main.py
git commit -m "feat: run blind labelers and build label panel in pipeline"
```

---

## Task 9: Render the Label Panel in the Markdown report

**Files:**
- Modify: `utils/report_generator.py`

- [ ] **Step 1: Read the panel in the report generator**

In `utils/report_generator.py`, inside `generate_report`, add near the other `result.get(...)` lookups at the top:

```python
    label_panel = result.get("label_panel", {})
```

- [ ] **Step 2: Render the panel section**

Add the following block just before the final `out_path.write_text("\n".join(lines), encoding="utf-8")` line:

```python
    # -----------------------------------------------------------------------
    # Label Panel
    # -----------------------------------------------------------------------
    if label_panel and label_panel.get("per_clause"):
        lines.append(f"---")
        lines.append(f"")
        lines.append(f"## Label Panel")
        lines.append(f"")
        blind_on = label_panel.get("blind_labeler_enabled", False)

        # Model legend
        first = label_panel["per_clause"][0]
        def _model_of(cell):
            return cell.get("model") if isinstance(cell, dict) else "n/a"
        lines.append(f"**Models:** "
                     f"Evaluator = `{_model_of(first.get('evaluator'))}` | "
                     f"Reflector A = `{_model_of(first.get('reflector_a'))}` | "
                     f"Reflector B = `{_model_of(first.get('reflector_b'))}`"
                     + (f" | Blind A = `{_model_of(first.get('blind_a'))}` | "
                        f"Blind B = `{_model_of(first.get('blind_b'))}`" if blind_on else ""))
        lines.append(f"")

        def _lab(cell):
            return cell.get("label") if isinstance(cell, dict) else "—"

        if blind_on:
            lines.append(f"| Clause | Evaluator | Reflector A | Reflector B | Blind A | Blind B | Status |")
            lines.append(f"|---|---|---|---|---|---|---|")
            for row in label_panel["per_clause"]:
                status = "⚠️ Disputed" if row.get("disputed") else "✅ Agreed"
                lines.append(
                    f"| {row['clause_id']} | {_lab(row.get('evaluator'))} | "
                    f"{_lab(row.get('reflector_a'))} | {_lab(row.get('reflector_b'))} | "
                    f"{_lab(row.get('blind_a'))} | {_lab(row.get('blind_b'))} | {status} |"
                )
        else:
            lines.append(f"| Clause | Evaluator | Reflector A | Reflector B | Status |")
            lines.append(f"|---|---|---|---|---|")
            for row in label_panel["per_clause"]:
                status = "⚠️ Disputed" if row.get("disputed") else "✅ Agreed"
                lines.append(
                    f"| {row['clause_id']} | {_lab(row.get('evaluator'))} | "
                    f"{_lab(row.get('reflector_a'))} | {_lab(row.get('reflector_b'))} | {status} |"
                )
        lines.append(f"")
        lines.append(f"- Disputed clauses: **{label_panel.get('disputed_count', 0)}**")

        # Anchoring summary
        summary = label_panel.get("anchoring_summary")
        if blind_on and summary:
            lines.append(f"")
            lines.append(f"### Anchoring Summary")
            lines.append(f"")
            for ref_key, label in (("reflector_a", "Reflector A"), ("reflector_b", "Reflector B")):
                s = summary.get(ref_key, {})
                rate = s.get("shift_rate")
                rate_str = f"{rate:.0%}" if rate is not None else "n/a"
                lines.append(
                    f"- {label} (`{s.get('model')}`): changed its label on "
                    f"**{s.get('clauses_changed', 0)}/{s.get('total', 0)}** clause(s) "
                    f"after seeing the Evaluator — anchoring shift **{rate_str}**."
                )
        elif not blind_on:
            lines.append(f"")
            lines.append(f"_Blind labeling disabled for this run — anchoring not measured._")
        lines.append(f"")
```

- [ ] **Step 3: Confirm the module imports**

Run: `python -c "import utils.report_generator; print('OK')"`
Expected output: `OK`

- [ ] **Step 4: Smoke-test the renderer with a synthetic result**

Run:
```bash
python -c "
from pathlib import Path
from utils.report_generator import generate_report
result = {
  'policy_name': 'demo', 'finalizer_output': {}, 'evaluator_output': {}, 'extractor_output': {},
  'final_reflector_output': {}, 'verified_clauses': [], 'flagged_clauses': [],
  'reflector_a_initial': {}, 'reflector_b_initial': {},
  'label_panel': {
    'blind_labeler_enabled': True, 'disputed_count': 1,
    'per_clause': [{'clause_id':'C1','evaluator':{'label':'Compliant','model':'E'},
      'reflector_a':{'label':'Non-Compliant','model':'Ra'},'reflector_b':{'label':'Compliant','model':'Rb'},
      'blind_a':{'label':'Compliant','model':'Ra'},'blind_b':{'label':'Compliant','model':'Rb'},
      'disputed':True,'anchoring_shift':{'reflector_a_vs_blind_a':'changed','reflector_b_vs_blind_b':'no_change'}}],
    'anchoring_summary': {'reflector_a':{'model':'Ra','clauses_changed':1,'total':1,'shift_rate':1.0},
      'reflector_b':{'model':'Rb','clauses_changed':0,'total':1,'shift_rate':0.0}}}}
generate_report(result, Path('output/_demo_report.md'))
txt = Path('output/_demo_report.md').read_text(encoding='utf-8')
assert '## Label Panel' in txt and 'Anchoring Summary' in txt and 'Disputed' in txt
print('OK')
"
```
Expected output: `OK`

- [ ] **Step 5: Commit**

```bash
git add utils/report_generator.py
git commit -m "feat: render label panel and anchoring summary in markdown report"
```

---

## Task 10: End-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full pipeline with the blind labeler ON**

Run: `python main.py --policy data/policies/policy_short.txt`

Expected in terminal: `[Blind Labeler A]` and `[Blind Labeler B]` sections appear, a `[Label Panel] N disputed clause(s).` line, and two `[Anchoring]` lines. Pipeline completes and saves output.

- [ ] **Step 2: Confirm the JSON contains the panel**

Run:
```bash
python -c "
import json, glob, os
f = max(glob.glob('output/results/policy_short_run*.json'), key=os.path.getmtime)
d = json.load(open(f, encoding='utf-8'))
lp = d['label_panel']
print('per_clause:', len(lp['per_clause']))
print('blind_enabled:', lp['blind_labeler_enabled'])
print('disputed_count:', lp['disputed_count'])
print('has anchoring_summary:', lp['anchoring_summary'] is not None)
"
```
Expected: non-zero `per_clause`, `blind_enabled: True`, an integer `disputed_count`, `has anchoring_summary: True`.

- [ ] **Step 3: Confirm the Markdown report has the panel**

Open the newest `output/results/policy_short_run*_report.md` and confirm a `## Label Panel` section with a table and an `### Anchoring Summary` section are present.

- [ ] **Step 4: Run with the blind labeler OFF**

Run: `python main.py --policy data/policies/policy_short.txt --no-blind-labeler`

Expected: terminal shows `[Blind Labeler] Disabled for this run.`; pipeline completes.

Run:
```bash
python -c "
import json, glob, os
f = max(glob.glob('output/results/policy_short_run*.json'), key=os.path.getmtime)
d = json.load(open(f, encoding='utf-8'))
lp = d['label_panel']
print('blind_enabled:', lp['blind_labeler_enabled'])
print('anchoring_summary:', lp['anchoring_summary'])
row = lp['per_clause'][0]
print('blind_a:', row['blind_a'], '| anchoring_shift:', row['anchoring_shift'])
"
```
Expected: `blind_enabled: False`, `anchoring_summary: None`, `blind_a: None`, and `anchoring_shift: not measured (blind labeler disabled)`.

- [ ] **Step 5: Final commit (if any cleanup was needed)**

```bash
git add -A
git commit -m "test: verify label panel end-to-end (blind on and off)" --allow-empty
```

---

## Notes for the implementer

- **No pytest in this repo.** Run test files directly with `python tests/<file>.py`; they print `OK` on success and raise `AssertionError` on failure.
- **Keep `blind_a`/`blind_b` model slugs equal to `reflector_a`/`reflector_b`.** The anchoring measurement is only valid when each blind/anchored pair shares a model.
- **Do not touch the retry loop, the verifier, or the merge logic.** The label panel is built from the *initial* reflector pass and runs alongside the pipeline, not inside its control flow.
- **The evaluator's label remains official.** Disputes only add human-review flags and lower confidence — they never overwrite a label.
