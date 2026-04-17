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

# Global default — used when no per-agent model is specified.
DEFAULT_MODEL = "anthropic/claude-sonnet-4-5"

# Per-agent model overrides. Set to None to inherit DEFAULT_MODEL.
# Override these via --model-extractor / --model-evaluator / etc. on the CLI.
DEFAULT_AGENT_MODELS = {
    "extractor":   None,
    "evaluator":   None,
    "reflector_a": None,
    "reflector_b": None,
    "finalizer":   None,
}

# Per-agent token budgets (max_tokens sent to the API)
MAX_TOKENS = {
    "extractor": 4096,
    "evaluator": 6000,
    "reflector": 4096,
    "finalizer": 6000,
}
