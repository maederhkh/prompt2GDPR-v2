# Design Spec: Label Panel & Anchoring Measurement

**Date:** 2026-05-21
**Component:** Agent 3 layer (Reflectors) + new Blind Labeler layer
**Type:** New feature — cross-model label transparency and anchoring-bias measurement

---

## 1. Problem

The pipeline produces a single official compliance label per clause from the Evaluator (Agent 2). There is no record of how *other* models would label the same clause, and no way to tell when a label is contested.

Two needs follow from this:

1. **Trust / transparency** — when independent models disagree on a clause's label, that clause deserves human attention. Today disagreement is invisible.
2. **Research** — this project is not only a legal tool; it is a study of how different models behave on the same legal judgment. To study that, the pipeline must record each model's independent label per clause, tagged with the model that produced it, so results remain interpretable even as models are swapped over time.

A complication blocks the naive solution. The two Reflectors (Agent 3A/3B) already read every clause and could state their own label — but they audit the Evaluator's output, so they see the Evaluator's label *before* forming a view. Their labels are therefore **anchored** toward agreement. Using anchored labels as if they were independent would inflate measured agreement and invalidate the research.

---

## 2. Evidence the anchoring problem is real

A literature review (conducted via web search during design) confirmed the problem is well-documented and large in magnitude:

- **Sycophancy** — models prioritise agreement with a shown answer over independent judgment. Stanford's *SycEval* found models changed a correct answer ~58% of the time when shown a contradictory rebuttal (Ranaldi et al., AAAI/AIES 2025). Anthropic identified RLHF as the root cause (Perez et al., 2023).
- **Anchoring bias** — outputs drift toward a salient prior value. He et al. (2025) measured anchoring on 22–61% of judgments depending on model size; **cheaper/smaller models anchor more** — directly relevant since this pipeline uses cheap models.
- **Label-induced bias** — the precise case here: models "systematically overrate outputs that already carry positive labels and underrate those with negative priors" (*Quantifying Label-Induced Bias in LLM Self- and Cross-Evaluations*, 2025).
- **Herding in multi-agent setups** — agents converge on the first confident answer, producing superficially harmonious but epistemically hollow consensus (*Peacemaker or Troublemaker*, 2025; CONSENSAGENT, ACL Findings 2025).

The established guidance (MT-Bench, PoLL) is that an agreement figure measured *after* a model has seen a prior label must be reported honestly as "post-disclosure agreement," not as independent inter-rater reliability.

See **Section 10 — References** for full citations.

---

## 3. Solution overview

Adopt the literature's recommended design for a research-focused setup: **add a blind labeling tier and measure the anchoring delta** rather than only trying to avoid it (recommended directly by the label-induced-bias paper and supported by the PoLL jury approach).

Concretely:

- Keep the Evaluator unchanged. Its label stays the **official** output.
- Keep the two Reflectors as auditors, with **one small addition**: each emits its own verdict label per clause (the *anchored* label — it has seen the Evaluator).
- Add **two Blind Labelers**, each using the **identical model** to one Reflector, but seeing **only** the clause + rubric — never the Evaluator's output (the *blind* label).
- Because each blind/anchored pair shares a model, the only difference between them is whether the Evaluator's label was visible. The label-change rate across that pair **is** the anchoring measurement for that model.
- Assemble everything into a per-clause **Label Panel** and surface it in both JSON and Markdown output.

This dual-condition (blind vs anchored) within-model comparison turns the bias from a nuisance into a measurable, reportable finding.

---

## 4. Architecture

```
Verified clauses
   ├─► Evaluator (Agent 2)            → official label   [sees legal tool]
   │
   ├─► Reflector A (sees Evaluator)   → audit + anchored label   [model Rₐ]
   ├─► Reflector B (sees Evaluator)   → audit + anchored label   [model R_b]
   │
   ├─► Blind Labeler A (NO Evaluator) → blind label   [model Rₐ, same legal tool]
   └─► Blind Labeler B (NO Evaluator) → blind label   [model R_b, same legal tool]
                     │
                     ▼
        Label Panel builder (Python, no LLM)
                     │
   per clause: {evaluator, reflector_a, reflector_b, blind_a, blind_b,
                disputed, anchoring_shift}
                     │
                     ▼
        JSON output + Markdown report
```

### Anchoring measurement (per model)

| Pair | Compares | Yields |
|---|---|---|
| Model Rₐ | `blind_a` vs `reflector_a` | anchoring shift for Reflector A's model |
| Model R_b | `blind_b` vs `reflector_b` | anchoring shift for Reflector B's model |

**Documented limitation:** the anchored label is produced inside the Reflector's audit-framed prompt, whereas the blind label comes from a pure labeling prompt. The measured delta therefore reflects anchoring *as it occurs in this pipeline's real working condition* (the Reflector is genuinely an auditor), with audit-framing held as part of that condition. The blind labeler is the clean counterfactual ("what would this same model say judging fresh"). This is the most pipeline-relevant measurement available without adding a third, lab-only labeling condition.

