"""
Central configuration for the GDPR Purpose Limitation Compliance Workflow.

OpenRouter model slugs follow the format: "provider/model-name"
Full list: https://openrouter.ai/models

Examples:
  anthropic/claude-sonnet-4-5
  anthropic/claude-opus-4-5
  openai/gpt-4o
  openai/gpt-4o-mini
  google/gemini-2.0-flash-001
  x-ai/grok-2-1212
  meta-llama/llama-3.3-70b-instruct
  mistralai/mistral-large
"""

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Global default — used as a last-resort fallback only.
# In normal operation every agent has an explicit model set in DEFAULT_AGENT_MODELS.
DEFAULT_MODEL = "anthropic/claude-sonnet-4-5"

# Per-agent model assignments.
# Each agent is assigned a model chosen for its specific role:
#
#   scout       — Gemini Flash 3: cheap, fast section identification (no complex reasoning needed)
#   extractor   — GPT 5.3:        strong instruction following for complete paragraph quoting
#   evaluator   — Grok 4.1:       independent reasoning style, complements GPT on legal assessment
#   reflector_a — Claude Sonnet 4.5: first independent auditor
#   reflector_b — GPT 5.3:        second auditor with different style from evaluator (Grok)
#   finalizer   — Claude Sonnet 4.5: reliable structured output generation
#
# Override any of these at runtime via CLI flags (see main.py --help).
DEFAULT_AGENT_MODELS = {
    "scout":       "deepseek/deepseek-v4-flash:free",    # DeepSeek Flash (free) — lightweight section ID
    "extractor":   "deepseek/deepseek-v4-flash:free",    # DeepSeek Flash (free) — verbatim quoting, no legal reasoning
    "evaluator":   "qwen/qwen3-235b-a22b",               # Qwen3 235B — strong legal reasoning
    "reflector_a": "openai/gpt-4o-mini",                 # GPT-4o Mini — first independent auditor
    "reflector_b": "google/gemini-2.0-flash-001",        # Gemini 2.0 Flash — second auditor (different provider)
    "finalizer":   "google/gemini-2.0-flash-001",        # Gemini 2.0 Flash — reliable structured output
}

# Per-agent token budgets (max_tokens sent to the API)
MAX_TOKENS = {
    "scout":     1024,    # Scout only returns a list of section headings — small output
    "extractor": 4096,
    "evaluator": 16000,   # Raised: two-pass extraction can yield 50–100 clauses; each needs full rubric
    "reflector": 8000,    # Raised: more clauses means a longer reflector review
    "finalizer": 8000,    # Raised: final report over many clauses can be long
    "gap_judge": 256,     # Gap judgment: small yes/no response
}
