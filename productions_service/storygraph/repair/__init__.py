"""Automatic QA repair for failing shots: diagnosis, directives and manual-edit flagging.

`loop.py` (render orchestration) is intentionally not re-exported here so pure modules
(compile, budget) can import the directive contract without pulling in the pipeline.
"""

from .diagnose import classify_failures, diagnose_failure, escalate, manual_edit_reasons
from .models import (
    MAX_REPAIR_ATTEMPTS,
    FailureClass,
    RepairDirective,
    RepairReport,
    ShotRepairOutcome,
)

__all__ = [
    "MAX_REPAIR_ATTEMPTS",
    "FailureClass",
    "RepairDirective",
    "RepairReport",
    "ShotRepairOutcome",
    "classify_failures",
    "diagnose_failure",
    "escalate",
    "manual_edit_reasons",
]
