"""Before/after metrics for the plate-anchored keyframe validation (pure given PNG bytes).

Both sides are measured identically: per frame the deterministic drift vs the scene anchor
(after: the locked plate; before: the scene's first keyframe, the de-facto reference of the
old edit chain) with the same character masks from the new plan, the frame status, and the
entities the checker reported missing.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import mean

from pydantic import BaseModel, Field

from ...keyframes.render.drift import DriftCfg, check_drift

_MISSING_RE = re.compile(r"^(?P<name>[^:]+?)(?::| is) missing")


@dataclass(frozen=True)
class FrameIn:
    t: int
    png: bytes
    status: str
    issues: tuple[str, ...]


class FrameMetric(BaseModel):
    t: int
    status: str
    issues: list[str] = Field(default_factory=list)
    bad_fraction: float = 0.0
    chroma_ratio: float = 1.0
    contrast_ratio: float = 1.0
    drift_ok: bool = True
    missing: list[str] = Field(default_factory=list)


class ShotMetric(BaseModel):
    shot_id: str
    frames: list[FrameMetric] = Field(default_factory=list)
    failure_reason: str = ""

    @property
    def manual_edit(self) -> int:
        return sum(f.status == "manual_edit" for f in self.frames)


class SideMetrics(BaseModel):
    label: str
    shots: list[ShotMetric] = Field(default_factory=list)
    frames: int = 0
    manual_edit: int = 0
    manual_edit_rate: float = 0.0
    drift_rejects: int = 0
    mean_bad_fraction: float = 0.0
    worst_chroma_ratio: float = 1.0
    missing_entities: int = 0
    missing_by_name: dict[str, int] = Field(default_factory=dict)
    failed_shots: list[str] = Field(default_factory=list)


def missing_names(issues: Sequence[str]) -> list[str]:
    return [m.group("name").strip() for i in issues if (m := _MISSING_RE.match(i))]


def frame_metric(
    anchor: bytes, frame: FrameIn, xs: Sequence[float], cfg: DriftCfg
) -> FrameMetric:
    rep = check_drift(anchor, frame.png, xs, cfg)
    return FrameMetric(
        t=frame.t,
        status=frame.status,
        issues=list(frame.issues),
        bad_fraction=rep.bad_fraction,
        chroma_ratio=rep.chroma_ratio,
        contrast_ratio=rep.contrast_ratio,
        drift_ok=rep.ok,
        missing=missing_names(frame.issues),
    )


def _worst(values: Sequence[float]) -> float:
    return max(values, key=lambda r: abs(r - 1.0), default=1.0)


def summarise(label: str, shots: list[ShotMetric]) -> SideMetrics:
    frames = [f for s in shots for f in s.frames]
    by_name: dict[str, int] = {}
    for name in (n for f in frames for n in f.missing):
        by_name[name] = by_name.get(name, 0) + 1
    manual = sum(f.status == "manual_edit" for f in frames)
    return SideMetrics(
        label=label,
        shots=shots,
        frames=len(frames),
        manual_edit=manual,
        manual_edit_rate=round(manual / len(frames), 3) if frames else 0.0,
        drift_rejects=sum(not f.drift_ok for f in frames),
        mean_bad_fraction=round(mean(f.bad_fraction for f in frames), 4)
        if frames
        else 0.0,
        worst_chroma_ratio=_worst([f.chroma_ratio for f in frames]),
        missing_entities=sum(by_name.values()),
        missing_by_name=by_name,
        failed_shots=[s.shot_id for s in shots if s.failure_reason or not s.frames],
    )
