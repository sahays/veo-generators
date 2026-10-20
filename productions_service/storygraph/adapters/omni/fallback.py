"""Explicit, logged fallback ladder for Omni interaction failures.

Level 0 `primary`: profile-sanitised prompt + all labelled images.
Level 1 `aggressive_single_ref`: aggressive rewrite + the single highest-priority identity image.
Level 2 `text_to_video`: aggressive rewrite, no images.
Every downgrade is logged (who/where/what/when/why/how) and returned as a `FallbackRecord`
so the pipeline can persist it on the `GenerationRun`.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from ...compile import Package
from .inputs import (
    FirstFrameMode,
    OmniRequest,
    build_omni_request,
    package_labels,
    plan_image_slots,
)
from .package import RenderPackage
from .safety import SafetyProfile, sanitize_prompt

logger = logging.getLogger(__name__)

FallbackLevel = Literal["primary", "aggressive_single_ref", "text_to_video"]


@dataclass(frozen=True)
class LadderStep:
    """One rung of the ladder: level name and the request to send."""

    level: FallbackLevel
    request: OmniRequest


@dataclass(frozen=True)
class FallbackRecord:
    """Audit record of a non-primary render path for one shot attempt."""

    shot_id: str
    project_id: str
    model: str
    fallback_level: FallbackLevel
    level_index: int
    safety_profile: str
    refs_dropped: tuple[str, ...]
    first_frame_dropped: bool
    reasons: tuple[str, ...]
    recorded_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable form for persistence."""
        out = asdict(self)
        out["refs_dropped"] = list(self.refs_dropped)
        out["reasons"] = list(self.reasons)
        return out


def project_id_of(package: Package) -> str:
    return package.project_id if isinstance(package, RenderPackage) else ""


def build_ladder(
    package: Package,
    profile: SafetyProfile,
    max_images: int,
    first_frame_mode: FirstFrameMode,
) -> list[LadderStep]:
    """Return the ordered request ladder; every rung's spec binds only the images it sends."""
    primary = plan_image_slots(
        package_labels(package), package.first_frame_uri, max_images, first_frame_mode
    )
    tokens = primary.ref_tokens()
    text = package.compiled_prompt

    def base(text: str) -> str:
        return sanitize_prompt(text, profile)

    def aggressive(text: str) -> str:
        return sanitize_prompt(text, profile, aggressive=True)

    return [
        LadderStep(
            "primary",
            build_omni_request(
                package, text, max_images, first_frame_mode, tokens, base
            ),
        ),
        LadderStep(
            "aggressive_single_ref",
            build_omni_request(package, text, 1, "drop", tokens, aggressive),
        ),
        LadderStep(
            "text_to_video",
            build_omni_request(package, text, 0, "drop", tokens, aggressive),
        ),
    ]


def make_record(
    package: Package,
    model: str,
    profile: SafetyProfile,
    ladder: list[LadderStep],
    used_index: int,
    reasons: list[str],
) -> FallbackRecord:
    """Describe which rung succeeded and what identity inputs were lost versus primary."""
    primary, used = ladder[0].request, ladder[used_index].request
    kept = set(used.image_uris)
    return FallbackRecord(
        shot_id=package.shot_id,
        project_id=project_id_of(package),
        model=model,
        fallback_level=ladder[used_index].level,
        level_index=used_index,
        safety_profile=profile.name,
        refs_dropped=tuple(u for u in primary.image_uris if u not in kept),
        first_frame_dropped=primary.first_frame_bound and not used.first_frame_bound,
        reasons=tuple(reasons),
    )


def log_downgrade(
    package: Package,
    model: str,
    profile: SafetyProfile,
    ladder: list[LadderStep],
    next_index: int,
    error: str,
) -> None:
    """Semantic WARNING emitted before trying the next rung."""
    record = make_record(package, model, profile, ladder, next_index, [error])
    logger.warning(
        "Omni render downgraded to fallback level %s for shot %s",
        record.fallback_level,
        package.shot_id,
        extra={
            "who": "storygraph.adapters.gemini_video",
            "where": "omni.fallback.log_downgrade",
            "what": "omni_fallback",
            "when": record.recorded_at,
            "why": error,
            "how": "aggressive sanitize + reduced references via interactions.create",
            "shot_id": record.shot_id,
            "project_id": record.project_id,
            "model": model,
            "fallback_level": record.fallback_level,
            "safety_profile": record.safety_profile,
            "refs_dropped": list(record.refs_dropped),
            "first_frame_dropped": record.first_frame_dropped,
        },
    )
