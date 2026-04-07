from __future__ import annotations

"""
prompt_runner.py — Executes a single PromptContract against the LLM.

Responsibilities:
  - Call the LLM via llm_router.
  - Validate the response deterministically.
  - On validation failure: return the contract's fallback value.
  - Never raise. Never retry (retry logic lives in the orchestrator).
  - Record success/failure in the IngestState passed in.

One PromptRunner instance per pipeline run; reused for all micro-tasks.
"""

import logging
from typing import Any, Optional

# Internal package imports - Fixed paths
from .config import PipelineConfig
from .llm_router import call_llm
from .prompts.contracts import PromptContract
from .state import IngestState

logger = logging.getLogger(__name__)


class PromptRunner:
    """
    Executes micro-prompts with full isolation: LLM failures do not propagate.
    """

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        contract: PromptContract,
        state: IngestState,
        prompt_kwargs: dict,
        fallback_kwargs: dict,
        temperature_override: Optional[float] = None,
    ) -> tuple[Any, bool]:
        """
        Execute a prompt contract.

        Returns:
            (value, llm_succeeded)
            value          — the extracted/fallback value to write to state
            llm_succeeded  — True if LLM output was used, False if fallback

        Never raises. All errors are written to state.errors.
        """
        user_prompt = contract.build(**prompt_kwargs)

        raw = call_llm(
            prompt=user_prompt,
            system=contract.system,
            config=self.config,
            temperature_override=temperature_override,
        )

        # ── Basic sanity before contract validation ───────────────────
        if len(raw.strip()) < self.config.min_response_len:
            return self._use_fallback(contract, state, fallback_kwargs, "empty_response")

        # ── Contract-level validation ─────────────────────────────────
        try:
            valid = contract.validate(raw)
        except Exception as exc:                   # noqa: BLE001
            state.add_error(contract.name, "validate_error", str(exc))
            return self._use_fallback(contract, state, fallback_kwargs, "validate_exception")

        if not valid:
            logger.debug("%s: validation failed — using fallback", contract.name)
            return self._use_fallback(contract, state, fallback_kwargs, "validate_failed")

        # ── Extract structured value from validated output ────────────
        try:
            value = contract.extract(raw)
            logger.debug("%s: LLM succeeded", contract.name)
            return value, True
        except Exception as exc:                   # noqa: BLE001
            state.add_error(contract.name, "extract_error", str(exc))
            return self._use_fallback(contract, state, fallback_kwargs, "extract_exception")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _use_fallback(
        self,
        contract: PromptContract,
        state: IngestState,
        fallback_kwargs: dict,
        reason: str,
    ) -> tuple[Any, bool]:
        state.add_error(
            stage=contract.name,
            error_type="llm_fallback",
            message=f"Reason: {reason}. Using heuristic fallback.",
        )
        try:
            value = contract.fallback(**fallback_kwargs)
        except Exception as exc:                   # noqa: BLE001
            # fallback itself broke — return type-safe empty value
            state.add_error(contract.name, "fallback_error", str(exc))
            value = _safe_empty(contract.name)
        return value, False


def _safe_empty(contract_name: str) -> Any:
    """Last-resort empty values that won't crash downstream template assembly."""
    defaults = {
        "P0_title":      "Untitled",
        "P1_authors":    {"author": "Unknown", "year": "Unknown"},
        "P2_summary":    "Summary unavailable.",
        "P3_key_methods": [],
        "P4_analysis":   {"strengths": [], "weaknesses": [], "assumptions": []},
        "P5_questions":  [],
        "P6_terms":      [],
        "P7_importance": 3,
        "P8_concept":    {"definition": "🚧 Stub", "why_it_matters": "", "variants": "NONE"},
    }
    return defaults.get(contract_name, "")