---

## 5. Confound controls

To ensure label differences are attributable to the **model**, not to how each was asked, the following are held identical across the Evaluator and both Blind Labelers:

| Element | Control |
|---|---|
| Rubric text | Single shared constant `prompts/rubric.py`, imported by Evaluator and Blind Labeler prompts |
| Legal reference access | Blind Labelers get the **same** `get_legal_reference` tool the Evaluator has |
| Sampling temperature | **0** for all label-producing calls — Evaluator, both Blind Labelers, **and both Reflectors** (so an anchored-vs-blind label difference reflects the model, not sampling noise) |
| Clause input format | Identical fields (`clause_id`, `quote`, `section_reference`, `relevance_type`) in identical JSON |
| Output label enum | Exactly `"Compliant"`, `"Partially Compliant"`, `"Non-Compliant"` |
| Batch size | Same as Evaluator (15 clauses per call) |
| Model pinning | Exact OpenRouter slugs; recorded per-clause in the panel |

**Residual confound (documented):** giving every labeler the legal tool equalises capability, but each labeler now independently *chooses* which references to retrieve, making retrieval choice a minor variable. Capability equalisation is judged the larger benefit.

---

## 6. On/Off toggle

The Blind Labeler tier is optional per run.

- `config.py`: `ENABLE_BLIND_LABELER = True` (default on)
- CLI override: `--no-blind-labeler` disables it for a single run without editing config

**When ON:** full design — blind labelers run, anchoring delta measured.

**When OFF:**
- The two Blind Labeler calls are skipped entirely (saves cost and time).
- The Label Panel still builds, showing `evaluator`, `reflector_a`, `reflector_b`, and `disputed`.
- `blind_a` / `blind_b` = `null`; `anchoring_shift` = `"not measured (blind labeler disabled)"`.
- Markdown omits the blind columns; the anchoring summary line reads *"Blind labeling disabled for this run."*

No other pipeline component depends on the blind labeler being on.

---

## 7. Data structures

### Reflector output — one new field

```json
{
  "review_status": "errors_found",
  "errors": [ ... ],
  "clause_labels": [
    { "clause_id": "C5", "label": "Non-Compliant" },
    { "clause_id": "C6", "label": "Compliant" }
  ],
  "reflector_notes": "..."
}
```

### Blind Labeler output

```json
{
  "labels": [
    { "clause_id": "C5", "label": "Compliant" },
    { "clause_id": "C6", "label": "Compliant" }
  ]
}
```

### Label Panel (new `label_panel` key in the result dict)

```json
{
  "label_panel": {
    "per_clause": [
      {
        "clause_id": "C5",
        "evaluator":   { "label": "Compliant",     "model": "google/gemini-2.0-flash-001" },
        "reflector_a": { "label": "Non-Compliant", "model": "openai/gpt-4o-mini" },
        "reflector_b": { "label": "Compliant",     "model": "openai/gpt-4o-mini" },
        "blind_a":     { "label": "Non-Compliant", "model": "openai/gpt-4o-mini" },
        "blind_b":     { "label": "Partially Compliant", "model": "openai/gpt-4o-mini" },
        "disputed": true,
        "anchoring_shift": {
          "reflector_a_vs_blind_a": "no_change",
          "reflector_b_vs_blind_b": "changed"
        }
      }
    ],
    "anchoring_summary": {
      "reflector_a": { "model": "openai/gpt-4o-mini", "clauses_changed": 6, "total": 48, "shift_rate": 0.125 },
      "reflector_b": { "model": "openai/gpt-4o-mini", "clauses_changed": 3, "total": 48, "shift_rate": 0.0625 }
    },
    "disputed_count": 7,
    "blind_labeler_enabled": true
  }
}
```

Role name is always listed before the model slug so the record self-documents which model held which role at the time of the run, surviving later model swaps.

---

## 8. Disagreement (dispute) rule

For each clause, collect all available labels (`evaluator`, `reflector_a`, `reflector_b`, and when enabled, `blind_a`, `blind_b`).

`disputed = true` if those labels are **not all identical** — a single dissent is enough.

Disputes are **non-destructive**:
- The Evaluator's label remains the official one.
- Disputed clause IDs are added to the Finalizer's human-review notes.
- The presence of disputes contributes to a lower confidence level.

---

## 9. Files changed

