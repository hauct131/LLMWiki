"""
stages/stage3_assembly.py — Programmatic assembly of the final wiki page.

No LLM. No external calls.
Reads from state, writes structured_page, index_entry, log_entry.

Design:
  - Template is a fixed string with named slots.
  - Every slot has a 3-level priority: LLM value → heuristic value → placeholder.
  - This stage CANNOT fail in a way that produces no output.
  - Worst case = a syntactically valid stub page.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from ..config import PipelineConfig
from ..state import IngestState, PageStatus
from ..vault_linker import normalize_concept

logger = logging.getLogger(__name__)

STAGE_NAME = "stage3_assembly"

# ---------------------------------------------------------------------------
# Wiki page template
# The assembler fills named {slots}. Template itself never changes.
# ---------------------------------------------------------------------------

SOURCE_PAGE_TEMPLATE = """\
---
title: "{title}"
tags: [{tags}]
author: "{author}"
year: {year}
date_ingested: {date_ingested}
importance: {importance}
status: {status}
source: "{source_url}"
---

## Summary

{summary}

## Key Methodology

{key_points}

## Critical Analysis

**Strengths**
{strengths}

**Weaknesses**
{weaknesses}

## Open Questions

{open_questions}

## Related Concepts

{related_links}

---
*Ingested: {date_ingested} | Quality: __QUALITY__ | Level: __LEVEL__*
"""

CONCEPT_PAGE_TEMPLATE = """\
---
title: "{title}"
tags: [concept, stub]
status: stub
---

## Definition

{definition}

## Why It Matters

{why_it_matters}

## Variants / Related Terms

{variants}

