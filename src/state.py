"""
state.py — IngestState: the single source of truth for every pipeline run.

Design rules:
  - No stage communicates with another except through this object.
  - No stage raises an unhandled exception; all errors write here.
  - The object is JSON-serialisable so it can be persisted as a sidecar.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class FallbackLevel(IntEnum):
    FULL_LLM    = 1   # single-shot structured output
    TEMPLATE    = 2   # LLM fills individual template slots
    HEURISTIC   = 3   # regex / rule-based extraction, no LLM
    RAW_EXCERPT = 4   # first 500 chars + honest placeholders, always succeeds


class ValidationStatus(str):
    PASSED  = "passed"
    PARTIAL = "partial"
    FAILED  = "failed"
    PENDING = "pending"


class PageStatus(str):
    PROCESSED    = "processed"
    NEEDS_REVIEW = "needs-review"
    STUB         = "stub"


# ---------------------------------------------------------------------------
# Sub-structures (kept as plain dicts in state for JSON-safety)
# ---------------------------------------------------------------------------

def _empty_critical_analysis() -> dict[str, list[str]]:
    return {"strengths": [], "weaknesses": [], "assumptions": []}


def _error_entry(stage: str, error_type: str, message: str) -> dict:
    return {
        "stage":      stage,
        "error_type": error_type,
        "message":    message,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# IngestState
# ---------------------------------------------------------------------------

@dataclass
class IngestState:
    """
    Lifecycle of one paper through the ingest pipeline.

    Sections mirror the pipeline stages so you can grep any field name
    and find exactly which stage owns it.
    """

    # ── INPUT ────────────────────────────────────────────────────────────────
    raw_text:    str = ""
    source_path: str = ""
    ingest_date: str = field(
        default_factory=lambda: datetime.now(timezone.utc).date().isoformat()
    )

    # ── STAGE 0 — PREPROCESSING ──────────────────────────────────────────────
    cleaned_text:      str  = ""
    detected_language: str  = "unknown"
    source_char_count: int  = 0
    exceeds_context:   bool = False   # True → only first chunk processed

    # ── STAGE 1 — HEURISTIC EXTRACTION ───────────────────────────────────────
    extracted_title:    str                   = ""
    extracted_sections: dict[str, str]        = field(default_factory=dict)
    # e.g. {"abstract": "...", "introduction": "...", "methodology": "..."}

    extracted_metadata: dict[str, Any]        = field(default_factory=dict)
    # e.g. {"author": "...", "year": "2024", "source_url": "..."}

    candidate_links:    list[str]             = field(default_factory=list)
    # capitalized noun phrases; used if P6 fails

    # ── STAGE 2 — LLM MICRO-TASKS ────────────────────────────────────────────
    summary:           str                    = ""
    key_points:        list[str]              = field(default_factory=list)
    critical_analysis: dict[str, list[str]]  = field(
        default_factory=_empty_critical_analysis
    )
    open_questions:    list[str]              = field(default_factory=list)
    confirmed_links:   list[str]             = field(default_factory=list)
    concept_pages:     list[dict[str, str]]  = field(default_factory=list)
    # [{"name": "LoRA", "content": "...wiki stub..."}]

    # ── STAGE 3 — TEMPLATE ASSEMBLY ──────────────────────────────────────────
    structured_page: str = ""
    index_entry:     str = ""
    log_entry:       str = ""

    # ── STAGE 4 — VALIDATION ─────────────────────────────────────────────────
    validation_status: str        = ValidationStatus.PENDING
    validation_flags:  list[str]  = field(default_factory=list)
    # e.g. ["no_yaml", "short_summary", "no_links"]
    quality_score:     int        = 0   # 0–100

    # ── STAGE 5 — OUTPUT ─────────────────────────────────────────────────────
    page_status:    str  = PageStatus.STUB    # written to YAML frontmatter
    files_written:  list[str] = field(default_factory=list)
    sidecar_path:   str  = ""               # path to .json sidecar

    # ── CONTROL ──────────────────────────────────────────────────────────────
    fallback_level: int       = FallbackLevel.FULL_LLM
    retry_count:    int       = 0
    errors:         list[dict] = field(default_factory=list)
    completed_stages: list[str] = field(default_factory=list)

    # ── HELPERS ──────────────────────────────────────────────────────────────

    def add_error(self, stage: str, error_type: str, message: str) -> None:
        """Record a failure without raising. Pipeline always continues."""
        self.errors.append(_error_entry(stage, error_type, message))

    def mark_stage_done(self, stage_name: str) -> None:
        if stage_name not in self.completed_stages:
            self.completed_stages.append(stage_name)

    def add_flag(self, flag: str) -> None:
        if flag not in self.validation_flags:
            self.validation_flags.append(flag)

    def downgrade(self, reason: str) -> None:
        """Increment fallback level and record why."""
        if self.fallback_level < FallbackLevel.RAW_EXCERPT:
            old = self.fallback_level
            self.fallback_level += 1
            self.add_error(
                "orchestrator",
                "fallback_downgrade",
                f"L{old} → L{self.fallback_level}: {reason}",
            )

    def to_dict(self) -> dict:
        """Return JSON-serialisable dict (for sidecar persistence)."""
        import dataclasses
        return dataclasses.asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_dict(cls, d: dict) -> "IngestState":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_json(cls, s: str) -> "IngestState":
        return cls.from_dict(json.loads(s))