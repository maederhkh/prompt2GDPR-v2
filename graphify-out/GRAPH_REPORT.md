# Graph Report - .  (2026-06-17)

## Corpus Check
- 53 files · ~54,611 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 424 nodes · 727 edges · 24 communities (19 shown, 5 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 30 edges (avg confidence: 0.85)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Run Summary & Index Analysis|Run Summary & Index Analysis]]
- [[_COMMUNITY_Three-Pass Clause Extraction|Three-Pass Clause Extraction]]
- [[_COMMUNITY_Pipeline Orchestration & Finalizer|Pipeline Orchestration & Finalizer]]
- [[_COMMUNITY_Run Diff Tooling|Run Diff Tooling]]
- [[_COMMUNITY_Blind Labeling & Evaluation|Blind Labeling & Evaluation]]
- [[_COMMUNITY_GDPR Legal References & Policies|GDPR Legal References & Policies]]
- [[_COMMUNITY_Reflector Audit & Finalizer|Reflector Audit & Finalizer]]
- [[_COMMUNITY_Policy Input Loader|Policy Input Loader]]
- [[_COMMUNITY_Runs Index Builder|Runs Index Builder]]
- [[_COMMUNITY_Label Panel & Dispute Detection|Label Panel & Dispute Detection]]
- [[_COMMUNITY_Extractor Test Harness (Fake Client)|Extractor Test Harness (Fake Client)]]
- [[_COMMUNITY_Run Metadata & Provenance|Run Metadata & Provenance]]
- [[_COMMUNITY_Agent Batching & Anchoring Metrics|Agent Batching & Anchoring Metrics]]
- [[_COMMUNITY_Evaluation Metrics (M1-M5)|Evaluation Metrics (M1-M5)]]
- [[_COMMUNITY_Extraction Architecture (Concepts)|Extraction Architecture (Concepts)]]
- [[_COMMUNITY_Analyze-Runs Entrypoint|Analyze-Runs Entrypoint]]
- [[_COMMUNITY_Labeler Temperature Config|Labeler Temperature Config]]
- [[_COMMUNITY_Token Budget Config|Token Budget Config]]
- [[_COMMUNITY_Diff-Runs Entrypoint|Diff-Runs Entrypoint]]
- [[_COMMUNITY_Label Stability Metric|Label Stability Metric]]

## God Nodes (most connected - your core abstractions)
1. `run_pipeline()` - 28 edges
2. `load_policy_text()` - 21 edges
3. `parse_and_repair()` - 20 edges
4. `build_label_panel()` - 18 edges
5. `run_extractor()` - 14 edges
6. `append_run_to_index()` - 14 edges
7. `build_run_metadata()` - 13 edges
8. `run_evaluator()` - 11 edges
9. `summarize()` - 11 edges
10. `_run()` - 10 edges

## Surprising Connections (you probably didn't know these)
- `Sample Policy PDF Fixture` --semantically_similar_to--> `Article 5(1)(b) Purpose Limitation Principle`  [INFERRED] [semantically similar]
  tests/fixtures/sample_policy.pdf → data/legal_refs/primary/article_5_1b.txt
- `run_pipeline()` --references--> `DEFAULT_AGENT_MODELS (per-agent model assignment)`  [INFERRED]
  main.py → config.py
- `run_blind_labeler()` --calls--> `parse_and_repair()`  [EXTRACTED]
  agents/blind_labeler.py → utils/schema_validator.py
- `run_pipeline()` --calls--> `run_blind_labeler()`  [EXTRACTED]
  main.py → agents/blind_labeler.py
- `run_evaluator()` --calls--> `parse_and_repair()`  [EXTRACTED]
  agents/evaluator.py → utils/schema_validator.py

## Import Cycles
- 1-file cycle: `agents/blind_labeler.py -> agents/blind_labeler.py`
- 1-file cycle: `main.py -> main.py`
- 1-file cycle: `agents/evaluator.py -> agents/evaluator.py`
- 1-file cycle: `agents/extractor.py -> agents/extractor.py`
- 1-file cycle: `agents/finalizer.py -> agents/finalizer.py`
- 1-file cycle: `agents/reflector.py -> agents/reflector.py`

