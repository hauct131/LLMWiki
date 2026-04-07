"""
stages/stage2_llm.py — Run all LLM micro-tasks and write results to state.

Design rules:
  - Skipped entirely if state.fallback_level == 4 (RAW_EXCERPT).
  - Each task (P0–P7) is fully isolated: one failure never blocks the rest.
  - LLM output is used only when it passes the contract's validate().
  - On any failure the heuristic/placeholder fallback fills the state field.
  - P7 depends on P2 having run first (only ordering constraint).

Writes to state:
  extracted_title, extracted_metadata, summary, key_points,
  critical_analysis, open_questions, confirmed_links,
  concept_pages (via P8 for each new term)
"""

from __future__ import annotations

import logging

from ..config import PipelineConfig
from ..prompt_runner import PromptRunner
# SỬA LỖI IMPORT: Trỏ trực tiếp vào contracts để không bị lỗi name import
from ..prompts.contracts import (
    P0_TITLE,
    P1_AUTHORS,
    P2_SUMMARY,
    P3_KEY_METHODS,
    P4_ANALYSIS,
    P5_QUESTIONS,
    P6_TERMS,
    P7_IMPORTANCE,
    P8_CONCEPT,
)
from ..state import FallbackLevel, IngestState

logger = logging.getLogger(__name__)

STAGE_NAME = "stage2_llm"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(state: IngestState, config: PipelineConfig, runner: PromptRunner) -> IngestState:
    """
    Execute all micro-tasks. Each task writes to exactly one state field.
    Always returns state — never raises.
    """
    if state.fallback_level >= FallbackLevel.RAW_EXCERPT:
        logger.info("Stage 2 skipped — already at Level 4")
        return state

    text     = state.cleaned_text
    sections = state.extracted_sections
    profile  = config.profile

    try:
        # ── P0: Title ─────────────────────────────────────────────────────
        title, ok = runner.run(
            P0_TITLE, state,
            prompt_kwargs={"text": text},
            fallback_kwargs={
                "source_path":  state.source_path,
                "cleaned_text": text,
            },
        )
        if ok or not state.extracted_title:
            state.extracted_title = title

        # ── P1: Authors + Date ────────────────────────────────────────────
        meta, ok = runner.run(
            P1_AUTHORS, state,
            prompt_kwargs={"text": text},
            fallback_kwargs={"cleaned_text": text},
        )
        if isinstance(meta, dict):
            # Merge — only overwrite if LLM succeeded or field is still Unknown
            for key, val in meta.items():
                if ok or state.extracted_metadata.get(key, "Unknown") == "Unknown":
                    state.extracted_metadata[key] = val

        # ── P2: Summary ───────────────────────────────────────────────────
        summary_text = _section_or_text(sections, ["abstract", "introduction"], text, 1500)
        summary, _ = runner.run(
            P2_SUMMARY, state,
            prompt_kwargs={
                "text":        summary_text,
                "n_sentences": profile.summary_sentences,
            },
            fallback_kwargs={
                "cleaned_text":      text,
                "extracted_sections": sections,
            },
        )
        state.summary = summary

        # ── P3: Key Methods ───────────────────────────────────────────────
        method_text = _section_or_text(
            sections, ["methodology", "introduction"], text,
            profile.max_input_chars,
            offset=500,
        )
        key_points, _ = runner.run(
            P3_KEY_METHODS, state,
            prompt_kwargs={
                "text":      method_text,
                "n_methods": profile.key_methods_count,
            },
            fallback_kwargs={
                "extracted_sections": sections,
                "cleaned_text":       text,
            },
        )
        state.key_points = key_points if isinstance(key_points, list) else []

        # ── P4: Strengths + Weaknesses ────────────────────────────────────
        full_text = text[: profile.max_input_chars * 2]
        analysis, _ = runner.run(
            P4_ANALYSIS, state,
            prompt_kwargs={"text": full_text},
            fallback_kwargs={},
        )
        if isinstance(analysis, dict):
            state.critical_analysis = analysis

        # ── P5: Open Questions ────────────────────────────────────────────
        conclusion_text = _section_or_text(
            sections, ["conclusion", "limitations"], text,
            profile.max_input_chars,
            from_end=True,
        )
        questions, _ = runner.run(
            P5_QUESTIONS, state,
            prompt_kwargs={"text": conclusion_text},
            fallback_kwargs={},
        )
        state.open_questions = questions if isinstance(questions, list) else []

        # ── P6: Technical Terms ───────────────────────────────────────────
        terms, _ = runner.run(
            P6_TERMS, state,
            prompt_kwargs={
                "text":    text,
                "n_terms": profile.terms_count,
            },
            fallback_kwargs={"candidate_links": state.candidate_links},
        )
        state.confirmed_links = terms if isinstance(terms, list) else state.candidate_links

        # ── P7: Importance (depends on P2 having run) ─────────────────────
        importance, _ = runner.run(
            P7_IMPORTANCE, state,
            prompt_kwargs={"summary": state.summary},
            fallback_kwargs={},
        )
        state.extracted_metadata["importance"] = str(importance)

        # ── P8: Concept Pages (one per new term, Level 1/2 only) ──────────
        if state.fallback_level <= FallbackLevel.TEMPLATE:
            state.concept_pages = _generate_concept_pages(
                state.confirmed_links, text, state, runner
            )

        state.mark_stage_done(STAGE_NAME)
        logger.debug("Stage 2 complete")

    except Exception as exc:  # noqa: BLE001
        state.add_error(STAGE_NAME, "unexpected", str(exc))

    return state


# ---------------------------------------------------------------------------
# Concept page generation (P8)
# ---------------------------------------------------------------------------

def _generate_concept_pages(
    terms: list[str],
    full_text: str,
    state: IngestState,
    runner: PromptRunner,
) -> list[dict[str, str]]:
    pages = []
    for term in terms[:8]:  # cap at 8 to avoid excessive API calls
        # Find a context snippet where the term appears
        idx = full_text.lower().find(term.lower())
        snippet = full_text[max(0, idx - 50): idx + 200] if idx != -1 else full_text[:200]

        result, _ = runner.run(
            P8_CONCEPT, state,
            prompt_kwargs={"term": term, "context_snippet": snippet},
            fallback_kwargs={"term": term},
        )
        if isinstance(result, dict) and result.get("definition"):
            pages.append({"name": term, **result})

    return pages


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _section_or_text(
    sections: dict[str, str],
    preferred: list[str],
    fallback_text: str,
    max_chars: int,
    offset: int = 0,
    from_end: bool = False,
) -> str:
    """Return the best available text slice for a given prompt input."""
    for key in preferred:
        if sections.get(key):
            return sections[key][:max_chars]

    text = fallback_text
    if from_end:
        return text[-max_chars:] if len(text) > max_chars else text
    return text[offset: offset + max_chars]