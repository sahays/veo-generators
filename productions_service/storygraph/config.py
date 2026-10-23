"""Pydantic configuration and YAML loader for StoryGraph."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from .omni.spec import PromptFormat


class StoreCfg(BaseModel):
    backend: str = "memory"  # "memory" | "firestore"
    firestore_project: str | None = None
    firestore_database: str = "(default)"
    collection_prefix: str = "veo_generators_productions"
    max_doc_bytes: int = 900_000


class BlobCfg(BaseModel):
    backend: str = "local"  # "local" | "gcs"
    local_root: str = "/tmp/storygraph_blobs"
    gcs_bucket: str | None = None
    gcs_prefix: str = "projects"


class ModelsCfg(BaseModel):
    story_architect: str = Field(
        default_factory=lambda: os.getenv(
            "GEMINI_AGENT_CREATIVE_MODEL", "gemini-3.8-flash"
        )
    )
    script_supervisor: str = Field(
        default_factory=lambda: os.getenv(
            "GEMINI_AGENT_SPECIALIST_MODEL", "gemini-3.8-flash"
        )
    )
    screenwriter: str = Field(
        default_factory=lambda: os.getenv(
            "GEMINI_AGENT_CREATIVE_MODEL", "gemini-3.8-flash"
        )
    )
    character_designer: str = Field(
        default_factory=lambda: os.getenv(
            "GEMINI_AGENT_CREATIVE_MODEL", "gemini-3.8-flash"
        )
    )
    location_designer: str = Field(
        default_factory=lambda: os.getenv(
            "GEMINI_AGENT_CREATIVE_MODEL", "gemini-3.8-flash"
        )
    )
    object_designer: str = Field(
        default_factory=lambda: os.getenv(
            "GEMINI_AGENT_CREATIVE_MODEL", "gemini-3.8-flash"
        )
    )
    designer: str = Field(
        default_factory=lambda: os.getenv(
            "GEMINI_AGENT_CREATIVE_MODEL", "gemini-3.8-flash"
        )
    )
    director: str = Field(
        default_factory=lambda: os.getenv(
            "GEMINI_AGENT_CREATIVE_MODEL", "gemini-3.8-flash"
        )
    )
    music_director: str = Field(
        default_factory=lambda: os.getenv(
            "GEMINI_AGENT_SPECIALIST_MODEL", "gemini-3.8-flash"
        )
    )
    critic_vlm: str = Field(
        default_factory=lambda: os.getenv(
            "GEMINI_AGENT_SPECIALIST_MODEL", "gemini-3.8-flash"
        )
    )


class ImageProviderCfg(BaseModel):
    provider: str = "mock"  # "gemini" | "mock"
    model: str = Field(
        default_factory=lambda: os.getenv("STORYBOARD_MODEL", "gemini-nano-banana-2.1")
    )


class VideoProviderCfg(BaseModel):
    provider: str = "mock"  # "veo" | "mock"
    model: str = Field(
        default_factory=lambda: os.getenv(
            "VIDEO_GEN_MODEL", "gemini-omni-1.1-flash-preview"
        )
    )
    max_reference_images: int = 3
    max_duration_s: float = 10.0
    max_prompt_chars: int | None = None
    supports_first_frame: bool = True
    # Omni binds the previous shot's last frame via the `<FIRST_FRAME>` prompt tag ("tag");
    # "drop" omits it and relies on the text continuity state.
    first_frame_mode: Literal["tag", "drop"] = "tag"
    # Text sent to Omni: "hybrid" (prose beats + labelled block; prompt A/B v1 winner) or
    # "json" (legacy compact OmniClipSpec). The spec JSON is stored either way.
    prompt_format: PromptFormat = "hybrid"
    # How a clip is animated (storygraph/keyframes; docs/eval/keyframe_strategy_v1.md):
    # "keyframe_anchored" (default, v2 winner) = ONE request: <FIRST_FRAME>=kf0,
    # <LAST_FRAME>=kfN + evenly spaced middle keyframes as timed state refs (S8_KEYFRAMES);
    # "keyframe_anchored_text" = first/last + middle states as text;
    # "direct" = one Omni request from the compiled prompt (pre-keyframe behaviour);
    # "keyframe_interp" = chained <FIRST_FRAME>/<LAST_FRAME> interpolation between 1 fps
    # graph keyframes every `keyframe_stride_s` seconds, stitched;
    # "animatic_edit" = the 1 fps keyframe animatic sent as <VIDEO_0> to animate.
    render_strategy: Literal[
        "direct",
        "keyframe_interp",
        "animatic_edit",
        "keyframe_anchored",
        "keyframe_anchored_text",
    ] = "keyframe_anchored"
    keyframe_stride_s: int = Field(default=3, ge=3, le=10)

    supports_audio_prompt: bool = True


class QACfg(BaseModel):
    face_cosine_min: float = 0.65
    wardrobe_vlm_min: float = 0.70
    setting_vlm_min: float = 0.70
    action_vlm_min: float = 0.70
    physics_vlm_min: float = 0.75
    permanence_vlm_min: float = 0.75
    dialogue_wer_max: float = 0.15
    # Optional cheap-LLM rewrite of unclassified critic reasons into target states.
    retry_rewrite_llm: bool = False


class CapsCfg(BaseModel):
    shot_max_retries: int = 3
    design_loop_max: int = 2
    max_words_per_sec: float = 2.8
    max_composite_subjects: int = 2
    stage_token_cap: int = 500_000
    project_cost_cap_usd: float = 50.0


class AssemblyCfg(BaseModel):
    """Final-assembly music bed settings (MusicCue audio mixed under stitched clips)."""

    music_enabled: bool = True
    music_gain: float = 0.35
    music_crossfade_s: float = 1.5
    duck_threshold: float = 0.05
    duck_ratio: float = 8.0


class AudioCfg(BaseModel):
    """Clip audio post-production (docs/eval/voiceover_sync_v1.md, docs/eval/audio_stems_v1.md).

    `mode`:
      * "omni"           keep Omni's audio as rendered (voices change between clips).
      * "voiceover_duck" fixed-voice TTS over Omni's bed, Omni speech ducked (`duck_db`
                         over transcript + VAD windows) or removed by `speech_removal`.
      * "stems"          Omni audio is a guide track only; final audio = dialogue stem
                         (fixed-voice TTS) + SFX stem (demucs no_vocals, residual voice
                         ducked by `residual_db`) + S5 music ducked under dialogue in S10.
    """

    mode: Literal["omni", "voiceover_duck", "stems"] = "stems"  # stems won v5 (see doc)
    speech_removal: Literal["duck", "demucs"] = "duck"
    tts_model: str = "gemini-2.5-flash-tts"
    duck_db: float = Field(default=-26.0, le=0.0)
    # TTS is asked to fit this fraction of Omni's speech window (leaves atempo headroom).
    pace_factor: float = Field(default=0.85, gt=0.3, le=1.0)
    tempo_min: float = Field(default=0.8, gt=0.5, le=1.0)
    tempo_max: float = Field(default=1.35, ge=1.0, lt=2.0)
    voice_lufs: float = -16.0
    # stems mode
    residual_db: float = Field(default=-24.0, le=0.0)  # SFX stem inside vocal activity
    dialogue_lufs: float = -16.0
    sfx_lufs: float = -24.0
    music_lufs: float = -26.0

    @property
    def voiceover_on(self) -> bool:
        """True for the modes that replace Omni's voices."""
        return self.mode != "omni"


