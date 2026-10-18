"""Preset dataclasses and canonical continuity/consistency definitions for StoryGraph."""

from __future__ import annotations

from dataclasses import dataclass

CONTINUITY_DEFINITION: str = (
    "Continuity is the seamless flow of action, time, and camera movement between consecutive shots. "
    "When prompting, align motion direction, object states, and lighting progressions across sequential clips."
)

CHARACTER_CONSISTENCY_DEFINITION: str = (
    "Character Consistency means keeping a subject's facial features, body type, and clothing identical across shots. "
    "Achieve this by repeating fixed identity descriptors or anchoring prompts with reference images."
)

SCENE_CONSISTENCY_DEFINITION: str = (
    "Scene Consistency is preserving the exact environment, architecture, lighting, and visual style throughout a sequence. "
    "Maintain it by reusing the same setting, atmosphere, and camera lens keywords in every prompt."
)


@dataclass(frozen=True)
class VisualStylePresetSpec:
    id: str
    category: str
    label: str
    short_description: str
    visual_medium: str
    default_palette: tuple[str, ...]
    lens_language: str
    lighting_rules: str
    avoid: tuple[str, ...]


@dataclass(frozen=True)
class ColorPalettePresetSpec:
    id: str
    label: str
    short_description: str
    swatches: tuple[str, ...]
    palette_keywords: tuple[str, ...]
    lighting_tint: str

    @property
    def palette(self) -> tuple[str, ...]:
        return self.palette_keywords


@dataclass(frozen=True)
class ScreenplayPresetSpec:
    id: str
    label: str
    short_description: str
    prompt_directive: str

    @property
    def instruction_prompt(self) -> str:
        return self.prompt_directive


@dataclass(frozen=True)
class MusicPresetSpec:
    id: str
    label: str
    short_description: str
    instrumentation: str
    default_bpm: int
    foley_directive: str

    @property
    def instruction_prompt(self) -> str:
        return self.foley_directive


@dataclass(frozen=True)
class DirectorPresetSpec:
    id: str
    label: str
    short_description: str
    bound_screenplay_preset: str
    bound_music_preset: str
    prompt_directive: str
    preferred_lens_mm: int
    preferred_movement: str

    @property
    def instruction_prompt(self) -> str:
        return self.prompt_directive


@dataclass(frozen=True)
class ResolvedProductionPresets:
    visual_style: VisualStylePresetSpec
    color_palette: ColorPalettePresetSpec
    director_style: DirectorPresetSpec
    screenplay_style: ScreenplayPresetSpec
    music_style: MusicPresetSpec
    combined_palette: list[str]
    combined_lighting_rules: str

    def format_global_instruction_block(self) -> str:
        return (
            f"VISUAL STYLE ({self.visual_style.label}): {self.visual_style.visual_medium}. "
            f"Lens: {self.visual_style.lens_language}. "
            f"COLOR PALETTE ({self.color_palette.label}): {', '.join(self.combined_palette)}. "
            f"Lighting: {self.combined_lighting_rules}\n"
            f"DIRECTOR STYLE ({self.director_style.label}): {self.director_style.prompt_directive}\n"
            f"SCREENPLAY STYLE ({self.screenplay_style.label}): {self.screenplay_style.prompt_directive}\n"
            f"MUSIC & FOLEY ({self.music_style.label}): {self.music_style.instrumentation}; {self.music_style.foley_directive}\n"
            f"9.1 Continuity: {CONTINUITY_DEFINITION}\n"
            f"9.2 Character Consistency: {CHARACTER_CONSISTENCY_DEFINITION}\n"
            f"9.3 Scene Consistency: {SCENE_CONSISTENCY_DEFINITION}"
        )


ProductionPresetBundle = ResolvedProductionPresets
