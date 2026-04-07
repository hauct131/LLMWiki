from dataclasses import dataclass
from typing import Literal

ModelTier = Literal["3b", "7b", "13b+"]

@dataclass(frozen=True)
class ModelProfile:
    tier: ModelTier
    max_input_chars: int
    max_output_tokens: int
    summary_sentences: int
    key_methods_count: int
    terms_count: int
    temperature: float
    fallback_threshold: str

PROFILES = {
    "3b": ModelProfile(
        tier="3b", max_input_chars=800, max_output_tokens=150,
        summary_sentences=2, key_methods_count=2, terms_count=5,
        temperature=0.1, fallback_threshold="aggressive"
    ),
    "7b": ModelProfile(
        tier="7b", max_input_chars=1500, max_output_tokens=300,
        summary_sentences=3, key_methods_count=3, terms_count=7,
        temperature=0.2, fallback_threshold="normal"
    ),
    "13b+": ModelProfile(
        tier="13b+", max_input_chars=3000, max_output_tokens=600,
        summary_sentences=3, key_methods_count=5, terms_count=10,
        temperature=0.3, fallback_threshold="relaxed"
    )
}