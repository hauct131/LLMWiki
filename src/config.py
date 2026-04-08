"""
config.py — All tunable constants, model profiles, and quality thresholds.

Nothing is hardcoded in stage files — they read from a Config instance.
This makes the system trivially testable with extreme configurations.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Literal, Optional


ModelTier = Literal["3b", "7b", "13b+"]


@dataclass(frozen=True)
class ModelProfile:
    """
    Per-model-size tuning. Injected into prompt runner and stages.
    Smaller models get shorter inputs, shorter expected outputs, and lower
    temperature so they don't wander.
    """
    tier:                  ModelTier
    max_input_chars:       int    # per prompt
    max_output_tokens:     int
    summary_sentences:     int
    key_methods_count:     int
    terms_count:           int    # P6 term extraction
    temperature:           float
    # How strict to be before giving up on LLM output for a slot
    fallback_threshold:    str    # "aggressive" | "normal" | "relaxed"

    @property
    def is_aggressive(self) -> bool:
        return self.fallback_threshold == "aggressive"


# Three built-in profiles; load from config file or env to override.
PROFILES: dict[ModelTier, ModelProfile] = {
    "3b": ModelProfile(
        tier="3b",
        # Increased for Phi-3.5 to handle larger academic contexts
        max_input_chars=4000,
        max_output_tokens=1024, # Fixed: Prevents truncated sentences like 'generaliz...'
        summary_sentences=3,
        key_methods_count=4,
        terms_count=10,
        temperature=0.1,
        fallback_threshold="normal", # Relaxed from aggressive to allow more AI creativity
    ),
    "7b": ModelProfile(
        tier="7b",
        max_input_chars=1500,
        max_output_tokens=300,
        summary_sentences=3,
        key_methods_count=3,
        terms_count=7,
        temperature=0.2,
        fallback_threshold="normal",
    ),
    "13b+": ModelProfile(
        tier="13b+",
        max_input_chars=3000,
        max_output_tokens=600,
        summary_sentences=3,
        key_methods_count=5,
        terms_count=10,
        temperature=0.3,
        fallback_threshold="relaxed",
    ),
}


@dataclass
class PipelineConfig:
    """
    Runtime configuration for a pipeline run.
    Pass this into the Orchestrator; stages read from it via dependency injection.
    """

    # ── LLM backend ──────────────────────────────────────────────────────────
    model_tier:        ModelTier = "3b" # Set to 3b by default for your 4GB VRAM
    api_base_url:      str       = "http://localhost:11434"   # Ollama default
    api_model_name:    str       = "phi3.5:latest"            # Optimised for Phi-3.5
    api_timeout_secs:  int       = 60 # Increased timeout for larger context windows
    use_remote_api:    bool      = False    # True → OpenAI-compatible remote
    remote_api_key:    str       = ""

    # ── Gemini (priority 1 backend if key is set) ─────────────────────────
    # Single key for backward compatibility
    gemini_api_key:    str       = ""
    # List of keys for rotation (read from env GEMINI_API_KEYS)
    gemini_api_keys:   List[str] = field(default_factory=list)
    gemini_model_name: str       = "gemini-2.0-flash"  # Fast and cheap default

    # ── Output paths ─────────────────────────────────────────────────────────
    output_dir:        str       = "./vault/_sources"
    concepts_dir:      str       = "./vault/_concepts"
    index_path:        str       = "./vault/index.md"
    log_path:          str       = "./vault/log.md"
    sidecar_dir:       str       = "./vault/_sidecars"

    # ── Quality gates ─────────────────────────────────────────────────────────
    # quality_score thresholds (0–100)
    min_score_processed:    int  = 60    # mark "processed"
    min_score_needs_review: int  = 30    # mark "needs-review"; below → "stub"

    # Individual validation thresholds
    min_response_len:       int  = 50    # empty check
    min_section_body_chars: int  = 50    # Slightly relaxed for more concise outputs
    min_summary_words:      int  = 20
    max_garbage_similarity: float = 0.60  # >60% copy of source → garbage

    # ── Context window ────────────────────────────────────────────────────────
    # Characters (not tokens) — conservative estimate; 1 token ≈ 4 chars
    context_window_chars:   int  = 35_000   # Set to 35k to handle full SemEval paper (31k chars)
    chunk_on_overflow:      bool = True      # True → use first chunk only

    # ── Retry policy ──────────────────────────────────────────────────────────
    max_retries_per_level:  int  = 1    # retry once before downgrading
    retry_temperature_delta: float = -0.05  # lower temp on retry

    def __post_init__(self):
        # Load Gemini keys from environment if not explicitly set
        if not self.gemini_api_keys:
            keys_str = os.getenv("GEMINI_API_KEYS", "")
            if keys_str:
                self.gemini_api_keys = [k.strip() for k in keys_str.split(",") if k.strip()]
        # If still empty, try single key from env or from the field
        if not self.gemini_api_keys:
            single_key = self.gemini_api_key or os.getenv("GEMINI_API_KEY", "")
            if single_key:
                self.gemini_api_keys = [single_key]
        # For backward compatibility, set gemini_api_key to the first key if available
        if self.gemini_api_keys and not self.gemini_api_key:
            self.gemini_api_key = self.gemini_api_keys[0]

    # ── Derived ───────────────────────────────────────────────────────────────
    @property
    def profile(self) -> ModelProfile:
        return PROFILES[self.model_tier]

    @property
    def closing_markers(self) -> list[str]:
        """Sections that must exist for a non-truncated response."""
        return ["## Related", "---", "## Open Questions"]