"""
stages/stage4_validation.py — Deterministic content quality scoring.

No LLM. Validates structured_page against a checklist of rules.
Every rule either passes or fails → sets a flag + deducts from score.
Final quality_score (0–100) determines page_status in Stage 5.

Writes to state:
  validation_status, validation_flags, quality_score
"""

from __future__ import annotations

import logging
import re

import yaml

from ..config import PipelineConfig
from ..state import IngestState, ValidationStatus

logger = logging.getLogger(__name__)

STAGE_NAME = "stage4_validation"

# ---------------------------------------------------------------------------
# Scoring weights (must sum to 100)
# ---------------------------------------------------------------------------
# Each entry: (flag_name, max_points_deducted, description)
CHECKS: list[tuple[str, int, str]] = [
    ("no_yaml",           20, "YAML frontmatter missing or unparseable"),
    ("missing_title",      5, "Title is empty or 'Untitled'"),
    ("missing_summary",   15, "Summary section absent or too short"),
    ("short_summary",     10, "Summary under minimum word count"),
    ("missing_sections",  15, "Fewer than 3 required sections present"),
    ("no_links",          10, "Zero [[links]] in output"),
    ("garbage_content",   15, "Content too similar to raw source (copy-paste)"),
    ("empty_response",    10, "Page body under minimum length"),
]

REQUIRED_HEADINGS = [
    "## Summary",
    "## Key Methodology",
    "## Critical Analysis",
    "## Open Questions",
]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(state: IngestState, config: PipelineConfig) -> IngestState:
    try:
        page   = state.structured_page
        flags  = []
        score  = 100

        if not page.strip():
            # Catastrophic — no page at all
            state.validation_flags  = ["empty_response", "no_yaml", "missing_summary",
                                        "missing_sections", "no_links"]
            state.quality_score     = 0
            state.validation_status = ValidationStatus.FAILED
            return state

        # ── Run each check ────────────────────────────────────────────────
        for flag, deduction, _ in CHECKS:
            failed = _run_check(flag, page, state.raw_text, config)
            if failed:
                flags.append(flag)
                score -= deduction

        score = max(0, score)

        state.validation_flags  = flags
        state.quality_score     = score
        state.validation_status = (
            ValidationStatus.PASSED  if score >= 60 else
            ValidationStatus.PARTIAL if score >= 30 else
            ValidationStatus.FAILED
        )

        state.mark_stage_done(STAGE_NAME)
        logger.debug(
            "Stage 4: score=%d, status=%s, flags=%s",
            score, state.validation_status, flags,
        )

    except Exception as exc:  # noqa: BLE001
        state.add_error(STAGE_NAME, "unexpected", str(exc))
        state.quality_score     = 0
        state.validation_status = ValidationStatus.FAILED

    return state


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _run_check(
    flag: str,
    page: str,
    raw_text: str,
    config: PipelineConfig,
) -> bool:
    """Return True if the check FAILS (i.e. flag should be set)."""

    match flag:

        case "no_yaml":
            return not _has_valid_yaml(page)

        case "missing_title":
            title = _extract_yaml_field(page, "title")
            return not title or title.lower() in {"untitled", "unknown", ""}

        case "missing_summary":
            m = re.search(r"## Summary\s*\n(.+?)(?=\n##|\Z)", page, re.DOTALL)
            if not m:
                return True
            body = m.group(1).strip()
            return len(body) < config.min_section_body_chars

        case "short_summary":
            m = re.search(r"## Summary\s*\n(.+?)(?=\n##|\Z)", page, re.DOTALL)
            if not m:
                return True
            return len(m.group(1).split()) < config.min_summary_words

        case "missing_sections":
            found = sum(1 for h in REQUIRED_HEADINGS if h in page)
            return found < 3

        case "no_links":
            return "[[" not in page

        case "garbage_content":
            return _is_garbage(page, raw_text, config.max_garbage_similarity)

        case "empty_response":
            return len(page.strip()) < config.min_response_len

        case _:
            return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_valid_yaml(page: str) -> bool:
    """Check that the page starts with a valid YAML frontmatter block."""
    if not page.startswith("---"):
        return False
    end = page.find("\n---", 3)
    if end == -1:
        return False
    frontmatter = page[3:end].strip()
    try:
        parsed = yaml.safe_load(frontmatter)
        return isinstance(parsed, dict) and len(parsed) > 0
    except yaml.YAMLError:
        return False


def _extract_yaml_field(page: str, field: str) -> str:
    """Extract a single field from the YAML frontmatter. Returns '' on failure."""
    if not page.startswith("---"):
        return ""
    end = page.find("\n---", 3)
    if end == -1:
        return ""
    frontmatter = page[3:end]
    try:
        parsed = yaml.safe_load(frontmatter)
        return str(parsed.get(field, "")) if isinstance(parsed, dict) else ""
    except yaml.YAMLError:
        return ""


def _is_garbage(page: str, raw_text: str, threshold: float) -> bool:
    """
    Detect copy-paste: if more than `threshold` fraction of the page body
    appears verbatim in raw_text, the model didn't summarise — it copied.
    Uses an n-gram overlap heuristic (8-grams).
    """
    if not raw_text:
        return False

    # Strip the YAML block and metadata lines from page
    body_start = page.find("\n---", 3)
    body = page[body_start:] if body_start != -1 else page

    def ngrams(text: str, n: int) -> set[str]:
        words = text.lower().split()
        return {" ".join(words[i: i + n]) for i in range(len(words) - n + 1)}

    page_grams = ngrams(body, 8)
    raw_grams  = ngrams(raw_text, 8)

    if not page_grams:
        return False

    overlap = len(page_grams & raw_grams) / len(page_grams)
    return overlap > threshold