## Hyperedges (group relationships)
- **Four-agent compliance pipeline flow (extract -> evaluate -> reflect -> finalize)** — extractor_run_extractor, evaluator_run_evaluator, reflector_run_reflector, finalizer_run_finalizer, main_run_pipeline [EXTRACTED 1.00]
- **Three-pass extraction: scout, deep extract, self-check gap filling** — extractor__run_scout, extractor__extract_from_section, extractor__self_check, extractor__find_uncovered_paragraphs, extractor__reextract_gap [EXTRACTED 1.00]
- **M1-M5 evaluation metrics suite** — metrics_m1_rubric_alignment, metrics_m2_evidence_grounding, metrics_m4_structural_completeness, metrics_m5_reflector_correction_rate, metrics_compute_all_metrics [EXTRACTED 1.00]
- **Run provenance and aggregation flow** — utils_run_metadata_build_run_metadata, utils_runs_index_append_run_to_index, utils_runs_summary_summarize [INFERRED 0.80]
- **Multi-labeler dispute and anchoring panel** — utils_label_panel_build_label_panel, utils_label_panel_annotate_finalizer_with_disputes, utils_reflector_merge_merge_reflector_outputs, utils_report_generator_generate_report [INFERRED 0.75]
- **rapidfuzz-based text matching utilities** — utils_verifier__best_match_score, utils_run_diff_match_clauses, utils_section_splitter_split_sections [INFERRED 0.80]
- **Purpose Limitation Legal Reference Corpus** — article_5_1b_purpose_limitation, article_89_safeguards_for_research, recital_39_purpose_specification_at_collection, recital_50_compatible_further_processing, recital_157_scientific_research, wp29_purpose_limitation_excerpts_purpose_specification [EXTRACTED 0.95]
- **Two-Pass Extraction Mechanism** — output_two_pass_extraction_report_two_pass_extraction, output_two_pass_extraction_report_section_scout, output_two_pass_extraction_report_section_splitter, output_two_pass_extraction_report_deep_extractor [EXTRACTED 0.95]
- **Health/Fitness App Privacy Policy Inputs** — policies_policy_long_ada_health_policy, policies_policy_medium_clue_policy, policies_policy_short_garmin_policy, fixtures_sample_policy_sample_policy [INFERRED 0.75]

## Communities (24 total, 5 thin omitted)

### Community 0 - "Run Summary & Index Analysis"
Cohesion: 0.09
Nodes (41): Print and write an aggregate summary of all pipeline runs.  Usage:  python ana, Standalone assert tests for the runs summary analyzer., One synthetic index row (all 15 fields, as strings, like the CSV)., _row(), test_build_summary_md_empty(), test_build_summary_md_per_policy(), test_fallback_rate_none_when_no_judged_runs(), test_load_rejects_old_schema() (+33 more)

### Community 1 - "Three-Pass Clause Extraction"
Cohesion: 0.09
Nodes (37): _extract_from_section(), _find_uncovered_paragraphs(), _judge_paragraph_gap(), OpenAI, Agent 1: Extractor (three-pass architecture)  Pass 1 — Section Scout:     A l, Pass 1: ask the model which sections are relevant to purpose limitation.     Re, Pass 2: extract complete paragraphs from a single policy section.     Returns a, Fallback: original single-pass extraction over the full policy text.     Used w (+29 more)

### Community 2 - "Pipeline Orchestration & Finalizer"
Cohesion: 0.08
Nodes (34): build_retry_instructions(), errors_for_agent(), Filter the Reflector's error list to only errors assigned to a specific agent., Format the Reflector's error list into human-readable retry instructions., Fuzzy quote matching (rapidfuzz), DEFAULT_AGENT_MODELS (per-agent model assignment), _annotate_reflector_status, build_finalizer_prompt (+26 more)

### Community 3 - "Run Diff Tooling"
Cohesion: 0.10
Nodes (35): Compare two pipeline run JSONs clause by clause.  Usage:  python diff_runs.py, Standalone assert tests for the run diff tool., One synthetic run dict. clauses = list of (clause_id, quote, label);     label, _run(), test_build_diff_changes_and_models(), test_build_diff_different_policy(), test_build_diff_missing_models_is_na(), test_clause_labels_join_and_unassessed() (+27 more)

