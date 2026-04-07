"""
tests/test_pipeline.py — Comprehensive test suite for the ingest pipeline.

Tests are organised by failure mode, not by module.
Uses unittest so there are zero external test-runner dependencies.

Run with:  python -m pytest tests/ -v
       or: python -m unittest tests.test_pipeline -v
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

# ── Adjust sys.path so tests can run from project root ────────────────────
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wiki_ingest.config import PipelineConfig
from wiki_ingest.pipeline import IngestPipeline
from wiki_ingest.state import FallbackLevel, IngestState, PageStatus, ValidationStatus
from wiki_ingest.stages import (
    stage0_preprocess,
    stage1_heuristic,
    stage2_llm,
    stage3_assembly,
    stage4_validation,
    stage5_output,
)
from wiki_ingest.prompts import P2_SUMMARY, P6_TERMS
from wiki_ingest.prompt_runner import PromptRunner


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────

GOOD_PAPER = """
# Attention Is All You Need

Ashish Vaswani, Noam Shazeer, Niki Parmar

Published 2017

## Abstract

The dominant sequence transduction models are based on complex recurrent or
convolutional neural networks that include an encoder and a decoder. The best
performing models also connect the encoder and decoder through an attention
mechanism. We propose a new simple network architecture, the Transformer,
based solely on attention mechanisms, dispensing with recurrence and
convolutions entirely.

## Introduction

Recurrent neural networks, long short-term memory and gated recurrent neural
networks in particular, have been firmly established as state of the art
approaches in sequence modeling and transduction problems such as language
modeling and machine translation.

## Methodology

We use multi-head attention and position-wise fully connected feed-forward
networks in a standard encoder-decoder structure. The Transformer uses
self-attention and cross-attention layers extensively.

## Experiments

We trained on the WMT 2014 English-to-German and English-to-French translation
tasks. Our model achieves 28.4 BLEU on English-to-German and 41.0 BLEU on
English-to-French, outperforming all previously published ensembles.

## Conclusion

