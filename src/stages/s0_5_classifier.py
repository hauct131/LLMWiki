"""
stages/s0_5_classifier.py — Identify document genre to route logic.
"""
from __future__ import annotations
import logging
from ..config import PipelineConfig
from ..prompt_runner import PromptRunner
from ..prompts.contracts import P0_DOC_TYPE
from ..state import IngestState

logger = logging.getLogger(__name__)


def run(state: IngestState, config: PipelineConfig, runner: PromptRunner) -> IngestState:
    # Lấy 1000 ký tự đầu tiên để AI nhận diện (đủ để thấy Abstract/Intro)
    snippet = state.cleaned_text[:1000]

    result, ok = runner.run(
        P0_DOC_TYPE, state,
        prompt_kwargs={"text_snippet": snippet},
        fallback_kwargs={}
    )

    # Lưu vào state để các Stage sau sử dụng
    state.extracted_metadata["doc_type"] = result.get("category", "OTHER")
    state.extracted_metadata["doc_confidence"] = result.get("confidence", "0.0")

    logger.info(
        f"📄 Classification: {state.extracted_metadata['doc_type']} ({state.extracted_metadata['doc_confidence']})")

    state.mark_stage_done("stage0_5_classifier")
    return state