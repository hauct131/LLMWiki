"""
pipeline.py — The main orchestrator.

Owns the execution loop, fallback/retry decisions, and inter-stage routing.
Stages never talk to each other — all communication is via IngestState.
The orchestrator reads state after each stage and decides what to do next.

Public API:
    pipeline = IngestPipeline(config)
    state    = pipeline.run(raw_text, source_path)
"""

from __future__ import annotations

import logging
from typing import Optional

from .config import PipelineConfig
from .prompt_runner import PromptRunner
from .state import FallbackLevel, IngestState, ValidationStatus
from .stages import (
    stage0_preprocess,
    s0_5_classifier,  # Added: New document classification stage
    stage1_heuristic,
    stage2_llm,
    stage3_assembly,
    stage4_validation,
    stage5_output,
)

logger = logging.getLogger(__name__)


class IngestPipeline:
    """
    Runs a single paper through all 6 stages with full fallback handling.

    Configuration is injected at construction time so the pipeline is
    reusable across many documents without creating new objects.
    """

    def __init__(self, config: Optional[PipelineConfig] = None) -> None:
        self.config = config or PipelineConfig()
        self.runner = PromptRunner(self.config)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, raw_text: str, source_path: str = "") -> IngestState:
        """
        Ingest one document. Always returns a fully populated IngestState.
        Never raises. Worst case: a Level 4 stub page.
        """
        state = IngestState(raw_text=raw_text, source_path=source_path)
        logger.info("Starting ingest: %r", source_path or "(no path)")

        try:
            state = self._execute(state)
        except Exception as exc:  # noqa: BLE001
            # Should be unreachable — every stage is guarded — but just in case.
            state.add_error("orchestrator", "fatal", str(exc))
            logger.critical("Unhandled exception in pipeline: %s", exc, exc_info=True)

        logger.info(
            "Ingest complete: level=L%d score=%d status=%s errors=%d",
            state.fallback_level,
            state.quality_score,
            state.page_status,
            len(state.errors),
        )
        return state

    # ------------------------------------------------------------------
    # Execution loop
    # ------------------------------------------------------------------

    def _execute(self, state: IngestState) -> IngestState:
        cfg = self.config

        # ── Stage 0: Preprocessing ────────────────────────────────────────
        state = stage0_preprocess.run(state, cfg)
        # Immediate L4 if cleaning left nothing usable
        if state.fallback_level >= FallbackLevel.RAW_EXCERPT:
            return self._fast_path_level4(state)

        # ── Stage 0.5: Document Classification ───────────────────────────
        # Identify if this is a scientific paper, news, or technical doc
        state = s0_5_classifier.run(state, cfg, self.runner)

        # ── Stage 1: Heuristic extraction (always runs) ───────────────────
        state = stage1_heuristic.run(state, cfg)

        # ── Stage 2 + Validate loop (with retry and downgrade) ────────────
        state = self._llm_loop(state)

        # ── Stage 3: Template assembly (always runs) ──────────────────────
        state = stage3_assembly.run(state, cfg)

        # ── Stage 4: Validation ───────────────────────────────────────────
        state = stage4_validation.run(state, cfg)

        # ── Post-validation fallback decision ─────────────────────────────
        state = self._post_validation(state)

        # ── Stage 5: Write output ─────────────────────────────────────────
        state = stage5_output.run(state, cfg)

        return state

    # ------------------------------------------------------------------
    # LLM loop: attempt Stage 2, validate, retry/downgrade as needed
    # ------------------------------------------------------------------

    def _llm_loop(self, state: IngestState) -> IngestState:
        cfg = self.config
        max_retries = cfg.max_retries_per_level

        while True:
            # Skip LLM entirely at L3 or L4
            if state.fallback_level >= FallbackLevel.HEURISTIC:
                logger.info("Skipping LLM (fallback_level=L%d)", state.fallback_level)
                break

            # Run Stage 2
            temp_override = self._retry_temperature(state)
            state = stage2_llm.run(state, cfg, self.runner)

            # Quick validation: did we get anything usable?
            quality = self._quick_quality_check(state)

            if quality >= 40:
                logger.debug("LLM output accepted (quick score ~%d)", quality)
                break

            # Failed — decide whether to retry or downgrade
            if state.retry_count < max_retries:
                state.retry_count += 1
                logger.info(
                    "LLM output poor (quick score ~%d) — retry %d/%d (L%d)",
                    quality, state.retry_count, max_retries, state.fallback_level,
                )
                # Reset LLM-populated fields so Stage 2 runs fresh
                state = self._clear_llm_fields(state)
                continue

            # Out of retries — downgrade
            reason = f"quick score {quality} after {state.retry_count+1} attempt(s)"
            state.downgrade(reason)
            state.retry_count = 0
            logger.info("Downgraded to L%d: %s", state.fallback_level, reason)

        return state

    # ------------------------------------------------------------------
    # Post-validation fallback handling
    # ------------------------------------------------------------------

    def _post_validation(self, state: IngestState) -> IngestState:
        cfg   = self.config
        score = state.quality_score

        if state.validation_status == ValidationStatus.FAILED:
            logger.warning(
                "Validation FAILED (score=%d, flags=%s)",
                score, state.validation_flags,
            )
            # If still at L1/L2 and we haven't tried heuristic-only, do so
            if state.fallback_level < FallbackLevel.HEURISTIC:
                state.downgrade("post-validation failure")
                # Rebuild with heuristic-only fields then re-assemble
                state = self._clear_llm_fields(state)
                state = stage3_assembly.run(state, cfg)
                state = stage4_validation.run(state, cfg)

        elif state.validation_status == ValidationStatus.PARTIAL:
            logger.info("Validation PARTIAL (score=%d) — marking needs-review", score)

        return state

    # ------------------------------------------------------------------
    # Level 4 fast path
    # ------------------------------------------------------------------

    def _fast_path_level4(self, state: IngestState) -> IngestState:
        """
        Source was empty/unreadable after Stage 0. Produce a stub page
        using only the source_path and first 500 raw characters.
        """
        logger.info("Fast path: Level 4 stub")
        # Minimal heuristic: extract what we can from raw text
        excerpt = state.raw_text[:500].strip() or "No content available."
        if not state.extracted_title:
            import os
            stem = os.path.splitext(os.path.basename(state.source_path))[0]
            state.extracted_title = stem.replace("-", " ").title() or "Untitled"

        state.summary = excerpt
        state = stage3_assembly.run(state, self.config)
        state = stage4_validation.run(state, self.config)
        state = stage5_output.run(state, self.config)
        return state

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _quick_quality_check(self, state: IngestState) -> int:
        """
        Fast heuristic score (0–100) to decide whether LLM output is
        worth keeping — runs BEFORE full Stage 4 validation.
        """
        score = 0
        if state.summary and len(state.summary.split()) >= 20:
            score += 40
        if state.key_points and len(state.key_points) >= 2:
            score += 20
        if state.confirmed_links and len(state.confirmed_links) >= 3:
            score += 20
        if state.critical_analysis.get("strengths"):
            score += 10
        if state.open_questions and len(state.open_questions) >= 2:
            score += 10
        return score

    def _clear_llm_fields(self, state: IngestState) -> IngestState:
        """Reset LLM-populated fields so Stage 2 reruns cleanly."""
        state.summary           = ""
        state.key_points        = []
        state.critical_analysis = {"strengths": [], "weaknesses": [], "assumptions": []}
        state.open_questions    = []
        state.confirmed_links   = []
        state.concept_pages     = []
        return state

    def _retry_temperature(self, state: IngestState) -> float | None:
        if state.retry_count > 0:
            delta = self.config.retry_temperature_delta * state.retry_count
            base  = self.config.profile.temperature
            return max(0.0, base + delta)
        return None