"""
stages/stage0_preprocess.py — Clean and normalise raw input.

No LLM. No external calls. Pure deterministic text processing.

Responsibilities:
  - Strip HTML tags and fix encoding issues.
  - Normalise whitespace.
  - Detect source language (heuristic — good enough for routing).
  - Measure character count and check against context window limit.
  - If source is empty after cleaning → immediately set fallback_level = 4.

Writes to state:
  cleaned_text, detected_language, source_char_count, exceeds_context
"""

from __future__ import annotations

import html
import logging
import re
import unicodedata

from ..config import PipelineConfig
from ..state import FallbackLevel, IngestState

logger = logging.getLogger(__name__)

STAGE_NAME = "stage0_preprocess"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(state: IngestState, config: PipelineConfig) -> IngestState:
    """
    Clean the raw text and make basic decisions about how to proceed.
    Guaranteed to return state — never raises.
    """
    try:
        cleaned = _strip_html(state.raw_text)
        cleaned = _fix_encoding(cleaned)
        # Added: Clear academic metadata noise (emails, conference headers)
        cleaned = _clean_academic_noise(cleaned)
        cleaned = _normalise_whitespace(cleaned)
        cleaned = _remove_binary_artifacts(cleaned)

        state.cleaned_text      = cleaned
        state.source_char_count = len(cleaned)
        state.detected_language = _detect_language(cleaned)

        # Guard: context window overflow
        if state.source_char_count > config.context_window_chars:
            state.exceeds_context = True
            if config.chunk_on_overflow:
                state.cleaned_text = cleaned[: config.context_window_chars]
                state.add_error(
                    STAGE_NAME,
                    "context_overflow",
                    f"Source {state.source_char_count} chars exceeds window "
                    f"{config.context_window_chars}. Truncated to first chunk.",
                )
            else:
                state.add_error(
                    STAGE_NAME,
                    "context_overflow",
                    "Source exceeds context window; chunking disabled.",
                )

        # Guard: empty after cleaning
        if len(state.cleaned_text.strip()) < 50:
            state.add_error(STAGE_NAME, "empty_source", "Source is empty after cleaning.")
            state.fallback_level = FallbackLevel.RAW_EXCERPT
            logger.warning("Empty source — skipping to Level 4")
            return state

        state.mark_stage_done(STAGE_NAME)
        logger.debug(
            "Stage 0 complete: %d chars, lang=%s, overflow=%s",
            state.source_char_count,
            state.detected_language,
            state.exceeds_context,
        )

    except Exception as exc:  # noqa: BLE001
        state.add_error(STAGE_NAME, "unexpected", str(exc))
        # Best-effort: pass raw_text through as cleaned_text
        if not state.cleaned_text:
            state.cleaned_text = state.raw_text[:config.context_window_chars]

    return state


# ---------------------------------------------------------------------------
# Cleaning functions
# ---------------------------------------------------------------------------

def _strip_html(text: str) -> str:
    """Remove HTML tags and decode HTML entities."""
    # Remove script and style blocks entirely
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # Remove all remaining tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode entities (&amp; etc.)
    text = html.unescape(text)
    return text


def _fix_encoding(text: str) -> str:
    """
    Replace or normalise problem characters:
    - Non-breaking spaces → regular spaces
    - Smart quotes → straight quotes
    - Ligatures → ASCII equivalents
    - NUL bytes and control chars → stripped
    """
    replacements = {
        "\u00a0": " ",   # non-breaking space
        "\u2019": "'",   # right single quote
        "\u2018": "'",   # left single quote
        "\u201c": '"',   # left double quote
        "\u201d": '"',   # right double quote
        "\u2013": "-",   # en dash
        "\u2014": "--",  # em dash
        "\ufb01": "fi",  # fi ligature
        "\ufb02": "fl",  # fl ligature
        "\u0000": "",    # NUL byte
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)

    # Normalise unicode to NFC (composed form)
    text = unicodedata.normalize("NFC", text)

    # Strip non-printable control characters (except newline/tab)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cc" or ch in "\n\t")

    return text


def _clean_academic_noise(text: str) -> str:
    # 1. Sửa lỗi Ligatures (fi, fl, ff) thường gặp trong PDF khoa học
    replacements = {"\ufb01": "fi", "\ufb02": "fl", "\ufb00": "ff", "\ufb03": "ffi", "\ufb04": "ffl"}
    for k, v in replacements.items():
        text = text.replace(k, v)

    # 2. Xóa sạch phần "Rác" trước Abstract (Guillotine Strategy)
    gate_markers = ["Abstract", "ABSTRACT", "1 Introduction", "1. Introduction"]
    for marker in gate_markers:
        if marker in text:
            text = text[text.find(marker):]
            break

    # 3. Xóa các Reference (Trích dẫn) dính chùm - Thủ phạm của "GanuAToes"
    # Xóa các cụm (Author, 20xx) hoặc [12]
    text = re.sub(r"\([A-Z][a-zA-Z]+ et al\., \d{4}\)", " ", text)
    text = re.sub(r"\[\d+\]", " ", text)

    # 4. Xóa các Footer/Header lặp lại (Page numbers, License)
    text = re.sub(r"(?i)this work is licensed.*", "", text)
    text = re.sub(r"(?i)proceedings of.*", "", text)
    text = re.sub(r"\n\d+\n", "\n", text)  # Xóa số trang đứng lẻ loi

    return text


def _normalise_whitespace(text: str) -> str:
    """Collapse runs of spaces/tabs; preserve paragraph breaks (double newline)."""
    # Collapse horizontal whitespace on each line
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    # Collapse runs of blank lines to a single blank line
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _remove_binary_artifacts(text: str) -> str:
    """Strip hex escape sequences that indicate binary content leaked through."""
    return re.sub(r"\\x[0-9a-fA-F]{2}", "", text)


# ---------------------------------------------------------------------------
# Language detection (heuristic, no library dependency)
# ---------------------------------------------------------------------------

# Common high-frequency words per language as discriminators
_LANG_MARKERS: dict[str, list[str]] = {
    "en": ["the", "and", "of", "to", "in", "is", "that", "for"],
    "fr": ["le", "la", "les", "de", "et", "en", "un", "une"],
    "de": ["der", "die", "das", "und", "in", "ist", "für", "von"],
    "zh": ["的", "了", "是", "在", "和", "有"],
    "ja": ["の", "は", "が", "を", "に", "で"],
    "es": ["el", "la", "los", "de", "y", "en", "que", "un"],
}

def _detect_language(text: str) -> str:
    """Return ISO-639-1 code or 'unknown'. Good enough to flag non-English for logs."""
    sample = text[:500].lower()
    words  = set(re.findall(r"\b\w+\b", sample))
    scores = {
        lang: sum(1 for w in markers if w in words)
        for lang, markers in _LANG_MARKERS.items()
    }
    best_lang, best_score = max(scores.items(), key=lambda x: x[1])
    return best_lang if best_score >= 3 else "unknown"