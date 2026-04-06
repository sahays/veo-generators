"""Shared prompt templates for AI service operations."""


def build_collage_prompt(segments: list[dict] | None) -> str:
    """Build prompt for promo collage with optional moment context."""
    base = (
        "Create a stylized collage thumbnail from these video screenshots. "
        "Arrange in a dynamic layout — NOT a simple grid. "
        "Include a close-up crop of a person's face. "
        "Cinematic styling: color grading, dramatic lighting, subtle vignette. "
        "Infer a short, punchy title and render as bold text. "
        "Style: professional broadcast quality, like ESPN or Netflix promos."
    )
    if not segments:
        return base
    lines = [
        f"- {s.get('title', '')}: {s.get('description', '')}"
        for s in segments
        if s.get("title")
    ]
    if lines:
        base += (
            "\n\nKey moments:\n"
            + "\n".join(lines)
            + "\n\nUse these to create a relevant title.\n"
        )
    return base


def default_promo_prompt(target_duration: int) -> str:
    return (
        f"You are a professional video editor creating a {target_duration}-second "
        "promo/highlight reel. Select compelling moments. "
        f"Total duration ≈ {target_duration}s. Each segment 3-15s. "
        "Return segments in chronological order with title, description, "
        "timestamp_start, timestamp_end, relevance_score."
    )


DEFAULT_BRIEF_PROMPT = """Act as a professional film director and scriptwriter.
Break the following creative brief into a scene-by-scene cinematic script.
Total length: {length} seconds.
Each scene must be between 2 and 8 seconds.

For each scene, provide:
- A detailed visual description for video generation
- Voice-over narration text spoken during the scene
- A music description for background music (genre, tempo, instruments, mood)

For each scene, also provide:
- An enter_transition: how the visuals begin, connecting from the previous scene (omit for the first scene)
- An exit_transition: how the visuals end, leading into the next scene (omit for the last scene)
- A music_transition: how background music should flow from the previous scene — prefer continuing the same track with gradual shifts in intensity/tempo rather than abrupt changes. Use crossfades, dynamic builds, or drops to silence only for dramatic effect. Omit for the first scene.

Also define a global soundtrack_style for the production's overall musical direction.

Creative Brief: {concept}

Return a JSON list of scenes following the requested structure."""

SCENE_ANALYSIS_PROMPT = """You are analyzing this video for smart reframing from 16:9 to 9:16 (portrait).

Your job is to identify SCENES and WHO to focus on in each scene.

FACE TRACK DATA may be provided above — it tells you exactly which faces were detected and their typical horizontal positions (left/center/right). Use the track labels (Track A, Track B, etc.) in your active_subject field when available.

For each scene, provide:
- start_sec and end_sec (timestamps)
- description: what's happening
- active_subject: WHO to focus on. Use one of:
  * A track label: "Track A", "Track B" (preferred when tracks are provided)
  * A spatial hint: "left", "right", "center"
  * "largest" for the most prominent person
- scene_type: one of "dialogue", "action", "close-up", "establishing", "wide", "general"

RULES:
- Cover the entire video with no gaps between scenes
- Scene boundaries should be at camera cuts or significant subject changes
- For dialogue: alternate between the speaking person's track per scene
- For close-ups: use "center" (the face fills the frame)
- For wide/establishing shots: use "center"
- For action: use "largest" to track the most prominent moving subject
- Include t=0 to the final frame"""
