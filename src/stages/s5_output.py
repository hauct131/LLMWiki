"""
stages/stage5_output.py — Write all output files and persist state sidecar.

No LLM. Deterministic.
This stage decides final page_status, writes files, and is the only stage
that performs disk I/O (other than the sidecar in emergency paths).

Design:
  - All OS errors are caught and written to state.errors.
  - Sidecar (.json) is always written — even if everything else fails.
  - Index and log are appended to (not overwritten).
  - page_status is decided here from quality_score.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from ..config import PipelineConfig
from ..state import IngestState, PageStatus

logger = logging.getLogger(__name__)

STAGE_NAME = "stage5_output"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(state: IngestState, config: PipelineConfig) -> IngestState:
    try:
        # ── 1. Determine page_status from quality_score ───────────────────
        state.page_status = _compute_status(state.quality_score, config)

        # ── 2. Patch status into the already-assembled page ───────────────
        state.structured_page = _patch_status(state.structured_page, state.page_status)

        # ── 3. Write source page ──────────────────────────────────────────
        page_path = _output_path(config.output_dir, state.extracted_title)
        _write_file(page_path, state.structured_page, state)

        # ── 4. Write concept stub pages ───────────────────────────────────
        for concept in state.concept_pages:
            rendered = concept.get("rendered_page", "")
            if rendered and concept.get("name"):
                cpath = _output_path(config.concepts_dir, concept["name"])
                if not cpath.exists():   # never overwrite existing concept pages
                    _write_file(cpath, rendered, state)

        # ── 5. Append to index ────────────────────────────────────────────
        _append_to_index(config.index_path, state.index_entry, state)

        # ── 6. Append to log ──────────────────────────────────────────────
        _append_to_log(config.log_path, state.log_entry, state)

        # ── 7. Write sidecar (always) ─────────────────────────────────────
        sidecar = _write_sidecar(config.sidecar_dir, state)
        state.sidecar_path = str(sidecar)

        state.mark_stage_done(STAGE_NAME)
        logger.info(
            "Stage 5 complete: %s | score=%d | status=%s",
            page_path.name,
            state.quality_score,
            state.page_status,
        )

    except Exception as exc:  # noqa: BLE001
        state.add_error(STAGE_NAME, "unexpected", str(exc))
        # Last resort: write sidecar to /tmp so the ingest is never lost
        try:
            tmp = Path("/tmp") / f"wiki_ingest_failed_{_slug(state.extracted_title or 'unknown')}.json"
            tmp.write_text(state.to_json())
            state.sidecar_path = str(tmp)
            logger.error("Stage 5 failed — sidecar saved to %s", tmp)
        except Exception:  # noqa: BLE001
            pass

    return state


# ---------------------------------------------------------------------------
# Status decision
# ---------------------------------------------------------------------------

def _compute_status(score: int, config: PipelineConfig) -> str:
    if score >= config.min_score_processed:
        return PageStatus.PROCESSED
    if score >= config.min_score_needs_review:
        return PageStatus.NEEDS_REVIEW
    return PageStatus.STUB


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------

def _output_path(directory: str, title: str) -> Path:
    """Compute the output file path from a directory and page title."""
    slug  = _slug(title)
    fname = f"{slug}.md"
    return Path(directory) / fname


def _write_file(path: Path, content: str, state: IngestState) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        state.files_written.append(str(path))
        logger.debug("Written: %s", path)
    except OSError as exc:
        state.add_error(STAGE_NAME, "file_write_error", f"{path}: {exc}")


def _append_to_index(index_path: str, row: str, state: IngestState) -> None:
    if not row:
        return
    try:
        p = Path(index_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            # Create with header
            p.write_text(
                "| Title | Author | Year | Importance | Status | Ingested |\n"
                "|---|---|---|---|---|---|\n",
                encoding="utf-8",
            )
        with p.open("a", encoding="utf-8") as f:
            f.write(row + "\n")
    except OSError as exc:
        state.add_error(STAGE_NAME, "index_write_error", str(exc))


def _append_to_log(log_path: str, entry: str, state: IngestState) -> None:
    if not entry:
        return
    try:
        p = Path(log_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except OSError as exc:
        state.add_error(STAGE_NAME, "log_write_error", str(exc))


def _write_sidecar(sidecar_dir: str, state: IngestState) -> Path:
    """Serialise full IngestState as JSON next to the output."""
    slug  = _slug(state.extracted_title or "unknown")
    fname = f"{slug}.json"
    path  = Path(sidecar_dir) / fname
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(state.to_json(), encoding="utf-8")
    except OSError as exc:
        state.add_error(STAGE_NAME, "sidecar_write_error", str(exc))
    return path


# ---------------------------------------------------------------------------
# Patch status into assembled page
# ---------------------------------------------------------------------------

def _patch_status(page: str, status: str) -> str:
    """Replace the placeholder status value in YAML frontmatter."""
    # The template writes status: stub by default; update it here.
    return re.sub(
        r"^(status:\s*)(.+)$",
        lambda m: f"{m.group(1)}{status}",
        page,
        count=1,
        flags=re.MULTILINE,
    )


# ---------------------------------------------------------------------------
# Slug utility
# ---------------------------------------------------------------------------

def _slug(title: str) -> str:
    """Convert a title to a safe filename."""
    s = title.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:80] or "untitled"