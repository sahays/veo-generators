"""Content-type-aware reframe strategies.

Maps each content type to prompt template variables and processing parameters.
A single base prompt template is filled with per-type variable values.
"""

from typing import Tuple

# ---------------------------------------------------------------------------
# Base prompt template — variables are filled per content type
# ---------------------------------------------------------------------------

BASE_REFRAME_PROMPT_TEMPLATE = """You are a professional video editor analyzing this video for smart reframing \
from 16:9 (landscape) to 9:16 (portrait).

CONTENT TYPE: {content_description}

FOCAL STRATEGY: {focal_strategy}

SAMPLING: {sampling_instructions}

AUDIO: {audio_instructions}

FRAMING: {framing_priority}

For each focal point, provide:
- time_sec: the timestamp in seconds (use decimals, e.g. 1.5)
- x: horizontal position of the subject center as a fraction \
(0.0 = left edge, 0.5 = center, 1.0 = right edge)
- y: vertical position of the subject center as a fraction \
(0.0 = top edge, 0.5 = center, 1.0 = bottom edge)
- confidence: how confident you are (0.0-1.0) that this is the right focal point
- description: brief description of what the subject is \
(e.g. "speaker's face", "product close-up")

Also identify scene changes (cuts, transitions) with their timestamps.

RULES:
- Always include t=0 and the final frame
- Sample at LEAST every 2 seconds — more frequently during action or dialogue
- x values matter most for 16:9 → 9:16 (horizontal positioning)
- NEVER default to x=0.5 unless the subject is truly centered. Look carefully at WHERE in the frame the subject is
- Be precise: a face at the left-third is x≈0.33, center is x≈0.5, right-third is x≈0.67
- A two-person conversation typically has speakers at x≈0.3 and x≈0.7, NOT both at x≈0.5
{extra_rules}"""

# ---------------------------------------------------------------------------
# Variable values per content type
# ---------------------------------------------------------------------------