DimensionName = Literal[
    "character_consistency",
    "temporal_consistency",
    "spatial_consistency",
    "scene_consistency",
    "object_permanence",
    "physical_plausibility",
    "action_adherence",
    "camera_adherence",
    "style_consistency",
    "audio",
    "script_adherence",
]


class DimensionGate(BaseModel):
    """Per-dimension gate: score floor, weight in the overall score, hard-gate flag.

    `demote_high_defects` makes this dimension's HIGH defects count as MEDIUM in the defect
    gate (for detectors that golden-set calibration found too imprecise to block alone).
    """

    threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    weight: float = Field(default=0.05, ge=0.0)
    hard_gate: bool = False
    demote_high_defects: bool = False
    # When set, a hard gate below `threshold` blocks only if the dimension also reported a
    # MEDIUM/HIGH defect, or its score is below `threshold - evidence_margin` (score scales
    # are style-dependent, so a bare near-threshold score is not evidence of a defect).
    evidence_margin: float | None = Field(default=None, ge=0.0, le=1.0)


def _default_dimension_gates() -> dict[DimensionName, DimensionGate]:
    """Code defaults (mirrors `config/default.yaml: eval.dimensions`, golden-v1 calibrated).

    Tuple: (threshold, weight, hard_gate, demote_high_defects).
    """
    spec: dict[DimensionName, tuple[float, float, bool, bool]] = {
        "character_consistency": (0.7, 0.16, True, False),
        "temporal_consistency": (0.6, 0.10, True, False),
        "spatial_consistency": (0.5, 0.05, False, False),
        "scene_consistency": (0.6, 0.07, False, False),
        "object_permanence": (0.6, 0.12, True, True),
        "physical_plausibility": (0.6, 0.07, False, False),
        "action_adherence": (0.6, 0.14, False, True),
        "camera_adherence": (0.0, 0.03, False, False),
        "style_consistency": (0.6, 0.06, False, False),
        "audio": (0.5, 0.05, False, False),
        "script_adherence": (0.6, 0.15, False, False),
    }
    margins: dict[DimensionName, float] = {"character_consistency": 0.15}
    return {
        k: DimensionGate(
            threshold=t,
            weight=w,
            hard_gate=h,
            demote_high_defects=d,
            evidence_margin=margins.get(k),
        )
        for k, (t, w, h, d) in spec.items()
    }


class GateConfig(BaseModel):
    """Attempt-independent video-eval gate (identical thresholds on every attempt)."""

    dimensions: dict[DimensionName, DimensionGate] = Field(
        default_factory=_default_dimension_gates
    )
    overall_threshold: float = Field(default=0.65, ge=0.0, le=1.0)
    min_confidence: float = Field(default=0.3, ge=0.0, le=1.0)
    max_medium_defects: int = 3

    def for_dimension(self, name: DimensionName) -> DimensionGate:
        """Gate for `name`; camera adherence is never a hard gate."""
        gate = self.dimensions.get(name, DimensionGate())
        if name == "camera_adherence" and gate.hard_gate:
            return gate.model_copy(update={"hard_gate": False})
        return gate


class Config(BaseModel):
    store: StoreCfg = StoreCfg()
    blobs: BlobCfg = BlobCfg()
    models: ModelsCfg = ModelsCfg()
    image: ImageProviderCfg = ImageProviderCfg()
    video: VideoProviderCfg = VideoProviderCfg()
    qa: QACfg = QACfg()
    caps: CapsCfg = CapsCfg()
    assembly: AssemblyCfg = AssemblyCfg()
    audio: AudioCfg = AudioCfg()
    eval: GateConfig = Field(default_factory=lambda: GateConfig())

    @classmethod
    def load(cls, path: str | Path | None = None) -> Config:
        default_path = Path(__file__).parent / "config" / "default.yaml"
        target = Path(path) if path else default_path
        if target.is_file():
            raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
            return cls.model_validate(raw)
        return cls()
