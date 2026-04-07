# Nội dung file src/__init__.py
from .pipeline import IngestPipeline
from .config import PipelineConfig
from .state import IngestState
"""
wiki_ingest — research paper → Obsidian wiki page pipeline.

Quick start:
    from wiki_ingest import IngestPipeline, PipelineConfig

    config   = PipelineConfig(model_tier="7b", api_model_name="mistral")
    pipeline = IngestPipeline(config)
    state    = pipeline.run(raw_text="...", source_path="paper.pdf")

    print(state.structured_page)
    print(f"Score: {state.quality_score}/100  Status: {state.page_status}")
"""

from .config import PipelineConfig, PROFILES, ModelProfile
from .pipeline import IngestPipeline
from .state import IngestState, FallbackLevel, ValidationStatus, PageStatus

__all__ = [
    "IngestPipeline",
    "PipelineConfig",
    "ModelProfile",
    "PROFILES",
    "IngestState",
    "FallbackLevel",
    "ValidationStatus",
    "PageStatus",
]