CONTENT_TYPE_VARIABLES: dict[str, dict[str, str]] = {
    "movies": {
        "content_description": "Movie, film, or scripted drama",
        "focal_strategy": (
            "Follow the STORY — track the character or element driving the "
            "narrative in each shot. During dialogue, center on the speaking "
            "character. During non-dialogue scenes (action, establishing shots, "
            "reactions), track the key character or visual subject on screen."
        ),
        "sampling_instructions": (
            "Sample at each scene cut and at significant subject movement. "
            "Within a static shot, 1-2 points are enough. "
            "During action or chase sequences, sample every 0.5-1s."
        ),
        "audio_instructions": (
            "Listen for dialogue — center on the speaking character. "
            "During non-dialogue, focus on the key character or visual "
            "subject on screen. Music cues and sound effects can indicate "
            "where the action is."
        ),
        "framing_priority": (
            "Respect the cinematographer's framing intent. "
            "Favor the visual center of interest in each shot. "
            "Preserve rule-of-thirds composition where possible."
        ),
        "extra_rules": (
            "- Scene cuts should be precise — each cut resets framing\n"
            "- Respect rule-of-thirds positioning in cinematic shots\n"
            "- During close-ups, keep the face centered\n"
            "- During wide establishing shots with no clear subject, use x=0.5"
        ),
    },
    "documentaries": {
        "content_description": "Documentary, educational, or informational content",
        "focal_strategy": (
            "Track the primary subject — narrator on camera, interview "
            "subject, or the object/scene being discussed. When b-roll is "
            "shown, follow the visual focus that illustrates the narration."
        ),
        "sampling_instructions": (
            "Sample at each scene cut and when the visual focus shifts. "
            "During talking-head segments, hold steady on the speaker. "
            "During b-roll montages, sample every 1-2s."
        ),
        "audio_instructions": (
            "Listen to the narration or interview audio. Center on whoever "
            "is speaking when they are on camera. During voice-over with "
            "b-roll, track the visual subject being described."
        ),
        "framing_priority": (
            "Keep the on-camera speaker centered during interviews. "
            "During b-roll, favor the visual subject that matches the "
            "narration. Smooth, slow panning — no abrupt movements."
        ),
        "extra_rules": (
            "- For interview segments, center on the person speaking\n"
            "- For b-roll, track the most relevant visual element\n"
            "- For text/graphics overlays, center the frame on the text\n"
            "- Wide landscape shots: use x=0.5"
        ),
    },
    "sports": {
        "content_description": "Live sports, highlights, or athletic footage",
        "focal_strategy": (
            "Track the PRIMARY ACTION — the ball, active player, "
            "or main point of interest. During plays, follow the ball. "
            "During replays or slow-motion, track the highlighted subject."
        ),
        "sampling_instructions": (
            "Sample every 0.25-0.5s during fast movement. "
            "Less frequently during pauses, timeouts, or replays. "
            "During celebrations or crowd shots, sample every 1-2s."
        ),
        "audio_instructions": (
            "Audio is secondary. Focus on visual motion. "
            "Commentary may hint at key players but visual tracking "
            "takes priority."
        ),
        "framing_priority": (
            "Keep the action visible. Fast panning is acceptable. "
            "Prioritize not losing the ball/play over smooth movement."
        ),
        "extra_rules": (
            "- Prioritize ball/puck over individual players\n"
            "- During replays, track the highlighted subject\n"
            "- Wide shots: use x=0.5\n"
            "- Scoreboards/graphics: briefly center on them if prominent"
        ),
    },
    "podcasts": {
        "content_description": "Podcast, interview, talk show, or panel discussion",
        "focal_strategy": (
            "Track the ACTIVE SPEAKER — the person currently talking. "
            "When speakers overlap, prefer the one facing the camera. "
            "During silence or non-speech moments, track the person "
            "reacting or most visually prominent on screen."
        ),
        "sampling_instructions": (
            "Sample at each SPEAKER CHANGE. Hold steady during a single "
            "speaker's turn — do NOT add extra points while the same person "
            "is talking. Only add points when the active speaker switches "
            "or the camera cuts. During silent moments, sample every 1-2s."
        ),
        "audio_instructions": (
            "LISTEN to the audio carefully. Identify who is speaking by "
            "correlating voice with lip movement and gestures. The audio "
            "track is your PRIMARY signal for who to focus on. "
            "When no one is speaking, rely on visual cues."
        ),
        "framing_priority": (
            "Keep the active speaker's face centered in the 9:16 crop. "
            "Smooth, slow pans between speakers. "
            "Never cut abruptly unless the camera angle changes."
        ),
        "extra_rules": (
            "- For multi-person shots, ALWAYS center on whoever is speaking\n"
            "- If no one is speaking, focus on the person reacting or most "
            "visually prominent\n"
            "- Mark camera angle changes as scene_changes\n"
            "- A 2-person setup typically has speakers at x≈0.3 and x≈0.7"
        ),
    },
    "promos": {
        "content_description": "Promotional video, advertisement, or product showcase",
        "focal_strategy": (
            "Track the PRODUCT or KEY MESSAGE — the item being showcased, "
            "the presenter, or the brand element that is the focus of each "
            "shot. Alternate between product close-ups and presenter."
        ),
        "sampling_instructions": (
            "Sample at each scene cut. Promos are fast-paced with many cuts "
            "— ensure a focal point at every transition. Within a shot, "
            "1-2 points are enough unless the subject moves."
        ),
        "audio_instructions": (
            "Listen for voice-over or presenter speech. Center on the "
            "presenter when speaking on camera. During product shots with "
            "voice-over, track the product being described."
        ),
        "framing_priority": (
            "Keep the product or presenter centered. Prioritize brand "
            "elements and text overlays being visible in the 9:16 crop. "
            "Fast, punchy transitions are acceptable."
        ),
        "extra_rules": (
            "- Always keep text/logo overlays visible in the crop\n"
            "- Center on the product during product shots\n"
            "- Center on the presenter during talking-head shots\n"
            "- For end cards with branding, use x=0.5"
        ),
    },
    "news": {
        "content_description": "News broadcast, anchor desk, or field reporting",
        "focal_strategy": (
            "Track the ANCHOR or REPORTER — the person delivering the news. "
            "During field reports, follow the reporter. During b-roll with "
            "voice-over, track the visual subject being reported on."
        ),
        "sampling_instructions": (
            "Sample at each camera switch (anchor to field, to b-roll, etc). "
            "During anchor desk segments, hold steady — minimal sampling. "
            "During field reports with movement, sample every 1-2s."
        ),
        "audio_instructions": (
            "Listen to identify who is speaking — anchor, reporter, or "
            "interviewee. Center on the active speaker when on camera. "
            "During voice-over b-roll, track the visual subject."
        ),
        "framing_priority": (
            "Keep the speaking person centered. News anchors are typically "
            "centered already. Field reporters may be off-center — track "
            "them precisely. Lower-third graphics should remain visible."
        ),
        "extra_rules": (
            "- Keep lower-third name/title graphics visible in the crop\n"
            "- Anchor desk: usually center (x≈0.5)\n"
            "- Split-screen interviews: center on the active speaker\n"
            "- For maps/graphics, center the frame on the graphic"
        ),
    },
    "other": {
        "content_description": "General video content",
        "focal_strategy": (
            "Track the most visually important subject the viewer's eye "
            "would be drawn to. Prioritize people over objects, and active "
            "subjects over static ones."
        ),
        "sampling_instructions": (
            "Sample every 0.5-1s. More frequently during movement, "
            "less during static shots."
        ),
        "audio_instructions": (
            "Use audio as a secondary cue to identify active subjects. "
            "If someone is speaking, center on them."
        ),
        "framing_priority": (
            "Balance between tracking the subject and maintaining stable "
            "framing. Avoid excessive panning."
        ),
        "extra_rules": (
            "- When multiple subjects are present, pick the active one "
            "(speaking, moving, in focus)\n"
            "- For wide establishing shots, use x=0.5"
        ),
    },
}

