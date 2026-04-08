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


# ---------------------------------------------------------------------------
# Known-good technical term patterns
# ---------------------------------------------------------------------------

# Acronyms: 2-6 uppercase letters, optionally with digits (LSTM, BERT, CRF, SB1)
_ACRONYM = re.compile(r"^[A-Z][A-Z0-9]{1,5}(?:-[A-Z0-9]+)?$")

# Title-case phrase: each word starts uppercase, 1–4 words
_TITLECASE_PHRASE = re.compile(
    r"^[A-Z][a-z]{1,}(?:\s+[A-Z][a-z]{1,}){0,3}$"
)

# Mixed case technical terms (camelCase / PascalCase internal)
_CAMEL = re.compile(r"^[A-Z][a-z]+[A-Z][a-zA-Z]+$")


# ---------------------------------------------------------------------------
# Rejection patterns — if ANY match, the term is dropped
# ---------------------------------------------------------------------------

# Looks like an author name: "Firstname Lastname" with no other words
_AUTHOR_NAME = re.compile(
    r"^[A-Z][a-z]{1,15}\s+[A-Z][a-z]{1,15}$"
)

# Contains digits (table headers, counts, years, percentages)
_CONTAINS_DIGIT = re.compile(r"\d")

# Email / URL fragments
_EMAIL_OR_URL = re.compile(r"[@/\\.]")

# All-caps single word that is probably an abbreviation of a proper noun
# (we keep known short acronyms via _ACRONYM but reject long ones)
_LONG_ALLCAPS = re.compile(r"^[A-Z]{7,}$")

# Sentence fragments: ends with comma, starts with lowercase
_FRAGMENT = re.compile(r"^[a-z]|,$")

# Noise from table/CSV rows: multiple uppercase tokens concatenated with spaces
# e.g. "Laptops Restaurants Team Acc", "Total Category Train Test"
# Heuristic: 4+ words all starting uppercase → table row junk
_TABLE_ROW_JUNK = re.compile(
    r"^(?:[A-Z][a-zA-Z]*\s+){3,}[A-Z][a-zA-Z]*$"
)

# Sentiment label concatenations: "Positive Negative Conflict Neutral"
# Detected as: 3+ known sentiment / polarity words joined
_SENTIMENT_WORDS = {"Positive", "Negative", "Neutral", "Conflict", "Mixed",
                    "None", "Unknown", "Other"}

# Citation junk: "et al", "ibid", standalone "al"
_CITATION = re.compile(r"\bet\s+al\b|\bibid\b|\b^al$\b", re.I)

# Obsidian artifacts if model accidentally included brackets
_BRACKETS = re.compile(r"\[|\]")

# Common English connectors that shouldn't be terms
_CONNECTOR_TERMS = {
    "the", "and", "or", "of", "in", "on", "to", "for", "with",
    "by", "at", "from", "as", "is", "are", "a", "an",
    "this", "that", "these", "those", "we", "our", "their",
    "figure", "table", "section", "paper", "work", "approach",
    "method", "model", "system", "result", "results", "data",
    "based", "using", "via", "new", "proposed", "used",
}


# ---------------------------------------------------------------------------
# Allowlist: terms that look like junk by heuristic but are genuinely technical
# ---------------------------------------------------------------------------

_ALLOWLIST = {
    "F1 Score", "F-measure", "T5", "GPT-4", "GPT-3", "BERT", "RoBERTa",
    "XLNet", "T-SNE", "K-Means", "K-NN", "K-Fold",
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
      4. Deduplicate (case-insensitive, keep first occurrence).
      5. Sort by length descending (longer = more specific = more useful).

    Args:
        raw_lines: list of strings from LLM output, one term per line.

    Returns:
        Cleaned list of technical term strings, max 12.
    """
    seen_lower: set[str] = set()
    cleaned: list[str] = []

    for raw in raw_lines:
        term = _normalise(raw)
        if not term:
            continue

        # Allowlist bypasses all filters
        if term in _ALLOWLIST:
            if term.lower() not in seen_lower:
                seen_lower.add(term.lower())
                cleaned.append(term)
            continue

        if _should_reject(term):
            continue

        # Deduplicate
        lower = term.lower()
        if lower in seen_lower:
            continue
        seen_lower.add(lower)
        cleaned.append(term)

    # Sort: longer terms first (more specific), then alphabetically
    cleaned.sort(key=lambda t: (-len(t.split()), t))
    return cleaned[:12]


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

    # Too short or empty
    if len(term) < 2:
        return True

    # Too long (>5 words = almost certainly a phrase fragment or table row)
    words = term.split()
    if len(words) > 5:
        return True

    # Single lowercase word = common English, not a technical concept
    if len(words) == 1 and term[0].islower():
        return True

    # Known connector/stopword as entire term
    if term.lower() in _CONNECTOR_TERMS:
        return True

    # Looks like "Firstname Lastname" author name
    if _AUTHOR_NAME.match(term):
        return True

    # Contains digits unless it's a known allowlist item
    if _CONTAINS_DIGIT.search(term):
        # Allow version numbers in known patterns: BERT-Large, GPT-2
        if not re.match(r"^[A-Z][a-zA-Z]+-\d$", term):
            return True

    # Email or URL fragment
    if _EMAIL_OR_URL.search(term):
        return True

    # Very long all-caps word (not a real acronym)
    if _LONG_ALLCAPS.match(term):
        return True

    # Fragment (starts lowercase, or ends with comma)
    if _FRAGMENT.search(term):
        return True

    # Table row junk: 4+ capitalised words strung together
    if _TABLE_ROW_JUNK.match(term):
        return True

    # Sentiment label concatenations
    term_words_set = set(words)
    sentiment_overlap = term_words_set & _SENTIMENT_WORDS
    if len(sentiment_overlap) >= 2:
        return True

    # Citation junk
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