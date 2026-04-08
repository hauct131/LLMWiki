"""
prompts.py — All micro-prompt contracts for the wiki ingest system.

Each PromptContract bundles:
  - system:    fixed system message
  - build():   constructs the user prompt from inputs
  - validate(): deterministic check of model output — returns True/False
  - extract(): parses validated output into the target state field type
  - fallback(): produces a safe value from heuristic state when LLM fails

Nothing in this file calls the LLM. That's prompt_runner.py's job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from ..utils.clean_terms import clean_terms

# ---------------------------------------------------------------------------
# Base contract type
# ---------------------------------------------------------------------------

@dataclass
class PromptContract:
    name:      str
    system:    str
    build:     Callable[..., str]   # (...) → user prompt string
    validate:  Callable[[str], bool]
    extract:   Callable[[str], Any]
    fallback:  Callable[..., Any]   # (...) → safe value


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sentence_count(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s])

def _word_count(text: str) -> int:
    return len(text.split())

def _bullet_lines(text: str) -> list[str]:
    return [l.strip() for l in text.splitlines() if l.strip().startswith("- ")]

def _strip_md(text: str) -> str:
    return re.sub(r"[#`*_]", "", text).strip()

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "in", "on", "to", "for",
    "with", "by", "at", "from", "as", "is", "are", "was", "were",
    "this", "that", "these", "those", "it", "its", "be", "been",
}


# ============================================================================
# P0 — Extract Title
# ============================================================================

def _p0_build(text: str) -> str:
    return (
        "Extract the title of this research paper. "
        "Output the title only, one line, no quotes.\n\n"
        f"TEXT:\n{text[:300]}"
    )

def _p0_validate(out: str) -> bool:
    out = out.strip()
    if not out or "\n" in out:
        return False
    words = out.split()
    return 2 <= len(words) <= 25

def _p0_extract(out: str) -> str:
    return _strip_md(out.strip().splitlines()[0])

def _p0_fallback(source_path: str = "", cleaned_text: str = "") -> str:
    # Try first H1 in text
    m = re.search(r"^#\s+(.+)$", cleaned_text, re.MULTILINE)
    if m:
        return m.group(1).strip()
    # Try first line
    first = cleaned_text.strip().splitlines()[0] if cleaned_text.strip() else ""
    if 3 <= len(first.split()) <= 20:
        return first
    # Fall back to filename
    import os
    stem = os.path.splitext(os.path.basename(source_path))[0]
    return stem.replace("-", " ").replace("_", " ").title() or "Untitled"

P0_TITLE = PromptContract(
    name="P0_title",
    system="You are a text extraction tool. Output only the requested field. No explanation.",
    build=_p0_build,
    validate=_p0_validate,
    extract=_p0_extract,
    fallback=_p0_fallback,
)


# ============================================================================
# P0.5 — Document Classifier (New Stage)
# ============================================================================

def _p0_5_build(text_snippet: str) -> str:
    return (
        "Analyze the following text and determine its category.\n"
        "Categories:\n"
        "- BENCHMARK_PAPER: Shared tasks, competitions, evaluation campaigns, dataset papers "
        "(e.g. SemEval, CoNLL, GLUE, ImageNet). Has subtasks, leaderboards, participant teams.\n"
        "- SCIENTIFIC_PAPER: Has Abstract, Intro, References, and academic affiliations. "
        "Proposes a method or model.\n"
        "- TECHNICAL_DOCUMENTATION: Manuals, API docs, or READMEs.\n"
        "- NEWS_ARTICLE: Journalistic style, no formal academic structure.\n"
        "- OTHER: General text.\n\n"
        "Format: CATEGORY | CONFIDENCE_SCORE\n"
        f"TEXT: {text_snippet}"
    )

def _p0_5_validate(out: str) -> bool:
    out = out.strip()
    if "|" not in out:
        return False
    valid_cats = ["BENCHMARK_PAPER", "SCIENTIFIC_PAPER", "TECHNICAL_DOCUMENTATION",
                  "NEWS_ARTICLE", "OTHER"]
    return any(cat in out for cat in valid_cats)

def _p0_5_extract(out: str) -> dict[str, str]:
    parts = out.split("|", 1)
    return {
        "category": parts[0].strip(),
        "confidence": parts[1].strip() if len(parts) > 1 else "0.0"
    }

def _p0_5_fallback(**_) -> dict[str, str]:
    return {"category": "OTHER", "confidence": "0.0"}

P0_DOC_TYPE = PromptContract(
    name="P0_doc_type",
    system="You are a Document Architect. Classify the document type accurately.",
    build=_p0_5_build,
    validate=_p0_5_validate,
    extract=_p0_5_extract,
    fallback=_p0_5_fallback,
)


# ============================================================================
# P1 — Extract Authors + Date
# ============================================================================

_P1_FORMAT = "AUTHORS: name1, name2\nYEAR: YYYY"

def _p1_build(text: str) -> str:
    return (
        "Extract the author names and publication year.\n\n"
        f"Output in this exact format:\n{_P1_FORMAT}\n\n"
        "If not found, write UNKNOWN for that field.\n\n"
        f"TEXT:\n{text[:500]}"
    )

def _p1_validate(out: str) -> bool:
    return "AUTHORS:" in out and "YEAR:" in out

def _p1_extract(out: str) -> dict[str, str]:
    result = {"author": "Unknown", "year": "Unknown"}
    for line in out.splitlines():
        if line.startswith("AUTHORS:"):
            val = line.split("AUTHORS:", 1)[1].strip()
            if val and val.upper() != "UNKNOWN":
                result["author"] = val
        if line.startswith("YEAR:"):
            val = line.split("YEAR:", 1)[1].strip()
            if re.match(r"^\d{4}$", val):
                result["year"] = val
    return result

def _p1_fallback(cleaned_text: str = "") -> dict[str, str]:
    import datetime
    author = "Unknown"
    year   = str(datetime.date.today().year)
    # Author: look for "Author:" label or capitalized name clusters
    m = re.search(r"(?:Authors?|By):\s*([A-Z][a-z]+ [A-Z][a-z]+(?:,\s*[A-Z][a-z]+ [A-Z][a-z]+)*)", cleaned_text)
    if m:
        author = m.group(1)
    # Year
    m = re.search(r"\b(20\d{2})\b", cleaned_text)
    if m:
        year = m.group(1)
    return {"author": author, "year": year}

P1_AUTHORS = PromptContract(
    name="P1_authors",
    system="You are a text extraction tool. Output only the requested field. No explanation.",
    build=_p1_build,
    validate=_p1_validate,
    extract=_p1_extract,
    fallback=_p1_fallback,
)


# ============================================================================
# P2 — Write Summary
# ============================================================================

def _p2_build(text: str, n_sentences: int = 3) -> str:
    return (
        f"Summarize this research in exactly {n_sentences} sentences.\n"
        "Sentence 1: What problem does it solve?\n"
        "Sentence 2: What is the core method?\n"
        "Sentence 3: What is the main result?\n\n"
        "Do not start with 'This paper'. No labels. No bullets.\n\n"
        f"TEXT:\n{text[:1500]}"
    )

def _p2_validate(out: str) -> bool:
    out = out.strip()
    if not out or out.startswith("##") or "- " in out[:5]:
        return False
    sentences = re.split(r"(?<=[.!?])\s+", out)
    sentences = [s for s in sentences if s.strip()]
    return 2 <= len(sentences) <= 6 and 20 <= _word_count(out) <= 250

def _p2_extract(out: str) -> str:
    return out.strip()

def _p2_fallback(cleaned_text: str = "", extracted_sections: dict = None) -> str:
    sections = extracted_sections or {}
    source = sections.get("abstract") or sections.get("introduction") or cleaned_text
    sentences = re.split(r"(?<=[.!?])\s+", source.strip())
    sentences = [s.strip() for s in sentences if len(s.split()) >= 5]
    return " ".join(sentences[:3]) or "Summary unavailable — needs manual review."

P2_SUMMARY = PromptContract(
    name="P2_summary",
    system=(
        "You are a research summarizer. Be concise and factual. No filler phrases. "
        "Never start with 'This paper'. Never say 'The authors'. "
        "Output only the summary. No labels, no headers."
    ),
    build=_p2_build,
    validate=_p2_validate,
    extract=_p2_extract,
    fallback=_p2_fallback,
)


# ============================================================================
# P3 — List Key Methods
# ============================================================================

def _p3_build(text: str, n_methods: int = 3) -> str:
    return (
        f"Identify the core sub-tasks or techniques in this paper.\n"
        "STRICT FORMAT: - Task Name: Brief description.\n"
        "Example: - SB1 Aspect Extraction: Identifying terms like 'service'.\n"
        f"TEXT:\n{text[:4000]}" # Đưa cho AI đoạn text đã sạch ở trang đầu
    )

def _p3_validate(out: str) -> bool:
    bullets = _bullet_lines(out)
    if len(bullets) < 2:
        return False
    if any(len(b.split()) > 60 for b in bullets):
        return False
    return all(": " in b for b in bullets)

def _p3_extract(out: str) -> list[str]:
    return _bullet_lines(out)

def _p3_fallback(extracted_sections: dict = None, cleaned_text: str = "") -> list[str]:
    sections = extracted_sections or {}
    source = sections.get("methodology") or sections.get("method") or cleaned_text
    # Grab existing bullets from source
    bullets = [l.strip() for l in source.splitlines()
               if re.match(r"^[-*•]\s+", l) or re.match(r"^\d+\.\s+", l)]
    if bullets:
        return [f"- {b.lstrip('-*•0123456789. ')}" for b in bullets[:5]]
    # Sentence-based fallback
    sentences = re.split(r"(?<=[.!?])\s+", source.strip())
    return [f"- {s.strip()}" for s in sentences[:3] if len(s.split()) >= 5]

P3_KEY_METHODS = PromptContract(
    name="P3_key_methods",
    system="You are a technical extraction tool. Output only bullet points. No intro sentence.",
    build=_p3_build,
    validate=_p3_validate,
    extract=_p3_extract,
    fallback=_p3_fallback,
)


# ============================================================================
# P4 — Strengths and Weaknesses
# ============================================================================

def _p4_build(text: str) -> str:
    return (
        "Analyze this research. Output exactly this format:\n\n"
        "STRENGTHS:\n- strength one\n- strength two\n\n"
        "WEAKNESSES:\n- weakness one\n- weakness two\n\n"
        f"TEXT:\n{text[:2000]}"
    )

def _p4_validate(out: str) -> bool:
    has_s = "STRENGTHS:" in out
    has_w = "WEAKNESSES:" in out
    if not (has_s and has_w):
        return False
    # At least one bullet under each
    parts = re.split(r"WEAKNESSES:", out, maxsplit=1)
    strengths_block = parts[0].split("STRENGTHS:", 1)[-1]
    weaknesses_block = parts[1] if len(parts) > 1 else ""
    return bool(_bullet_lines(strengths_block)) and bool(_bullet_lines(weaknesses_block))

def _p4_extract(out: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {"strengths": [], "weaknesses": [], "assumptions": []}
    current = None
    for line in out.splitlines():
        l = line.strip()
        if l == "STRENGTHS:":
            current = "strengths"
        elif l == "WEAKNESSES:":
            current = "weaknesses"
        elif l.startswith("- ") and current:
            result[current].append(l)
    return result

def _p4_extract_assumptions(out: str) -> list[str]:
    # Placeholder if P4 is extended to Assumptions
    return []

def _p4_fallback(**_) -> dict[str, list[str]]:
    return {
        "strengths":   ["- Addresses a meaningful problem in the field."],
        "weaknesses":  ["- Limitations not fully assessed — needs manual review."],
        "assumptions": [],
    }

P4_ANALYSIS = PromptContract(
    name="P4_analysis",
    system="You are a critical analysis tool. Be specific. No filler. Output only what is asked.",
    build=_p4_build,
    validate=_p4_validate,
    extract=_p4_extract,
    fallback=_p4_fallback,
)


# ============================================================================
# P5 — Open Questions
# ============================================================================

_GENERIC_QUESTIONS = [
    "- [ ] What are the computational costs of this approach at scale?",
    "- [ ] How does this generalise beyond the tested benchmarks?",
    "- [ ] What failure cases are not addressed in this work?",
]

def _p5_build(text: str) -> str:
    return (
        "List 3 open questions or unresolved issues raised by this research.\n\n"
        "Format:\n- [ ] Question here?\n\n"
        "No explanation. Just the questions.\n\n"
        f"TEXT:\n{text}"
    )

def _p5_validate(out: str) -> bool:
    pattern = re.compile(r"^- \[ \] .+\?$")
    valid = [l.strip() for l in out.splitlines() if pattern.match(l.strip())]
    return len(valid) >= 2

def _p5_extract(out: str) -> list[str]:
    pattern = re.compile(r"^- \[ \] .+\?$")
    return [l.strip() for l in out.splitlines() if pattern.match(l.strip())]

def _p5_fallback(**_) -> list[str]:
    return list(_GENERIC_QUESTIONS)

P5_QUESTIONS = PromptContract(
    name="P5_questions",
    system="You are a research gap detector. Output only questions. No explanation.",
    build=_p5_build,
    validate=_p5_validate,
    extract=_p5_extract,
    fallback=_p5_fallback,
)


# ============================================================================
# P6 — Extract Technical Terms (for [[links]])
# ============================================================================

def _p6_build(text: str, n_terms: int = 7) -> str:
    return (
        "Extract 5-10 technical concepts from this research text for a wiki.\n\n"
        "RULES — read carefully:\n"
        "✓ INCLUDE: method names, model architectures, algorithm names, dataset names, "
        "evaluation metrics, NLP/ML tasks (e.g. 'Aspect Term Extraction', 'CRF', 'F1 Score').\n"
        "✗ EXCLUDE author names (e.g. 'Pontiki', 'Manning', 'Ganu').\n"
        "✗ EXCLUDE statistics or counts (e.g. '163 submissions', '32 teams', '3041 sentences').\n"
        "✗ EXCLUDE sentiment labels (e.g. 'Positive Negative Conflict Neutral').\n"
        "✗ EXCLUDE table headers or column names (e.g. 'Train Test Acc', 'Category Total').\n"
        "✗ EXCLUDE institution names or affiliations.\n\n"
        "OUTPUT FORMAT: one concept per line, no bullets, no numbers.\n"
        "Each concept: 1 to 3 words maximum.\n\n"
        "EXAMPLES of correct output:\n"
        "Conditional Random Fields\n"
        "Aspect Term Extraction\n"
        "Sentiment Analysis\n"
        "SemEval\n"
        "Named Entity Recognition\n\n"
        f"TEXT:\n{text[:3000]}"
    )

def _p6_validate(out: str) -> bool:
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    if not (3 <= len(lines) <= 20):
        return False
    valid = 0
    for l in lines:
        # Reject if starts with bullet or number
        if l.startswith("- ") or re.match(r"^\d+\.", l):
            continue
        # Reject if more than 4 words (concatenated junk)
        if len(l.split()) > 4:
            continue
        # Reject if contains digits (stats, counts)
        if re.search(r"\d", l):
            continue
        valid += 1
    return valid >= 3

def _p6_extract(out: str) -> list[str]:
    raw = [l.strip() for l in out.splitlines() if l.strip()]
    # Strip any bullets/numbers the model added despite instructions
    cleaned_raw = []
    for line in raw:
        line = re.sub(r"^[-*•]\s+", "", line)
        line = re.sub(r"^\d+[.)]\s*", "", line)
        cleaned_raw.append(line.strip())
    # Run through the full clean_terms pipeline
    return clean_terms(cleaned_raw)

def _p6_fallback(candidate_links: list = None, **_) -> list[str]:
    return candidate_links or []

P6_TERMS = PromptContract(
    name="P6_terms",
    system=(
        "You are a technical term extractor. "
        "Output only a list of terms. No explanation. No duplicates."
    ),
    build=_p6_build,
    validate=_p6_validate,
    extract=_p6_extract,
    fallback=_p6_fallback,
)


# ============================================================================
# P7 — Classify Importance
# ============================================================================

def _p7_build(summary: str) -> str:
    return (
        "Rate the importance of this research for an AI practitioner on a scale of 1 to 5.\n\n"
        "1 = minor/incremental\n"
        "2 = useful but not groundbreaking\n"
        "3 = solid contribution\n"
        "4 = significant advance\n"
        "5 = landmark/must-read\n\n"
        "Output only the digit. Nothing else.\n\n"
        f"SUMMARY:\n{summary}"
    )

def _p7_validate(out: str) -> bool:
    return out.strip() in {"1", "2", "3", "4", "5"}

def _p7_extract(out: str) -> int:
    return int(out.strip())

def _p7_fallback(**_) -> int:
    return 3  # neutral — never wrong enough to matter

P7_IMPORTANCE = PromptContract(
    name="P7_importance",
    system="You are a relevance classifier. Output only a single digit.",
    build=_p7_build,
    validate=_p7_validate,
    extract=_p7_extract,
    fallback=_p7_fallback,
)


# ============================================================================
# P8 — Concept Page (one per new term)
# ============================================================================

def _p8_build(term: str, context_snippet: str) -> str:
    return (
        f"Write a short wiki entry for the technical concept: {term}\n\n"
        "Output exactly this format:\n\n"
        "DEFINITION: one paragraph, 2–4 sentences.\n"
        "WHY IT MATTERS: one sentence.\n"
        "VARIANTS: term1, term2 (or NONE)\n\n"
        f"CONTEXT (where this term appeared):\n{context_snippet[:200]}"
    )

def _p8_validate(out: str) -> bool:
    return "DEFINITION:" in out and "WHY IT MATTERS:" in out and _word_count(out) >= 20

def _p8_extract(out: str) -> dict[str, str]:
    result = {"definition": "", "why_it_matters": "", "variants": ""}
    for line in out.splitlines():
        if line.startswith("DEFINITION:"):
            result["definition"] = line.split("DEFINITION:", 1)[1].strip()
        elif line.startswith("WHY IT MATTERS:"):
            result["why_it_matters"] = line.split("WHY IT MATTERS:", 1)[1].strip()
        elif line.startswith("VARIANTS:"):
            result["variants"] = line.split("VARIANTS:", 1)[1].strip()
    return result

def _p8_fallback(term: str = "", **_) -> dict[str, str]:
    return {
        "definition":     f"🚧 Stub — {term} needs a manual definition.",
        "why_it_matters": "Significance not yet documented.",
        "variants":       "NONE",
    }

P8_CONCEPT = PromptContract(
    name="P8_concept",
    system=(
        "You are a technical wiki writer. "
        "Output only the requested content. Be precise and short."
    ),
    build=_p8_build,
    validate=_p8_validate,
    extract=_p8_extract,
    fallback=_p8_fallback,
)


# ============================================================================
# P3_BENCHMARK — Key Methodology for shared task / benchmark papers
# Used when doc_type == BENCHMARK_PAPER (SemEval, CoNLL, GLUE, etc.)
# ============================================================================

def _p3_benchmark_build(text: str, n_methods: int = 4) -> str:
    return (
        "This is a benchmark/shared task paper. Extract the key subtasks, datasets, "
        "and evaluation metrics it defines.\n\n"
        "STRICT FORMAT — one bullet per item:\n"
        "- Subtask/Dataset/Metric Name: one sentence describing what it is.\n\n"
        "EXAMPLES:\n"
        "- Aspect Term Extraction: Identifying aspect terms (e.g. 'battery') in review sentences.\n"
        "- Restaurants Dataset: 3041 sentences from restaurant reviews, manually annotated.\n"
        "- Accuracy Metric: Percentage of correctly predicted aspect polarities.\n\n"
        "DO NOT include author names, team names, submission counts, or institution names.\n\n"
        f"TEXT:\n{text[:4000]}"
    )

def _p3_benchmark_validate(out: str) -> bool:
    bullets = _bullet_lines(out)
    if len(bullets) < 2:
        return False
    # Each bullet must have ": " separator
    return sum(1 for b in bullets if ": " in b) >= 2

def _p3_benchmark_extract(out: str) -> list[str]:
    return _bullet_lines(out)

def _p3_benchmark_fallback(extracted_sections: dict = None, cleaned_text: str = "") -> list[str]:
    sections = extracted_sections or {}
    source = sections.get("abstract") or sections.get("introduction") or cleaned_text
    bullets = [l.strip() for l in source.splitlines()
               if re.match(r"^[-*•]\s+", l) or re.match(r"^\d+\.\s+", l)]
    if bullets:
        return [f"- {b.lstrip('-*•0123456789. ')}" for b in bullets[:5]]
    sentences = re.split(r"(?<=[.!?])\s+", source.strip())
    return [f"- {s.strip()}" for s in sentences[:4] if len(s.split()) >= 5]

P3_KEY_METHODS_BENCHMARK = PromptContract(
    name="P3_key_methods_benchmark",
    system=(
        "You are a technical extraction tool for benchmark papers. "
        "Output only bullet points describing subtasks, datasets, and metrics. "
        "No author names. No statistics about submission counts."
    ),
    build=_p3_benchmark_build,
    validate=_p3_benchmark_validate,
    extract=_p3_benchmark_extract,
    fallback=_p3_benchmark_fallback,
)


# ============================================================================
# Registry (ordered by execution sequence)
# ============================================================================

ALL_CONTRACTS: dict[str, PromptContract] = {
    "P0": P0_TITLE,
    "P0_5": P0_DOC_TYPE,
    "P1": P1_AUTHORS,
    "P2": P2_SUMMARY,
    "P3": P3_KEY_METHODS,
    "P3_BENCHMARK": P3_KEY_METHODS_BENCHMARK,
    "P4": P4_ANALYSIS,
    "P5": P5_QUESTIONS,
    "P6": P6_TERMS,
    "P7": P7_IMPORTANCE,
    "P8": P8_CONCEPT,
}