# ---------------------------------------------------------------------------
# Processing strategy per content type
# ---------------------------------------------------------------------------

STRATEGY_CONFIG: dict[str, dict] = {
    "movies": {
        "cv_strategy": "face",
        "max_velocity": 0.15,
        "deadzone": 0.05,
        "use_diarization": False,
    },
    "documentaries": {
        "cv_strategy": "multi_face",
        "max_velocity": 0.12,
        "deadzone": 0.06,
        "use_diarization": True,
    },
    "sports": {
        "cv_strategy": "motion",
        "max_velocity": 0.50,
        "deadzone": 0.02,
        "use_diarization": False,
    },
    "podcasts": {
        "cv_strategy": "multi_face",
        "max_velocity": 0.10,
        "deadzone": 0.08,
        "use_diarization": True,
    },
    "promos": {
        "cv_strategy": "face",
        "max_velocity": 0.20,
        "deadzone": 0.04,
        "use_diarization": False,
    },
    "news": {
        "cv_strategy": "multi_face",
        "max_velocity": 0.12,
        "deadzone": 0.06,
        "use_diarization": True,
    },
    "other": {
        "cv_strategy": "face",
        "max_velocity": 0.15,
        "deadzone": 0.05,
        "use_diarization": True,
    },
}


def get_strategy(content_type: str) -> dict:
    """Return processing strategy config for the given content type."""
    return STRATEGY_CONFIG.get(content_type, STRATEGY_CONFIG["other"])


def get_variables(content_type: str) -> dict[str, str]:
    """Return prompt template variables for the given content type."""
    return CONTENT_TYPE_VARIABLES.get(content_type, CONTENT_TYPE_VARIABLES["other"])


def resolve_prompt(content_type: str) -> Tuple[str, dict[str, str]]:
    """Render the base prompt template with content-type variables.

    Returns:
        (rendered_prompt, variables_dict) — the prompt string and the
        variable values used, so they can be stored on the record.
    """
    variables = get_variables(content_type)
    prompt = BASE_REFRAME_PROMPT_TEMPLATE.format(**variables)
    return prompt, variables