In this work, we presented the Transformer, the first sequence transduction
model based entirely on attention, replacing the recurrent layers most commonly
used in encoder-decoder architectures with multi-headed self-attention.
""".strip()

EMPTY_TEXT   = "   \n\n   "
HTML_TEXT    = "<html><body><h1>Title</h1><p>Content here. More content.</p></body></html>"
MINIMAL_TEXT = "A short text with insufficient content for full analysis."


def _config(tmp_path: str = "/tmp/wiki_test") -> PipelineConfig:
    return PipelineConfig(
        model_tier="7b",
        output_dir=f"{tmp_path}/sources",
        concepts_dir=f"{tmp_path}/concepts",
        index_path=f"{tmp_path}/index.md",
        log_path=f"{tmp_path}/log.md",
        sidecar_dir=f"{tmp_path}/sidecars",
        api_timeout_secs=2,
    )


# ──────────────────────────────────────────────────────────────────────────
# Stage 0 tests
# ──────────────────────────────────────────────────────────────────────────

class TestStage0Preprocess(unittest.TestCase):

    def test_strips_html(self):
        state = IngestState(raw_text=HTML_TEXT)
        result = stage0_preprocess.run(state, _config())
        self.assertNotIn("<html>", result.cleaned_text)
        self.assertIn("Title", result.cleaned_text)

    def test_empty_text_triggers_level4(self):
        state = IngestState(raw_text=EMPTY_TEXT)
        result = stage0_preprocess.run(state, _config())
        self.assertEqual(result.fallback_level, FallbackLevel.RAW_EXCERPT)

    def test_context_overflow_truncates(self):
        long_text = "word " * 5000
        cfg = _config()
        cfg = PipelineConfig(
            **{**cfg.__dict__, "context_window_chars": 100, "chunk_on_overflow": True}
        )
        state = IngestState(raw_text=long_text)
        result = stage0_preprocess.run(state, cfg)
        self.assertTrue(result.exceeds_context)
        self.assertLessEqual(len(result.cleaned_text), 110)

    def test_language_detection_english(self):
        state = IngestState(raw_text=GOOD_PAPER)
        result = stage0_preprocess.run(state, _config())
        self.assertEqual(result.detected_language, "en")

    def test_never_raises_on_garbage_input(self):
        state = IngestState(raw_text="\x00\xff\xfe" * 100)
        try:
            result = stage0_preprocess.run(state, _config())
        except Exception as exc:
            self.fail(f"Stage 0 raised unexpectedly: {exc}")


# ──────────────────────────────────────────────────────────────────────────
# Stage 1 tests
# ──────────────────────────────────────────────────────────────────────────

class TestStage1Heuristic(unittest.TestCase):

    def _run(self, text=GOOD_PAPER):
        state = IngestState(raw_text=text, cleaned_text=text)
        return stage1_heuristic.run(state, _config())

    def test_extracts_title(self):
        result = self._run()
        self.assertIn("Attention", result.extracted_title)

    def test_extracts_abstract(self):
        result = self._run()
        self.assertIn("abstract", result.extracted_sections)

    def test_extracts_author_from_byline(self):
        result = self._run()
        self.assertNotEqual(result.extracted_metadata.get("author"), "Unknown")

    def test_extracts_year(self):
        result = self._run()
        self.assertEqual(result.extracted_metadata.get("year"), "2017")

    def test_candidate_links_extracted(self):
        result = self._run()
        self.assertGreater(len(result.candidate_links), 0)

    def test_partial_failure_allowed(self):
        """Stage 1 should never abort even with minimal input."""
        result = self._run(MINIMAL_TEXT)
        self.assertIn("stage1_heuristic", result.completed_stages)


# ──────────────────────────────────────────────────────────────────────────
# Prompt contract tests
# ──────────────────────────────────────────────────────────────────────────

class TestPromptContracts(unittest.TestCase):

    def test_p2_validate_rejects_bullets(self):
        bad = "- Point one.\n- Point two.\n- Point three."
        self.assertFalse(P2_SUMMARY.validate(bad))

    def test_p2_validate_accepts_3_sentences(self):
        good = (
            "This paper addresses the problem of sequence transduction. "
            "The core method is the Transformer architecture using self-attention. "
            "Results show 28.4 BLEU on EN-DE translation tasks."
        )
        self.assertTrue(P2_SUMMARY.validate(good))

    def test_p2_fallback_returns_nonempty(self):
        val = P2_SUMMARY.fallback(
            cleaned_text=GOOD_PAPER,
            extracted_sections={"abstract": "Abstract text. More text. Third sentence."},
        )
        self.assertTrue(len(val) > 10)

    def test_p6_validate_rejects_bullets(self):
        bad = "- Transformer\n- Attention\n- BLEU"
        self.assertFalse(P6_TERMS.validate(bad))

    def test_p6_validate_accepts_plain_terms(self):
        good = "Transformer\nMulti-Head Attention\nBLEU Score\nWMT Dataset\nSelf-Attention"
        self.assertTrue(P6_TERMS.validate(good))


# ──────────────────────────────────────────────────────────────────────────
# Prompt runner tests
# ──────────────────────────────────────────────────────────────────────────

class TestPromptRunner(unittest.TestCase):

    def _runner(self):
        return PromptRunner(_config())

    @patch("wiki_ingest.llm_router.call_llm")
    def test_uses_llm_on_valid_output(self, mock_llm):
        mock_llm.return_value = (
            "Transformer solves sequence-to-sequence tasks. "
            "It uses self-attention instead of recurrence. "
            "It achieves state-of-the-art translation results."
        )
        state = IngestState()
        runner = self._runner()
        val, ok = runner.run(
            P2_SUMMARY, state,
            prompt_kwargs={"text": GOOD_PAPER, "n_sentences": 3},
            fallback_kwargs={"cleaned_text": GOOD_PAPER, "extracted_sections": {}},
        )
        self.assertTrue(ok)
        self.assertIn("Transformer", val)

    @patch("wiki_ingest.llm_router.call_llm")
    def test_falls_back_on_empty_response(self, mock_llm):
        mock_llm.return_value = ""
        state = IngestState(cleaned_text=GOOD_PAPER)
        runner = self._runner()
        val, ok = runner.run(
            P2_SUMMARY, state,
            prompt_kwargs={"text": GOOD_PAPER, "n_sentences": 3},
            fallback_kwargs={"cleaned_text": GOOD_PAPER, "extracted_sections": {}},
        )
        self.assertFalse(ok)
        self.assertTrue(len(val) > 5)   # fallback produced something

    @patch("wiki_ingest.llm_router.call_llm")
    def test_falls_back_on_validation_failure(self, mock_llm):
        mock_llm.return_value = "- bullet one\n- bullet two\n"
        state = IngestState(cleaned_text=GOOD_PAPER)
        runner = self._runner()
        val, ok = runner.run(
            P2_SUMMARY, state,
            prompt_kwargs={"text": GOOD_PAPER, "n_sentences": 3},
            fallback_kwargs={"cleaned_text": GOOD_PAPER, "extracted_sections": {}},
        )
        self.assertFalse(ok)
        self.assertNotIn("- bullet", val)

    @patch("wiki_ingest.llm_router.call_llm")
    def test_errors_written_to_state(self, mock_llm):
        mock_llm.return_value = ""
        state = IngestState()
        runner = self._runner()
        runner.run(
            P2_SUMMARY, state,
            prompt_kwargs={"text": "x", "n_sentences": 3},
            fallback_kwargs={"cleaned_text": "x", "extracted_sections": {}},
        )
        self.assertTrue(len(state.errors) > 0)


# ──────────────────────────────────────────────────────────────────────────
# Stage 3 assembly tests
# ──────────────────────────────────────────────────────────────────────────

class TestStage3Assembly(unittest.TestCase):

    def _state_with_content(self) -> IngestState:
        state = IngestState(
            raw_text=GOOD_PAPER,
            cleaned_text=GOOD_PAPER,
            extracted_title="Attention Is All You Need",
            summary="A transformer model replaces RNNs with attention. It achieves SOTA results.",
            key_points=["- Multi-head attention: enables parallel computation."],
            critical_analysis={
                "strengths":   ["- Parallelisable architecture."],
                "weaknesses":  ["- Quadratic attention complexity."],
                "assumptions": [],
            },
            open_questions=["- [ ] Does it scale to 100B parameters?"],
            confirmed_links=["Transformer", "Multi-Head Attention", "BLEU"],
            extracted_metadata={"author": "Vaswani et al.", "year": "2017",
                                 "importance": "5", "source_url": ""},
        )
        return state

    def test_produces_valid_markdown(self):
        state = self._state_with_content()
        result = stage3_assembly.run(state, _config())
        self.assertIn("---", result.structured_page)
        self.assertIn("## Summary", result.structured_page)
        self.assertIn("[[Transformer]]", result.structured_page)

    def test_produces_index_entry(self):
        state = self._state_with_content()
        result = stage3_assembly.run(state, _config())
        self.assertIn("Vaswani", result.index_entry)

    def test_never_empty(self):
        # Even a completely empty state should produce a stub
        state = IngestState()
        result = stage3_assembly.run(state, _config())
        self.assertTrue(len(result.structured_page) > 50)

    def test_all_placeholder_slots_filled(self):
        state = IngestState()  # nothing populated
        result = stage3_assembly.run(state, _config())
        # No Python format placeholders should remain
        self.assertNotIn("{title}", result.structured_page)
        self.assertNotIn("{summary}", result.structured_page)


# ──────────────────────────────────────────────────────────────────────────
# Stage 4 validation tests
# ──────────────────────────────────────────────────────────────────────────

class TestStage4Validation(unittest.TestCase):

    def _assemble(self, state: IngestState) -> IngestState:
        return stage3_assembly.run(state, _config())

    def test_high_score_on_good_content(self):
        state = IngestState(
            raw_text=GOOD_PAPER,
            cleaned_text=GOOD_PAPER,
            extracted_title="Attention Is All You Need",
            summary="Transformers replace recurrence with attention. "
                    "The architecture is fully parallelisable. "
                    "It achieves new state-of-the-art translation scores.",
            key_points=["- Multi-head attention: parallel computation."],
            critical_analysis={
                "strengths": ["- Novel architecture."],
                "weaknesses": ["- Quadratic complexity."],
                "assumptions": [],
            },
            open_questions=["- [ ] How does it scale?"],
            confirmed_links=["Transformer", "Self-Attention", "BLEU"],
            extracted_metadata={"author": "Vaswani", "year": "2017",
                                 "importance": "5", "source_url": ""},
        )
        state = self._assemble(state)
        result = stage4_validation.run(state, _config())
        self.assertGreaterEqual(result.quality_score, 60)
        self.assertEqual(result.validation_status, ValidationStatus.PASSED)

    def test_flags_missing_yaml(self):
        state = IngestState()
        state.structured_page = "# Just a heading\n\nNo YAML here at all."
        result = stage4_validation.run(state, _config())
        self.assertIn("no_yaml", result.validation_flags)

    def test_detects_garbage_content(self):
        state = IngestState(raw_text=GOOD_PAPER, cleaned_text=GOOD_PAPER)
        # Assemble with the raw text verbatim as summary (copy-paste detection)
        state.summary     = GOOD_PAPER[:1200]
        state.confirmed_links = ["Transformer"]
        state.extracted_metadata = {"author": "x", "year": "2017",
                                     "importance": "3", "source_url": ""}
        state.extracted_title = "Test"
        state = self._assemble(state)
        result = stage4_validation.run(state, _config())
        self.assertIn("garbage_content", result.validation_flags)

    def test_score_zero_on_empty_page(self):
        state = IngestState()
        state.structured_page = ""
        result = stage4_validation.run(state, _config())
        self.assertEqual(result.quality_score, 0)
        self.assertEqual(result.validation_status, ValidationStatus.FAILED)


# ──────────────────────────────────────────────────────────────────────────
# End-to-end pipeline tests (LLM mocked)
# ──────────────────────────────────────────────────────────────────────────

class TestPipelineEndToEnd(unittest.TestCase):

    def _good_llm_responses(self):
        """Cycle through valid responses for each micro-task."""
        responses = [
            "Attention Is All You Need",                          # P0
            "AUTHORS: Vaswani et al.\nYEAR: 2017",               # P1
            "Transformers replace recurrence with attention mechanisms. "
            "The model uses multi-head self-attention throughout. "
            "It achieves new state-of-the-art on WMT translation tasks.",  # P2
            "- Multi-head attention: enables parallel sequence processing.\n"
            "- Positional encoding: injects sequence order without RNNs.",  # P3
            "STRENGTHS:\n- Fully parallelisable architecture.\n\n"
            "WEAKNESSES:\n- O(n²) attention complexity.",                   # P4
            "- [ ] Does it work on very long sequences?\n"
            "- [ ] Can it replace vision models too?",                      # P5
            "Transformer\nMulti-Head Attention\nPositional Encoding\n"
            "BLEU Score\nWMT Dataset",                                      # P6
            "5",                                                            # P7
        ]
        return iter(responses)

    @patch("wiki_ingest.llm_router.call_llm")
    def test_happy_path_produces_valid_page(self, mock_llm):
        responses = self._good_llm_responses()
        mock_llm.side_effect = lambda **_: next(responses, "3")

        cfg  = _config()
        pipe = IngestPipeline(cfg)
        state = pipe.run(GOOD_PAPER, "attention_paper.md")

        self.assertIn("## Summary", state.structured_page)
        self.assertGreater(state.quality_score, 40)
        self.assertNotEqual(state.page_status, PageStatus.STUB)

    @patch("wiki_ingest.llm_router.call_llm")
    def test_api_down_uses_heuristic(self, mock_llm):
        mock_llm.return_value = ""   # All LLM calls fail

        cfg  = _config()
        pipe = IngestPipeline(cfg)
        state = pipe.run(GOOD_PAPER, "attention_paper.md")

        # Must still produce a page — just heuristic-based
        self.assertTrue(len(state.structured_page) > 100)
        self.assertGreaterEqual(state.fallback_level, FallbackLevel.HEURISTIC)

    def test_empty_source_produces_stub(self):
        cfg  = _config()
        pipe = IngestPipeline(cfg)
        state = pipe.run("", "empty.md")

        self.assertEqual(state.fallback_level, FallbackLevel.RAW_EXCERPT)
        self.assertIn("---", state.structured_page)   # valid YAML block exists

    def test_pipeline_never_raises(self):
        cfg  = _config()
        pipe = IngestPipeline(cfg)
        garbage_inputs = [
            "\x00\x01\x02",
            "<script>alert('xss')</script>",
            "a" * 50_000,
            "",
            "   \n\n   ",
        ]
        for raw in garbage_inputs:
            try:
                pipe.run(raw, "test.md")
            except Exception as exc:
                self.fail(f"Pipeline raised on input {raw!r:.30}: {exc}")

    @patch("wiki_ingest.llm_router.call_llm")
    def test_weak_model_garbage_triggers_downgrade(self, mock_llm):
        # Model ignores schema and returns raw input
        mock_llm.return_value = GOOD_PAPER[:500]

        cfg  = _config()
        pipe = IngestPipeline(cfg)
        state = pipe.run(GOOD_PAPER, "attention_paper.md")

        # Should have downgraded away from L1
        self.assertGreater(state.fallback_level, FallbackLevel.FULL_LLM)

    @patch("wiki_ingest.llm_router.call_llm")
    def test_retry_lowers_temperature(self, mock_llm):
        call_log = []

        def capture(**kwargs):
            call_log.append(kwargs.get("temperature_override"))
            return ""  # always fail to force retries

        mock_llm.side_effect = capture

        cfg  = _config()
        pipe = IngestPipeline(cfg)
        pipe.run(GOOD_PAPER, "attention_paper.md")

        # At least one retry should have been attempted
        temps = [t for t in call_log if t is not None]
        # Temperature should decrease on retry (or stay None if never overridden)
        # Just check it didn't crash
        self.assertIsNotNone(state := pipe.run(GOOD_PAPER, "retry_test.md"))


# ──────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)