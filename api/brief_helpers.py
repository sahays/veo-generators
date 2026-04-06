"""Brief analysis parsing helpers."""

from models import Scene, SceneMetadata


def parse_scenes(data) -> tuple:
    """Parse Gemini response into Scene objects, global_style, continuity."""
    global_style = continuity = None
    if isinstance(data, dict):
        global_style = data.get("global_style")
        continuity = data.get("continuity")
        data = data.get("scenes", data)
    if not isinstance(data, list):
        return [], None, None

    scenes = []
    for s in data:
        metadata = s.get("metadata", {})
        if "character" in metadata and isinstance(metadata["character"], str):
            metadata["characters"] = [metadata.pop("character")]
        scenes.append(
            Scene(
                visual_description=s["visual_description"],
                timestamp_start=s["timestamp_start"],
                timestamp_end=s["timestamp_end"],
                metadata=SceneMetadata(**metadata),
                narration=s.get("narration"),
                narration_enabled=bool(s.get("narration")),
                music_description=s.get("music_description"),
                music_enabled=bool(s.get("music_description")),
                enter_transition=s.get("enter_transition"),
                exit_transition=s.get("exit_transition"),
                music_transition=s.get("music_transition"),
            )
        )
    return scenes, global_style, continuity
