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


# Appended to every video-generation prompt sent to Veo. Veo renders each scene
# literally and in isolation, so it needs an explicit instruction to keep the
# physics coherent (no morphing, floating, clipping, or vanishing props).
PHYSICAL_REALISM_DIRECTIVE = (
    "Maintain strict physical realism: objects stay solid and obey gravity; "
    "nothing morphs into something else, teleports, floats, melts, or appears "
    "or disappears; props being held or handed over remain visible and "
    "consistent; people and objects move around furniture and walls, never "
    "through them. Render one continuous, physically plausible action."
)

# Passed as the Veo `negative_prompt` to suppress the common artifact classes.
VEO_NEGATIVE_PROMPT = (
    "morphing, warping, objects transforming into other objects, shape-shifting, "
    "teleporting, objects or people appearing or disappearing, floating or "
    "levitating objects, objects defying gravity, people or objects passing "
    "through walls or furniture, melting, extra limbs, deformed hands, "
    "distorted faces, duplicated objects, physically impossible motion, flickering"
)

DEFAULT_BRIEF_PROMPT = """Act as a professional film director and scriptwriter.
Break the following creative brief into a scene-by-scene cinematic script.
Total length: {length} seconds.
Each scene must be between 2 and 8 seconds.

PHYSICAL REALISM RULES (critical — each scene is rendered literally and in isolation by the video model):
- Each scene is ONE clear, continuous, physically plausible action. Do not stack multiple distinct actions into a single scene.
- Objects are solid and obey gravity. They never morph into other objects, teleport, melt, float, or appear/disappear mid-scene.
- A prop handed between characters stays visible and consistent throughout the scene.
- Characters and objects move around furniture and walls, never through them.
- If the story needs a "transformation" or a change of object/place, express it as a hard CUT between two separate scenes — never an in-frame morph.

For each scene, provide:
- A detailed visual description for video generation, written as a single coherent action
- Voice-over narration text spoken during the scene
- A music description for background music (genre, tempo, instruments, mood)

For each scene, also provide:
- An enter_transition: a CAMERA or LIGHTING move only (e.g. "slow push-in", "fade up from black", "whip-pan"). Never describe objects changing form. Omit for the first scene.
- An exit_transition: a CAMERA or LIGHTING move only (e.g. "hold then cut", "fade to black"). Never describe objects changing form. Omit for the last scene.
- A music_transition: how background music should flow from the previous scene — prefer continuing the same track with gradual shifts in intensity/tempo rather than abrupt changes. Use crossfades, dynamic builds, or drops to silence only for dramatic effect. Omit for the first scene.

Also define a global soundtrack_style for the production's overall musical direction.

Creative Brief: {concept}

Return a JSON list of scenes following the requested structure."""

SCENE_ANALYSIS_PROMPT = """You are analyzing this video for smart reframing from 16:9 to 9:16 (portrait).

Your job is to identify SCENES and WHO to focus on in each scene.

FACE TRACK DATA may be provided above — it tells you exactly which faces were detected and their typical horizontal positions (left/center/right). Use the track labels (Track A, Track B, etc.) in your active_subject field when available.

DETECTED CUTS may be provided above — scene boundaries are already known. When they
are, label each segment between consecutive cuts; do not invent different boundaries.

For each scene, provide:
- start_sec and end_sec (timestamps)
- description: what's happening
- active_subject: WHO to focus on. Use one of:
  * A track label: "Track A", "Track B" (preferred when tracks are provided)
  * A spatial hint: "left", "right", "center"
  * "largest" for the most prominent person
- scene_type: one of "dialogue", "action", "close-up", "establishing", "wide", "general"
- layout: the spatial layout of essential content:
  * "single" — one subject (default for most shots)
  * "side_by_side" — two subjects far apart that BOTH matter (e.g. interview two-shot)
  * "text_card" — full-width title/logo/credits
  * "slide" — presentation slide or wide graphic
  * "general" — none of the above
- requires_full_width: true ONLY when essential content spans most of the frame width
  (full-width text/logo, slide, wide graphic) so a narrow 9:16 crop would cut it off
- min_horizontal_coverage: fraction of frame WIDTH (0.0-1.0) that must stay visible:
  * ~0.3 for a single centered subject
  * ~0.5-0.6 for two people side by side
  * ~0.9-1.0 for full-width text / slides / wide graphics

RULES:
- Cover the entire video with no gaps between scenes
- Scene boundaries should be at camera cuts or significant subject changes
- For dialogue: alternate between the speaking person's track per scene
- For close-ups: use "center", layout "single", low coverage
- For wide/establishing shots: use "center"
- For action: use "largest" to track the most prominent moving subject
- For on-screen text/logos/slides: set requires_full_width=true and high coverage
- Include t=0 to the final frame"""