---
*Auto-generated concept stub — verify before publishing.*
"""

INDEX_ROW_TEMPLATE = "| [[{title}]] | {author} | {year} | {importance} | {status} | {date_ingested} |"

LOG_ENTRY_TEMPLATE = (
    "- `{date_ingested}` — **{title}** "
    "| {status}"
    "{error_note}"
)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(state: IngestState, config: PipelineConfig) -> IngestState:
    try:
        slots = _collect_slots(state)

        state.structured_page = SOURCE_PAGE_TEMPLATE.format(**slots)
        state.index_entry      = INDEX_ROW_TEMPLATE.format(**slots)
        state.log_entry        = _build_log_entry(slots, state)

        # Build concept pages
        for concept in state.concept_pages:
            concept["rendered_page"] = _render_concept_page(concept)

        state.mark_stage_done(STAGE_NAME)
        logger.debug("Stage 3 assembled page: %d chars", len(state.structured_page))

    except Exception as exc:  # noqa: BLE001
        state.add_error(STAGE_NAME, "unexpected", str(exc))
        # Last resort: produce an absolute minimal page so we never return empty
        state.structured_page = _emergency_stub(state)

    return state


# ---------------------------------------------------------------------------
# Slot collection — three-level priority for each field
# ---------------------------------------------------------------------------

_PLACEHOLDER = {
    "summary":        "Summary not available — needs manual review.",
    "key_points":     "- Key methodology not extracted.",
    "strengths":      "- Not assessed.",
    "weaknesses":     "- Not assessed.",
    "open_questions": "- [ ] What are the key open questions for this work?",
    "related_links":  "",
    "tags":           "needs-review",
    "source_url":     "",
}


def _collect_slots(state: IngestState) -> dict[str, str]:
    meta = state.extracted_metadata

    title       = state.extracted_title or "Untitled"
    author      = meta.get("author", "Unknown")
    year        = meta.get("year", "Unknown")
    date_in     = state.ingest_date
    importance  = meta.get("importance", "3")
    source_url  = meta.get("source_url", "")
    status      = state.page_status or PageStatus.STUB

    summary     = state.summary or _PLACEHOLDER["summary"]
    key_points  = _render_bullets(state.key_points) or _PLACEHOLDER["key_points"]

    analysis    = state.critical_analysis or {}
    strengths   = _render_bullets(analysis.get("strengths", [])) or _PLACEHOLDER["strengths"]
    weaknesses  = _render_bullets(analysis.get("weaknesses", [])) or _PLACEHOLDER["weaknesses"]

    open_q      = _render_task_list(state.open_questions) or _PLACEHOLDER["open_questions"]
    links       = _render_obsidian_links(state.confirmed_links or state.candidate_links)
    tags        = _render_tags(state.confirmed_links or state.candidate_links, title)

    return {
        "title":          _safe_yaml_str(title),
        "tags":           tags,
        "author":         _safe_yaml_str(author),
        "year":           year,
        "date_ingested":  date_in,
        "importance":     importance,
        "status":         status,
        "source_url":     _safe_yaml_str(source_url),
        "summary":        summary,
        "key_points":     key_points,
        "strengths":      strengths,
        "weaknesses":     weaknesses,
        "open_questions": open_q,
        "related_links":  links,
    }


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def _render_bullets(items: list[str]) -> str:
    if not items:
        return ""
    cleaned = []
    for item in items:
        item = item.strip()
        if not item.startswith("- "):
            item = f"- {item}"
        cleaned.append(item)
    return "\n".join(cleaned)


def _render_task_list(items: list[str]) -> str:
    if not items:
        return ""
    cleaned = []
    for item in items:
        item = item.strip()
        if not item.startswith("- [ ]"):
            item = f"- [ ] {item.lstrip('- ')}"
        cleaned.append(item)
    return "\n".join(cleaned)


def _render_obsidian_links(terms: list[str]) -> str:
    seen = set()
    links = []
    for term in terms:
        norm = normalize_concept(term.strip())
        if norm and len(norm) > 2 and norm not in seen:
            seen.add(norm)
            links.append(f"- [[{norm}]]")
    return "\n".join(links)

def _render_tags(terms: list[str], title: str) -> str:
    """Convert terms to YAML-safe tag list."""
    slugs = set()
    for term in terms[:8]:
        slug = re.sub(r"[^a-z0-9\-]", "-", term.lower().strip())
        slug = re.sub(r"-{2,}", "-", slug).strip("-")
        if slug:
            slugs.add(slug)
    slugs.add("source")
    return ", ".join(sorted(slugs))


def _safe_yaml_str(s: str) -> str:
    """Escape quotes in YAML string values."""
    return s.replace('"', '\\"').replace("\n", " ").strip()


# ---------------------------------------------------------------------------
# Concept page rendering
# ---------------------------------------------------------------------------

def _render_concept_page(concept: dict) -> str:
    return CONCEPT_PAGE_TEMPLATE.format(
        title=_safe_yaml_str(concept.get("name", "Unknown Term")),
        definition=concept.get("definition", "🚧 Stub."),
        why_it_matters=concept.get("why_it_matters", "Not yet documented."),
        variants=concept.get("variants", "NONE"),
    )


# ---------------------------------------------------------------------------
# Log entry
# ---------------------------------------------------------------------------

def _build_log_entry(slots: dict, state: IngestState) -> str:
    error_note = ""
    if state.errors:
        n = len(state.errors)
        error_note = f" | ⚠️ {n} error(s)"
    return LOG_ENTRY_TEMPLATE.format(
        **slots,
        error_note=error_note,
    )


# ---------------------------------------------------------------------------
# Emergency stub (last resort — stage itself failed)
# ---------------------------------------------------------------------------

def _emergency_stub(state: IngestState) -> str:
    title = state.extracted_title or "Untitled"
    excerpt = state.cleaned_text[:500] if state.cleaned_text else state.raw_text[:500]
    return (
        f"---\ntitle: \"{title}\"\nstatus: stub\ntags: [stub, needs-review]\n---\n\n"
        f"## Summary\n\n🚧 Emergency stub — assembly failed. Raw excerpt:\n\n{excerpt}\n"
    )