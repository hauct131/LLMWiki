"""
clean_terms.py — Deterministic post-processor for P6 (technical term extraction).

This runs AFTER the LLM returns its term list and BEFORE terms are written
to state.confirmed_links.  It is the safety net that catches everything the
LLM was told not to do but did anyway.

Public API:
    clean_terms(raw_lines: list[str]) -> list[str]

Design goals:
  - Pure function. No LLM calls. No side effects.
  - Every filter rule is explicit and testable.
  - Conservative: when in doubt, drop the term (stubs are cheaper than junk).
  - Works for the worst-case weak model (Phi-3.5 / 3B).
"""

from __future__ import annotations

import re
from typing import Sequence
from .concept_normalizer import normalize_concept

# ---------------------------------------------------------------------------
# Known-good technical term patterns (kept for reference, used implicitly)
# ---------------------------------------------------------------------------

# Contains digits (table headers, counts, years, percentages)
_CONTAINS_DIGIT = re.compile(r"\d")

# Email / URL fragments
_EMAIL_OR_URL = re.compile(r"[@/\\.]")

# All-caps 7+ chars = not a real acronym
_LONG_ALLCAPS = re.compile(r"^[A-Z]{7,}$")

# Fragment: starts lowercase or ends with comma
_FRAGMENT = re.compile(r"^[a-z]|,$")

# 4+ capitalized words = table row junk
_TABLE_ROW_JUNK = re.compile(r"^(?:[A-Z][a-zA-Z]*\s+){3,}[A-Z][a-zA-Z]*$")

# Sentiment label concatenations
_SENTIMENT_WORDS = {"Positive", "Negative", "Neutral", "Conflict", "Mixed",
                    "None", "Unknown", "Other"}

# Citation junk
_CITATION = re.compile(r"\bet\s+al\b|\bibid\b", re.I)

# Obsidian link brackets
_BRACKETS = re.compile(r"\[|\]")

# Common English connectors that should never be wiki concepts
_CONNECTOR_TERMS = {
    "the", "and", "or", "of", "in", "on", "to", "for", "with",
    "by", "at", "from", "as", "is", "are", "a", "an",
    "this", "that", "these", "those", "we", "our", "their",
    "figure", "table", "section", "paper", "work", "approach",
    "method", "model", "system", "result", "results", "data",
    "based", "using", "via", "new", "proposed", "used",
}


# ---------------------------------------------------------------------------
# Common English/Asian first names — used to detect "Firstname Lastname" patterns
# WITHOUT catching real technical 2-word terms like "Sentiment Analysis"
# ---------------------------------------------------------------------------
_FIRST_NAMES = {
    "john", "james", "robert", "michael", "william", "david", "richard",
    "joseph", "thomas", "charles", "christopher", "daniel", "matthew",
    "mark", "donald", "paul", "steven", "andrew", "kenneth", "george",
    "mary", "patricia", "jennifer", "linda", "barbara", "elizabeth",
    "susan", "jessica", "sarah", "karen", "lisa", "nancy", "betty",
    "alina", "vasileios", "fabrizio", "alessandro", "maria", "anna",
    "peter", "alexander", "kevin", "brian", "wei", "yang", "yong",
    "ming", "hong", "lin", "jun", "hai", "bo", "lei", "pontiki",
    "manning", "ganu", "pang", "liu", "wang", "zhang", "chen",
}

# Section-header words — term starting with these is reference/bibliography junk
_SECTION_PREFIXES = {
    "references", "bibliography", "appendix", "introduction", "conclusion",
    "abstract", "acknowledgment", "acknowledgements", "footnote",
    "figure", "equation", "algorithm", "section", "chapter",
}

