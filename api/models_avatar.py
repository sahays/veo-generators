"""Avatar feature models — interactive AI avatars that reply with lip-synced video."""

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from models_core import UsageMetrics, generate_id


class AvatarStyle(str, Enum):
    talkative = "talkative"
    funny = "funny"
    serious = "serious"
    cynical = "cynical"
    to_the_point = "to_the_point"


class AvatarVoice(str, Enum):
    """Prebuilt voices supported by Gemini Live (used by v2 avatars).

    Names match the upstream gemini-avatar VOICE_PRESETS catalog. Gender
    grouping is the frontend's concern; the backend just validates the id.
    """

    # All 30 voices the API exposes. We accept any of them; gender filtering
    # in the UI is purely cosmetic.
    Kore = "Kore"
    Puck = "Puck"
    Charon = "Charon"
    Fenrir = "Fenrir"
    Aoede = "Aoede"
    Leda = "Leda"
    Orus = "Orus"
    Zephyr = "Zephyr"
    Autonoe = "Autonoe"
    Umbriel = "Umbriel"
    Erinome = "Erinome"
    Laomedeia = "Laomedeia"
    Schedar = "Schedar"
    Achird = "Achird"
    Sadachbia = "Sadachbia"
    Enceladus = "Enceladus"
    Algieba = "Algieba"
    Algenib = "Algenib"
    Achernar = "Achernar"
    Gacrux = "Gacrux"
    Zubenelgenubi = "Zubenelgenubi"
    Sadaltager = "Sadaltager"
    Callirrhoe = "Callirrhoe"
    Iapetus = "Iapetus"
    Despina = "Despina"
    Rasalgethi = "Rasalgethi"
    Alnilam = "Alnilam"
    Pulcherrima = "Pulcherrima"
    Vindemiatrix = "Vindemiatrix"
    Sulafat = "Sulafat"


AvatarVersion = Literal["v1", "v2"]


class Avatar(BaseModel):
    id: str = Field(default_factory=lambda: generate_id("av-"))
    name: str
    # v1 always has a portrait. v2 with a preset doesn't need one — we make
    # it optional and let the frontend send "" or null when using a preset.
    image_gcs_uri: str = ""
    style: AvatarStyle = AvatarStyle.to_the_point
    persona_prompt: str = ""
    is_default: bool = False
    signed_urls: dict = Field(default_factory=dict)
    archived: bool = False
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    # v2 (Low Latency) avatars use Gemini Live; v1 stays the Veo render pipeline.
    version: AvatarVersion = "v1"
    voice: Optional[AvatarVoice] = None  # required for v2, ignored for v1
    # v2 only — name of the preset avatar (e.g. "Kira", "Hana"). When set,
    # the live setup frame uses {avatarConfig: {avatarName}} instead of a
    # customizedAvatar with the user's portrait.
    preset_name: Optional[str] = None
    # v2 only — BCP-47 language code for ASR + TTS (e.g. "en-US", "es-ES",
    # "ja-JP"). Defaults to en-US to keep existing avatars working.
    language: str = "en-US"
    # v2 only — first sentence the avatar speaks when the session opens.
    # Empty string means no scripted opener.
    default_greeting: str = ""
    # v2 only — when true, the live session is configured with Google Search
    # grounding so the model can pull live web facts.
    enable_grounding: bool = False


class AvatarTurn(BaseModel):
    id: str = Field(default_factory=lambda: generate_id("at-"))
    avatar_id: str
    question: str
    answer_text: str = ""
    video_gcs_uri: Optional[str] = None
    status: Literal["pending", "generating", "completed", "failed"] = "pending"
    progress_pct: int = 0
    error_message: Optional[str] = None
    model_id: Optional[str] = None
    region: Optional[str] = None
    usage: UsageMetrics = Field(default_factory=UsageMetrics)
    signed_urls: dict = Field(default_factory=dict)
    invite_code: Optional[str] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    completedAt: Optional[datetime] = None


class CreateAvatarRequest(BaseModel):
    name: str
    image_gcs_uri: str = ""
    style: AvatarStyle = AvatarStyle.to_the_point
    persona_prompt: str = ""
    version: AvatarVersion = "v1"
    voice: Optional[AvatarVoice] = None
    preset_name: Optional[str] = None
    language: str = "en-US"
    default_greeting: str = ""
    enable_grounding: bool = False

    @model_validator(mode="after")
    def _validate(self) -> "CreateAvatarRequest":
        if self.version == "v1":
            if not self.image_gcs_uri:
                raise ValueError("image_gcs_uri is required when version is 'v1'")
            # v1 doesn't use voice or preset; keep the record clean.
            self.voice = None
            self.preset_name = None
        else:  # v2
            if self.voice is None:
                raise ValueError("voice is required when version is 'v2'")
            if not self.preset_name and not self.image_gcs_uri:
                raise ValueError(
                    "either preset_name or image_gcs_uri is required for v2"
                )
        return self


class AskAvatarRequest(BaseModel):
    question: str
    history: list[dict] = Field(default_factory=list)
    model_id: Optional[str] = None
    region: Optional[str] = None
