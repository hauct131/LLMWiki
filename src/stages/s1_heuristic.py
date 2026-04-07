"""
stages/stage1_heuristic.py — Rule-based extraction from cleaned text.

No LLM. Produces best-effort values that become the fallback for every
downstream LLM micro-task. If the LLM fails, stage 1 values fill the gap.

Writes to state:
  extracted_title, extracted_sections, extracted_metadata, candidate_links
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from ..config import PipelineConfig
from ..state import IngestState

logger = logging.getLogger(__name__)

STAGE_NAME = "stage1_heuristic"

# ---------------------------------------------------------------------------
# Section header patterns (covers arXiv, NeurIPS, ICLR, general markdown)
# ---------------------------------------------------------------------------
SECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("abstract",      re.compile(r"(?i)^#+\s*abstract|^abstract\s*\n", re.M)),
    ("introduction",  re.compile(r"(?i)^#+\s*(?:\d+\.?\s*)?introduction", re.M)),
    ("methodology",   re.compile(r"(?i)^#+\s*(?:\d+\.?\s*)?(?:method(?:ology)?|approach|model|architecture)", re.M)),
    ("experiments",   re.compile(r"(?i)^#+\s*(?:\d+\.?\s*)?(?:experiments?|evaluation|results?|benchmarks?)", re.M)),
    ("conclusion",    re.compile(r"(?i)^#+\s*(?:\d+\.?\s*)?(?:conclusion|discussion|summary)", re.M)),
    ("related_work",  re.compile(r"(?i)^#+\s*(?:\d+\.?\s*)?related work", re.M)),
    ("limitations",   re.compile(r"(?i)^#+\s*(?:\d+\.?\s*)?(?:limitations?|future work)", re.M)),
]

# Stopwords for [[link]] candidate filtering
LINK_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "in", "on", "to", "for",
    "with", "by", "at", "from", "as", "is", "are", "was", "were",
    "this", "that", "these", "those", "it", "its", "be", "been",
    "we", "our", "their", "they", "he", "she", "figure", "table",
    "section", "paper", "work", "model", "approach", "method",
}

# Patterns that look like proper technical terms
TECHNICAL_TERM_PATTERN = re.compile(
    r"\b([A-Z][a-zA-Z]{2,}(?:[A-Z][a-z]+)+|[A-Z]{2,}(?:-[A-Z0-9]+)?)\b"
)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(state: IngestState, config: PipelineConfig) -> IngestState:
    """
    Extract all we can from cleaned_text with zero LLM calls.
    Partial failure is fine — missing fields stay empty, not an abort.
    """
    try:
        text = state.cleaned_text

        state.extracted_title    = _extract_title(text, state.source_path)
        state.extracted_sections = _extract_sections(text)
        state.extracted_metadata = _extract_metadata(
            text, state.extracted_sections, state.ingest_date
        )
        state.candidate_links    = _extract_candidate_links(text)

        state.mark_stage_done(STAGE_NAME)
        logger.debug(
            "Stage 1: title=%r, sections=%s, candidates=%d",
            state.extracted_title,
            list(state.extracted_sections.keys()),
            len(state.candidate_links),
        )

    except Exception as exc:  # noqa: BLE001
        state.add_error(STAGE_NAME, "unexpected", str(exc))

    return state


# ---------------------------------------------------------------------------
# Title extraction
# ---------------------------------------------------------------------------

def _extract_title(text: str, source_path: str = "") -> str:
    # 1. First markdown H1
    m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    if m:
        return m.group(1).strip()

    # 2. "Title:" label
    m = re.search(r"(?i)^Title:\s*(.+)$", text, re.MULTILINE)
    if m:
        return m.group(1).strip()

    # 3. First non-empty line that looks like a title (< 20 words, no period)
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        words = line.split()
        if 3 <= len(words) <= 20 and not line.endswith("."):
            return line

    # 4. Filename
    if source_path:
        import os
        stem = os.path.splitext(os.path.basename(source_path))[0]
        return stem.replace("-", " ").replace("_", " ").title()

    return "Untitled"


# ---------------------------------------------------------------------------
# Section extraction
# ---------------------------------------------------------------------------

def _extract_sections(text: str) -> dict[str, str]:
    """
    Return dict mapping section name → section body text.
    Uses the patterns in SECTION_PATTERNS to find boundaries.
    Body is trimmed to first 800 chars (enough for micro-prompts).
    """
    sections: dict[str, str] = {}

    # Collect all match positions
    hits: list[tuple[str, int]] = []
    for name, pattern in SECTION_PATTERNS:
        m = pattern.search(text)
        if m:
            hits.append((name, m.start()))

    # Sort by position so we can slice between them
    hits.sort(key=lambda x: x[1])

    for i, (name, start) in enumerate(hits):
        end = hits[i + 1][1] if i + 1 < len(hits) else len(text)
        # Skip the heading line itself
        body_start = text.find("\n", start)
        if body_start == -1 or body_start >= end:
            continue
        body = text[body_start:end].strip()
        if len(body) >= 30:
            sections[name] = body[:800]

    # Always try to get a plain-text "abstract" even if not labelled as a section
    if "abstract" not in sections:
        abstract = _extract_abstract_heuristic(text)
        if abstract:
            sections["abstract"] = abstract

    return sections


def _extract_abstract_heuristic(text: str) -> str:
    """
    Look for text between 'Abstract' keyword and the next section.
    Falls back to the first meaningful paragraph.
    """
    m = re.search(r"(?i)\bAbstract\b[:\s]*\n(.+?)(?=\n\n|\n#)", text, re.DOTALL)
    if m:
        return m.group(1).strip()[:600]

    # First paragraph of at least 3 sentences
    paragraphs = re.split(r"\n\n+", text)
    for para in paragraphs:
        sentences = re.split(r"(?<=[.!?])\s+", para.strip())
        if len(sentences) >= 3 and len(para.split()) >= 20:
            return para.strip()[:600]

    return ""


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

def _extract_metadata(
    text: str,
    sections: dict[str, str],
    ingest_date: str,
) -> dict[str, str]:
    meta: dict[str, str] = {
        "author":       _extract_author(text),
        "year":         _extract_year(text),
        "source_url":   _extract_url(text),
        "date_ingested": ingest_date,
        "importance":   "3",   # default; overwritten by P7
    }
    return meta


def _extract_author(text: str) -> str:
    # "Author(s):" label
    m = re.search(r"(?i)Authors?:\s*([A-Z][^\n]{3,80})", text)
    if m:
        return m.group(1).strip()

    # "Name Surname, Name Surname" pattern after "by" keyword
    m = re.search(
        r"(?i)(?:by|written by|submitted by)\s+([A-Z][a-z]+ [A-Z][a-z]+(?:,\s*[A-Z][a-z]+ [A-Z][a-z]+)*)",
        text,
    )
    if m:
        return m.group(1).strip()

    # arXiv byline: lines of "Firstname Lastname" after the title
    lines = text.splitlines()[:20]
    name_pattern = re.compile(r"^([A-Z][a-z]+ [A-Z][a-z]+(?:,\s*[A-Z][a-z]+ [A-Z][a-z]+)*)$")
    for line in lines:
        if name_pattern.match(line.strip()):
            return line.strip()

    return "Unknown"


def _extract_year(text: str) -> str:
    import datetime
    # First 4-digit year in plausible range
    m = re.search(r"\b(20(?:1[0-9]|2[0-9]))\b", text[:1000])
    if m:
        return m.group(1)
    return str(datetime.date.today().year)


def _extract_url(text: str) -> str:
    m = re.search(r"https?://[^\s\"'>]{10,}", text)
    return m.group(0) if m else ""


# ---------------------------------------------------------------------------
# Candidate [[link]] extraction
# ---------------------------------------------------------------------------

def _extract_candidate_links(text: str) -> list[str]:
    """
    Extract capitalised multi-word technical phrases as link candidates.
    Filtered against stopwords. Returns up to 15 terms.
    """
    # CamelCase / acronyms
    raw_terms: set[str] = set()
    for m in TECHNICAL_TERM_PATTERN.finditer(text):
        term = m.group(0)
        if len(term) >= 3 and term.lower() not in LINK_STOPWORDS:
            raw_terms.add(term)

    # Capitalised bigrams / trigrams (e.g. "Attention Mechanism")
    capitalized_phrase = re.compile(
        r"\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){1,3})\b"
    )
    for m in capitalized_phrase.finditer(text):
        phrase = m.group(0)
        words  = phrase.lower().split()
        if not any(w in LINK_STOPWORDS for w in words):
            raw_terms.add(phrase)

    # Deduplicate, sort, limit
    sorted_terms = sorted(raw_terms, key=lambda t: (-len(t), t))
    return sorted_terms[:15]