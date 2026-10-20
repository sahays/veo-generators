"""Classify a failed clip as *spec-caused* or *render-caused* (pure, deterministic).

A spec-caused failure cannot be fixed by re-rendering with a new seed: the compiled spec
itself contradicts what the critic expects (wrong object state, overloaded actions,
impossible staging). Those failures regenerate the clip's spec instead.

Evidence, strongest first:
1. Blocking spec-linter issues for the shot (Phase-1 `lint_shot`, when available).
2. The critic's structured `defects[].likely_cause` ('spec' | 'render' | 'reference').
   Read defensively: older `QAReport`s have no `defects` field.
3. Heuristics: the same failure class repeating across consecutive failed attempts of
   the same content, or a critic reason / suggested fix that points at the spec.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..config import QACfg
from ..schema import QAReport
from .diagnose import classify_failures
from .models import RepairRoute

DefectCause = Literal["spec", "render", "reference"]

_CAUSES: Final[frozenset[str]] = frozenset({"spec", "render", "reference"})
_SPEC_FIXES: Final[frozenset[str]] = frozenset({"recompile_prompt", "resplit_shot"})
_CONTRADICTION_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(contradict\w*|inconsistent with the (spec|script|prompt)|not in the (spec|script)"
    r"|spec (says|requires|asks)|impossible to|already (holding|there|adjacent|gone|eaten))\b",
    re.IGNORECASE,
)


class RouteDecision(BaseModel):
    """Which repair route a failed clip takes, and the evidence behind it."""

    model_config = ConfigDict(frozen=True)

    route: RepairRoute
    why: str
    evidence: list[str] = Field(default_factory=list)


def _defect_cause(defect: object) -> str | None:
    raw = (
        defect.get("likely_cause")
        if isinstance(defect, dict)
        else getattr(defect, "likely_cause", None)
    )
    cause = str(raw).strip().lower() if raw is not None else ""
    return cause if cause in _CAUSES else None


def defect_causes(report: QAReport) -> Counter[str]:
    """Count of `likely_cause` values over the critic's structured defects (may be empty)."""
    defects = getattr(report, "defects", None) or []
    return Counter(c for c in map(_defect_cause, defects) if c is not None)


def _defect_text(defect: object) -> str:
    parts = [
        str(v)
        for key in ("type", "subject", "evidence")
        if (
            v := defect.get(key)
            if isinstance(defect, dict)
            else getattr(defect, key, None)
        )
    ]
    return ": ".join(parts)


def spec_defect_texts(report: QAReport) -> list[str]:
    """Human-readable descriptions of the defects the critic attributes to the spec."""
    defects = getattr(report, "defects", None) or []
    return [t for d in defects if _defect_cause(d) == "spec" and (t := _defect_text(d))]


def _repeated_classes(
    report: QAReport, history: Sequence[QAReport], qa: QACfg
) -> list[str]:
    """Failure classes shared with the previous failed attempt of the same content."""
    if not history:
        return []
    now = set(classify_failures(report, qa))
    return sorted(c.value for c in now & set(classify_failures(history[-1], qa)))


def _spec_pointing_reasons(report: QAReport) -> list[str]:
    hits = [r for r in report.failure_reasons if _CONTRADICTION_RE.search(r)]
    if report.suggested_fix in _SPEC_FIXES:
        hits.append(f"suggested_fix={report.suggested_fix}")
    return hits


def _from_defects(causes: Counter[str]) -> RouteDecision | None:
    """Spec route when most defects are spec-caused; None when the defects don't say spec."""
    if causes["spec"] <= causes["render"] + causes["reference"]:
        return None
    evidence = [f"{k}={v}" for k, v in sorted(causes.items())]
    return RouteDecision(
        route="spec", why="critic attributes defects to the spec", evidence=evidence
    )


def classify_route(
    report: QAReport,
    history: Sequence[QAReport],
    lint_issues: Sequence[str],
    qa: QACfg,
) -> RouteDecision:
    """Route for the next repair of a failed clip.

    `history` holds earlier failed QA reports of the *same content version*, oldest first
    (excluding `report`); `lint_issues` are blocking spec-linter messages for the shot.
    A repeating failure overrides render-attributed defects (`likely_cause` defaults to
    'render', and a reseed that already failed the same way is not worth repeating).
    """
    if lint_issues:
        return RouteDecision(
            route="spec",
            why="spec linter reports blocking issues",
            evidence=list(lint_issues),
        )
    causes = defect_causes(report)
    by_defects = _from_defects(causes)
    if by_defects is not None:
        return by_defects
    repeated = _repeated_classes(report, history, qa)
    if repeated:
        return RouteDecision(
            route="spec", why="same failure repeated across attempts", evidence=repeated
        )
    pointing = [] if causes else _spec_pointing_reasons(report)
    if pointing:
        return RouteDecision(
            route="spec", why="critic reason contradicts the spec", evidence=pointing
        )
    return RouteDecision(
        route="render", why="no spec-level evidence; treat as render variance"
    )
