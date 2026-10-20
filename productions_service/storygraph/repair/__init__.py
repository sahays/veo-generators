"""Automatic QA repair for failing shots: diagnosis, directives and manual-edit flagging.

`loop.py` (render orchestration) is intentionally not re-exported here so pure modules
(compile, budget) can import the directive contract without pulling in the pipeline.
"""

from .classify import RouteDecision, classify_route, spec_defect_texts
from .diagnose import classify_failures, diagnose_failure, escalate, manual_edit_reasons
from .models import (
    MAX_REPAIR_ATTEMPTS,
    FailureClass,
    RepairDirective,
    RepairReport,
    RepairRoute,
    ShotRepairOutcome,
)

__all__ = [
    "MAX_REPAIR_ATTEMPTS",
    "FailureClass",
    "RepairDirective",
    "RepairReport",
    "RepairRoute",
    "RouteDecision",
    "ShotRepairOutcome",
    "classify_failures",
    "classify_route",
    "diagnose_failure",
    "escalate",
    "manual_edit_reasons",
    "spec_defect_texts",
]
