"""Role Agent runners facade re-exporting from `.role`."""

from __future__ import annotations

from .role import (
    ROLE_AGENT_NAMES,
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
    deduplicate_entities_fuzzy,
    run_director_for_scene,
    run_music_director,
    run_screenwriter_for_scene,
    run_script_supervisor,
    run_story_architect,
)

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
