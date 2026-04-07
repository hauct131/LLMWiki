
"""Stages sub-package — Mapping short filenames to pipeline expectations."""

from . import s0_preprocess as stage0_preprocess
from . import s1_heuristic as stage1_heuristic
from . import s2_llm_tasks as stage2_llm
from . import s3_assembly as stage3_assembly
from . import s4_validator as stage4_validation
from . import s5_output as stage5_output

__all__ = [
    "stage0_preprocess",
    "stage1_heuristic",
    "stage2_llm",
    "stage3_assembly",
    "stage4_validation",
    "stage5_output",
]