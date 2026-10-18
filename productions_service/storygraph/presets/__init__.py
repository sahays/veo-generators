"""Curated Visual Style, Color Palette, Directorial, Screenplay, and Music presets with O(1) auto-binding."""

from __future__ import annotations

from .models import (
    CHARACTER_CONSISTENCY_DEFINITION,
    CONTINUITY_DEFINITION,
    SCENE_CONSISTENCY_DEFINITION,
    ColorPalettePresetSpec,
    DirectorPresetSpec,
    MusicPresetSpec,
    ProductionPresetBundle,
    ResolvedProductionPresets,
    ScreenplayPresetSpec,
    VisualStylePresetSpec,
)
from .roles_and_resolver import (
    DIRECTOR_STYLE_PRESETS,
    MUSIC_STYLE_PRESETS,
    SCREENPLAY_STYLE_PRESETS,
    resolve_production_presets,
)
from .visual_and_palette import COLOR_PALETTE_PRESETS, VISUAL_STYLE_PRESETS

__all__ = [
    "CHARACTER_CONSISTENCY_DEFINITION",
    "COLOR_PALETTE_PRESETS",
    "CONTINUITY_DEFINITION",
    "DIRECTOR_STYLE_PRESETS",
    "MUSIC_STYLE_PRESETS",
    "SCENE_CONSISTENCY_DEFINITION",
    "SCREENPLAY_STYLE_PRESETS",
    "VISUAL_STYLE_PRESETS",
    "ColorPalettePresetSpec",
    "DirectorPresetSpec",
    "MusicPresetSpec",
    "ProductionPresetBundle",
    "ResolvedProductionPresets",
    "ScreenplayPresetSpec",
    "VisualStylePresetSpec",
    "resolve_production_presets",
]
