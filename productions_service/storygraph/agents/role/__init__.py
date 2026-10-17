"""Role Agent runners package for `STORY_ARCHITECT`, `SCRIPT_SUPERVISOR`, `SCREENWRITER`, `DIRECTOR`, and `MUSIC_DIRECTOR`."""

from __future__ import annotations

from ...tools.role_helpers import (
    AttributeKV,
    DialogueLineDraft,
    DirectorSceneOutput,
    EventDraft,
    ExtractedEntityDraft,
    MusicCueDraft,
    MusicDirectorOutput,
    SceneDraft,
    ScreenwriterOutput,
    ScriptSupervisorOutput,
    ShotAudioDraft,
    ShotDraft,
    StoryArchitectOutput,
)
from ..runner import ROLE_AGENT_NAMES
from .architect import run_story_architect
from .director import run_director_for_scene
from .music import run_music_director
from .screenwriter import run_screenwriter_for_scene
from .supervisor import deduplicate_entities_fuzzy, run_script_supervisor

__all__ = [
    "ROLE_AGENT_NAMES",
    "AttributeKV",
    "DialogueLineDraft",
    "DirectorSceneOutput",
    "EventDraft",
    "ExtractedEntityDraft",
    "MusicCueDraft",
    "MusicDirectorOutput",
    "SceneDraft",
    "ScreenwriterOutput",
    "ScriptSupervisorOutput",
    "ShotAudioDraft",
    "ShotDraft",
    "StoryArchitectOutput",
    "deduplicate_entities_fuzzy",
    "run_director_for_scene",
    "run_music_director",
    "run_screenwriter_for_scene",
    "run_script_supervisor",
    "run_story_architect",
]