| File | Action | Change |
|---|---|---|
| `prompts/rubric.py` | Create | Shared rubric constant (Stage 1 / Stage 2 / Article 89 tables + label decision rules), extracted from the current evaluator prompt |
| `prompts/blind_labeler_prompt.py` | Create | System + user template for blind labeling; imports the shared rubric |
| `agents/blind_labeler.py` | Create | `run_blind_labeler(client, verified_clauses, model)` — same legal tool, temperature 0, batch size 15, returns labels list |
| `utils/label_panel.py` | Create | `build_label_panel(...)` — pure Python; assembles per-clause panel, computes `disputed` and `anchoring_shift`, builds `anchoring_summary` |
| `prompts/reflector_prompt.py` | Modify | Add `clause_labels` to output schema + instruction to emit a verdict label per clause |
| `prompts/evaluator_prompt.py` | Modify | Import rubric from `prompts/rubric.py` instead of inlining it (no wording change) |
| `utils/schema_validator.py` | Modify | Tolerate/validate `clause_labels` (reflector) and `labels` (blind labeler); robust to omission |
| `config.py` | Modify | Add `ENABLE_BLIND_LABELER`, add `blind_a` / `blind_b` model slots, define temperature 0 for all label-producing calls |
| `agents/evaluator.py` + `agents/reflector.py` | Modify | Pass `temperature=0` on label-producing calls |
| `main.py` | Modify | Add `--no-blind-labeler` flag; run blind labelers when enabled; call `build_label_panel`; add `label_panel` to result dict |
| `utils/report_generator.py` | Modify | Render the Label Panel table + anchoring summary in the Markdown report |

No change to: the verifier, the retry loop, the merge logic, or the Finalizer's core flow (it only gains disputed-clause notes).

---

## 10. Error handling

| Failure | Behaviour |
|---|---|
| Blind Labeler call fails | Log warning; that clause's `blind_x` = `null`, `anchoring_shift` = `"unavailable"`; pipeline continues |
| Reflector omits `clause_labels` | Panel records `reflector_x` label as `null` for affected clauses; not treated as a dispute driver |
| Blind labeler disabled | Panel built without blind columns (Section 6) |
| Clause appears in one source but not another | Panel still emitted; missing labels recorded as `null` |

The Label Panel never raises — all gaps degrade to `null` and are surfaced for human review.

---

## 11. References

Sources identified during design research (verified via web search). Anchoring/sycophancy evidence and mitigation design:

1. Lianmin Zheng et al., "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena," NeurIPS 2023. https://arxiv.org/abs/2306.05685
2. Pat Verga et al. (Cohere), "Replacing Judges with Juries: Evaluating LLM Generations with a Panel of Diverse Models" (PoLL), arXiv 2404.18796, 2024. https://arxiv.org/abs/2404.18796
3. He et al., "Understanding the Anchoring Effect of LLM with Synthetic Data: Existence, Mechanism, and Potential Mitigations," arXiv 2505.15392, 2025 (ICLR HCAIR Workshop). https://arxiv.org/abs/2505.15392
4. Ethan Perez et al. (Anthropic), "Towards Understanding Sycophancy in Language Models," 2023. https://www.anthropic.com/research/towards-understanding-sycophancy-in-language-models
5. Ranaldi et al. (Stanford), "SycEval: Evaluating LLM Sycophancy," AAAI/AIES 2025. https://arxiv.org/abs/2502.08177
6. "Quantifying Label-Induced Bias in Large Language Model Self- and Cross-Evaluations," arXiv 2508.21164, 2025. https://arxiv.org/pdf/2508.21164
7. "Peacemaker or Troublemaker: How Sycophancy Shapes Multi-Agent Debate," arXiv 2509.23055, 2025. https://arxiv.org/pdf/2509.23055
8. CONSENSAGENT, "Towards Efficient and Effective Consensus in Multi-Agent LLM Interactions Through Sycophancy Mitigation," ACL Findings 2025. https://aclanthology.org/2025.findings-acl.1141/
9. Seungone Kim et al., "Prometheus: Inducing Fine-grained Evaluation Capability in Language Models," ICLR 2024. https://arxiv.org/abs/2310.08491
10. Yang Liu et al., "G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment," EMNLP 2023. https://arxiv.org/abs/2303.16634
11. Yuntao Bai et al. (Anthropic), "Constitutional AI: Harmlessness from AI Feedback," arXiv 2212.08073, 2022. https://arxiv.org/abs/2212.08073
12. Wang et al., "Large Language Models are not Fair Evaluators," 2023. https://arxiv.org/pdf/2305.17926

How specific recommendations map to this design:
- **Blind labeling tier** (primary mitigation) — ref. 6 (label-induced bias), ref. 1 (reference-guided judging).
- **Measure the anchoring delta** rather than only avoiding it — ref. 6, ref. 3.
- **Same-model blind/anchored pairing** for a within-model comparison — ref. 6 (sequential evaluation: evaluate before revealing labels).
- **Report post-disclosure vs independent agreement separately** — ref. 1, ref. 2.
- **Shared rubric to remove wording confound** — ref. 9 (Prometheus rubric anchoring).
