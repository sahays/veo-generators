"""Typed data contracts shared by the prompt A/B builders, runner, scorer and report.

Every stage exchanges only these frozen records (JSON-serialisable via `to_dict`), so a stage
can be re-run in isolation from the JSONL the previous stage wrote.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from ...adapters.omni.package import RefLabel

VariantId = Literal["V1_json", "V2_prose", "V3_hybrid", "V4_minimal"]
ALL_VARIANTS: tuple[VariantId, ...] = ("V1_json", "V2_prose", "V3_hybrid", "V4_minimal")
ShotCategory = Literal[
    "locomotion", "small_prop", "two_character", "dialogue", "close_up", "chained"
]


@dataclass(frozen=True)
class ShotCase:
    """One shot under test: the compiled V1 spec plus the exact images it is rendered with."""

    case_id: str
    project_id: str
    shot_id: str
    category: ShotCategory
    spec_json: str
    labels: tuple[RefLabel, ...]
    first_frame_uri: str | None = None
    prev_frame_path: str | None = None
    visual_style_preset: str = ""
    language: str = ""

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["labels"] = [asdict(lbl) for lbl in self.labels]
        return out

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ShotCase:
        labels = tuple(
            RefLabel(**{**lbl, "names": tuple(lbl["names"])}) for lbl in raw["labels"]
        )
        return cls(**{**raw, "labels": labels})


@dataclass(frozen=True)
class PromptVariant:
    """The text a variant sends for one case (header/images are added by the adapter)."""

    case_id: str
    variant: VariantId
    prompt: str
    words: int


@dataclass(frozen=True)
class RenderRecord:
    """Outcome of one Omni render (one case x variant x sample)."""

    case_id: str
    variant: VariantId
    sample: int
    clip_path: str | None
    ok: bool
    latency_s: float
    duration_s: float
    est_cost_usd: float
    request_text_sha: str
    image_uris: tuple[str, ...]
    error: str = ""
    fallback_level: str = "primary"

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["image_uris"] = list(self.image_uris)
        return out


@dataclass(frozen=True)
class FrameCheck:
    """Deterministic ffmpeg-derived signals for one clip."""

    frames_dir: str
    frames: int
    cut_times_s: tuple[float, ...]
    contact_sheet: str
    duration_s: float


@dataclass(frozen=True)
class ScoreRecord:
    """Per-render scores on the six reported dimensions (0..1, None = not applicable)."""

    case_id: str
    variant: VariantId
    sample: int
    dims: dict[str, float | None]
    overall: float
    gate_passed: bool
    cut_count: int
    transcript: str = ""
    defects: list[str] = field(default_factory=list)
    contact_sheet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