# Generic academic venue terms — never useful as wiki concepts
_GENERIC_ACADEMIC = {
    "international conference", "workshop proceedings", "annual meeting",
    "proceedings of", "journal of", "transactions on", "advances in",
    "language resources", "exploring attitude", "knowledge management",
    "information systems", "provincia autonoma", "overview paper",
    # Generic method/evaluation terms that are too vague
    "learning methods", "training procedure", "database assessment",
    "large datasets", "public datasets", "multiple datasets",
    "standard datasets", "state of the art", "state of the art performance",
    "performance maintenance", "source code release", "code availability",
    "experimental results", "evaluation metrics", "baseline methods",
    "training time efficiency", "real time performance",
    "taxonomy of sr techniques", "super resolution tasks",
    "sentiment analysis tasks", "semantic similarity tasks",
    "entity recognition tasks", "inference speedup techniques",
    "deep learning techniques", "gan based methods",
    "transformer and bert methods",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def clean_terms(raw_lines: Sequence[str]) -> list[str]:
    """
    Accept a list of raw term strings (one per line from the LLM) and return
    a cleaned, deduplicated list of valid technical terms.

    Steps:
      1. Strip whitespace, bullets, numbers, brackets.
      2. Apply rejection filters (author names, junk, digits, etc.).
      3. Validate shape: term must look like a real technical concept.
      4. Normalize using synonym dictionary (map aliases to canonical name).
      5. Deduplicate (case-insensitive, keep first occurrence).
      6. Sort by length descending (longer = more specific = more useful).

    Args:
        raw_lines: list of strings from LLM output, one term per line.

    Returns:
        Cleaned list of technical term strings, max 12.
    """
    seen_lower: set[str] = set()
    filtered: list[str] = []

    # Step 1-3: filtering and basic case-insensitive dedup
    for raw in raw_lines:
        term = _normalise(raw)
        if not term:
            continue

        # Allowlist bypasses all filters


        if _should_reject(term):
            continue

        # Deduplicate (case-insensitive)
        lower = term.lower()
        if lower in seen_lower:
            continue
        seen_lower.add(lower)
        filtered.append(term)

    # Step 4: Normalize each term to canonical name using synonym dictionary
    # (e.g., "aspect extraction" -> "Aspect Term Extraction")
    normalized = [normalize_concept(term) for term in filtered]

    # Step 5: Deduplicate by canonical name (keep first occurrence)
    result = []
    seen_norm = set()
    for norm in normalized:
        if norm not in seen_norm:
            seen_norm.add(norm)
            result.append(norm)

    # Step 6: Sort as before
    result.sort(key=lambda t: (-len(t.split()), t))
    return result[:12]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalise(raw: str) -> str:
    """Strip bullets, numbers, markdown, and extra whitespace."""
    term = raw.strip()

    # Remove Obsidian link brackets if model included them
    term = _BRACKETS.sub("", term)

    # Remove leading bullets: "- ", "* ", "• "
    term = re.sub(r"^[-*•]\s+", "", term)

    # Remove leading numbers: "1. ", "12) "
    term = re.sub(r"^\d+[.)]\s*", "", term)

    # Remove trailing punctuation
    term = term.rstrip(".,;:()[]")

    # Collapse internal whitespace
    term = re.sub(r"\s{2,}", " ", term).strip()

    return term


def _should_reject(term: str) -> bool:
    """Return True if the term should be discarded."""
    if len(term) < 2:
        return True

    words = term.split()

    # Too long
    if len(words) > 5:
        return True

    # Single lowercase word
    if len(words) == 1 and term[0].islower():
        return True

    # Connector/stopword
    if term.lower() in _CONNECTOR_TERMS:
        return True

    # Generic academic venue term
    if term.lower() in _GENERIC_ACADEMIC:
        return True

    # First word is a section-header prefix → bibliography junk
    # e.g. "References Alina Andreevskaia", "Introduction Opinion Mining"
    if words[0].lower() in _SECTION_PREFIXES:
        return True

    # BUG FIX: Old code used _AUTHOR_NAME = ^[A-Z][a-z]+\s+[A-Z][a-z]+$
    # which caught EVERY 2-word Title Case term including "Sentiment Analysis".
    # New approach: only reject if first word is a known first name.
    if len(words) >= 2 and words[0].lower() in _FIRST_NAMES:
        return True

    # 3-word "SectionPrefix Firstname Lastname"
    if len(words) == 3:
        if words[0].lower() in _SECTION_PREFIXES and words[1].lower() in _FIRST_NAMES:
            return True

    # Contains digits — allow BERT-Large style
    if _CONTAINS_DIGIT.search(term):
        if not re.match(r"^[A-Z][a-zA-Z]+-\d[A-Za-z]*$", term):
            return True

    if _EMAIL_OR_URL.search(term):
        return True

    if _LONG_ALLCAPS.match(term):
        return True

    # Starts lowercase or ends with comma
    if _FRAGMENT.search(term):
        return True

    # 4+ capitalized words = table-row junk
    if _TABLE_ROW_JUNK.match(term):
        return True

    # >=2 sentiment polarity words in one term
    if len(set(words) & _SENTIMENT_WORDS) >= 2:
        return True

    if _CITATION.search(term):
        return True

    return False


# ---------------------------------------------------------------------------
# Convenience: split-then-clean for when the model outputs multi-word junk
# on a single line (e.g. "Aspect Extraction Sentiment Analysis")
# ---------------------------------------------------------------------------

def split_and_clean(raw_line: str, known_concepts: set[str] | None = None) -> list[str]:
    """
    When a single line contains multiple valid concepts concatenated,
    attempt to split it into individual concepts.

    Strategy:
      1. Try splitting on "/" or "," first.
      2. If result is 1 item and it's >4 words, try a bigram/trigram sliding
         window against known_concepts (if provided).
      3. If still no split, apply _should_reject to the whole string.

    This is a best-effort function — prefer dropping to hallucinating.

    Args:
        raw_line: one raw line from LLM output.
        known_concepts: optional set of known valid concepts for matching.

    Returns:
        List of 1+ clean terms (may be empty if everything rejects).
    """
    # First try delimiter split
    for delimiter in ["/", ",", ";", " | "]:
        if delimiter in raw_line:
            parts = [p.strip() for p in raw_line.split(delimiter) if p.strip()]
            if len(parts) >= 2:
                return clean_terms(parts)

    # Single item — try bigram/trigram match against known concepts
    if known_concepts:
        words = raw_line.strip().split()
        candidates = []
        i = 0
        while i < len(words):
            matched = False
            for n in (3, 2):  # try trigrams first, then bigrams
                phrase = " ".join(words[i: i + n])
                if phrase in known_concepts:
                    candidates.append(phrase)
                    i += n
                    matched = True
                    break
            if not matched:
                i += 1
        if candidates:
            return clean_terms(candidates)

    # Fallback: treat as single term
    return clean_terms([raw_line])

# ============================================================================
# Improved version with canonicalization to avoid duplicates like
# "Natural Language Processing" vs "natural-language-processing"
# ============================================================================

def _canonicalize(term: str) -> str:
    """
    Convert a term to a canonical form for deduplication.
    - Lowercase
    - Replace spaces, underscores, hyphens with a single space
    - Remove punctuation (except letters and spaces)
    - Collapse multiple spaces
    """
    term = term.lower()
    term = re.sub(r'[-_/]', ' ', term)          # replace separators with space
    term = re.sub(r'[^\w\s]', '', term)        # remove punctuation
    term = re.sub(r'\s+', ' ', term).strip()   # collapse spaces
    return term

def clean_terms_deduplicated(raw_lines: Sequence[str]) -> list[str]:
    """
    Same as clean_terms() but with aggressive canonicalization deduplication.
    Use this instead of clean_terms() to avoid duplicate concepts like
    "Natural Language Processing" and "natural-language-processing".
    """
    terms = clean_terms(raw_lines)             # get filtered list
    canonical_map = {}
    for term in terms:
        canon = _canonicalize(term)
        if canon not in canonical_map:
            canonical_map[canon] = term
    # Preserve order of first appearance
    result = []
    seen_canon = set()
    for term in terms:
        canon = _canonicalize(term)
        if canon not in seen_canon:
            seen_canon.add(canon)
            result.append(term)
    return result