### Community 4 - "Blind Labeling & Evaluation"
Cohesion: 0.08
Nodes (30): OpenAI, Blind Labeler agent.  Assigns a purpose-limitation compliance label to each ve, Split into batches of BLIND_LABELER_BATCH_SIZE and merge label lists., Assign a blind compliance label to each verified clause.      Args:         c, _run_batched(), run_blind_labeler(), OpenAI, Agent 2: Evaluator  Applies the two-stage purpose limitation rubric (Article 5 (+22 more)

### Community 5 - "GDPR Legal References & Policies"
Cohesion: 0.08
Nodes (33): Article 5(1)(b) Purpose Limitation Principle, Data Minimisation, Article 89 Safeguards for Research and Archiving, Sample Policy PDF Fixture, C15 Dropped-Safeguards Problem, Deep Extractor (Pass 2), Section Scout (Pass 1), Section Splitter (rapidfuzz) (+25 more)

### Community 6 - "Reflector Audit & Finalizer"
Cohesion: 0.09
Nodes (26): _annotate_reflector_status(), OpenAI, Agent 4: Finalizer  Consolidates all pipeline outputs into a single structured c, If the reflector output contains unresolved errors (set by the orchestrator),, Call the Finalizer agent and return the complete compliance report.      Args:, run_finalizer(), OpenAI, Agent 3: Reflector  Audits the outputs of Agents 1 and 2, identifies errors, a (+18 more)

### Community 7 - "Policy Input Loader"
Cohesion: 0.14
Nodes (24): Standalone assert tests for the policy input loader., test_docx_generated(), test_html_strips_tags_and_keeps_headings(), test_normalization(), test_pdf_fixture(), test_supported_extensions(), test_txt(), test_unsupported_extension() (+16 more)

### Community 8 - "Runs Index Builder"
Cohesion: 0.14
Nodes (24): _empty_result(), _full_result(), Standalone assert tests for the runs index builder., test_append_newest_first(), test_build_index_row_empty_result(), test_build_index_row_full(), test_build_index_row_single_pass_coverage(), test_schema_mismatch_backs_up() (+16 more)

### Community 9 - "Label Panel & Dispute Detection"
Cohesion: 0.14
Nodes (22): _labels(), Standalone assert tests for the pure-Python label panel builder., test_agreement_not_disputed(), test_anchoring_shift_detected(), test_annotate_finalizer_with_disputes(), test_blind_disabled_skips_blind_columns(), test_missing_label_is_null_not_dispute_driver(), test_single_dissent_is_disputed() (+14 more)

### Community 10 - "Extractor Test Harness (Fake Client)"
Cohesion: 0.17
Nodes (9): _Chat, _Choice, _Completions, FakeClient, _Msg, Standalone assert tests for the extractor's extraction_mode flag.  Uses a mini, _Resp, test_single_pass_mode() (+1 more)

### Community 11 - "Run Metadata & Provenance"
Cohesion: 0.21
Nodes (15): Standalone assert tests for the run-metadata builder., test_build_run_metadata_keys_and_types(), test_git_commit_shape(), test_sha256_hex_changes_with_content(), test_sha256_hex_is_deterministic_and_8_chars(), _git_commit, _sha256_hex, build_run_metadata() (+7 more)

### Community 12 - "Agent Batching & Anchoring Metrics"
Cohesion: 0.14
Nodes (15): _run_batched (blind labeler), build_blind_labeler_prompt, run_blind_labeler, Anchoring measurement (blind vs anchored labels), _run_batched_evaluator, build_evaluator_prompt, run_evaluator, compute_all_metrics (+7 more)

### Community 13 - "Evaluation Metrics (M1-M5)"
Cohesion: 0.19
Nodes (13): compute_all_metrics(), m1_rubric_alignment(), m2_evidence_grounding(), m3_label_stability(), m4_structural_completeness(), m5_reflector_correction_rate(), Evaluation metrics for the agentic GDPR purpose limitation workflow.  Adapted fr, M2: Evidence Grounding Score (adapted FGS).      Two sub-scores:     - Verifier (+5 more)

### Community 14 - "Extraction Architecture (Concepts)"
Cohesion: 0.17
Nodes (13): Three-pass extraction architecture, _extract_from_section, _find_uncovered_paragraphs, _judge_paragraph_gap, _reextract_gap, _run_scout, _run_single_pass, _self_check (+5 more)

## Knowledge Gaps
- **36 isolated node(s):** `Path`, `_run_batched (blind labeler)`, `_run_batched_evaluator`, `_find_uncovered_paragraphs`, `_annotate_reflector_status` (+31 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `run_pipeline()` connect `Pipeline Orchestration & Finalizer` to `Three-Pass Clause Extraction`, `Blind Labeling & Evaluation`, `Reflector Audit & Finalizer`, `Policy Input Loader`, `Label Panel & Dispute Detection`, `Run Metadata & Provenance`, `Agent Batching & Anchoring Metrics`, `Extraction Architecture (Concepts)`?**
  _High betweenness centrality (0.198) - this node is a cross-community bridge._
- **Why does `verify_clauses()` connect `Pipeline Orchestration & Finalizer` to `Three-Pass Clause Extraction`, `Run Diff Tooling`?**
  _High betweenness centrality (0.158) - this node is a cross-community bridge._
- **Why does `match_clauses()` connect `Run Diff Tooling` to `Pipeline Orchestration & Finalizer`?**
  _High betweenness centrality (0.140) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `build_label_panel()` (e.g. with `annotate_finalizer_with_disputes()` and `generate_report()`) actually correct?**
  _`build_label_panel()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Blind Labeler agent.  Assigns a purpose-limitation compliance label to each ve`, `Assign a blind compliance label to each verified clause.      Args:         c`, `Split into batches of BLIND_LABELER_BATCH_SIZE and merge label lists.` to the rest of the system?**
  _167 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Run Summary & Index Analysis` be split into smaller, more focused modules?**
  _Cohesion score 0.08985200845665962 - nodes in this community are weakly interconnected._
- **Should `Three-Pass Clause Extraction` be split into smaller, more focused modules?**
  _Cohesion score 0.08780487804878048 - nodes in this community are weakly interconnected._