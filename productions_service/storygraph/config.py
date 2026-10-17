"""Pydantic configuration and YAML loader for StoryGraph."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


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
    max_duration_s: float = 8.0
    max_prompt_chars: int = 4000
    supports_first_frame: bool = True

    supports_audio_prompt: bool = True


class QACfg(BaseModel):
    face_cosine_min: float = 0.65
    wardrobe_vlm_min: float = 0.70
    setting_vlm_min: float = 0.70
    action_vlm_min: float = 0.70
    dialogue_wer_max: float = 0.15


class CapsCfg(BaseModel):
    shot_max_retries: int = 3
    design_loop_max: int = 2
    max_words_per_sec: float = 2.8
    max_composite_subjects: int = 2
    stage_token_cap: int = 500_000
    project_cost_cap_usd: float = 50.0


class Config(BaseModel):
    store: StoreCfg = StoreCfg()
    blobs: BlobCfg = BlobCfg()
    models: ModelsCfg = ModelsCfg()
    image: ImageProviderCfg = ImageProviderCfg()
    video: VideoProviderCfg = VideoProviderCfg()
    qa: QACfg = QACfg()
    caps: CapsCfg = CapsCfg()

    @classmethod
    def load(cls, path: str | Path | None = None) -> Config:
        default_path = Path(__file__).parent / "config" / "default.yaml"
        target = Path(path) if path else default_path
        if target.is_file():
            raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
            return cls.model_validate(raw)
        return cls()
