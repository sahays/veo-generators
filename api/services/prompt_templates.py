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


# Appended to every video-generation prompt sent to Veo/Omni. Each scene is
# rendered literally and in isolation, so it needs explicit rules for physics,
# anatomy, prop contact, and speaker lip-sync attribution.
PHYSICAL_REALISM_DIRECTIVE = (
    "Maintain strict physical and anatomical realism: objects stay solid and obey gravity; "
    "held props (rings, staffs, scrolls, cups) must rest firmly inside the palm with fingers "
    "physically gripping them — never floating, hovering, or detached in mid-air; "
    "anatomical invariants are strict (each person/deity has two arms and two hands unless explicitly specified, "
    "and monkey/vanara characters like Hanuman have strictly ONE monkey tail, never two tails); "
    "silent listeners and background characters keep their mouths closed and never lip-sync "
    "another character's monologue or off-screen voice-over; "
    "persistent environmental states (such as dramatic golden firelight, glowing embers, and atmospheric smoke) remain "
    "visibly present across the entire shot. Render one continuous, physically plausible action."
)

# Passed as the Veo `negative_prompt` to suppress the common artifact classes.
VEO_NEGATIVE_PROMPT = (
    "morphing, warping, objects transforming into other objects, shape-shifting, "
    "teleporting, objects or people appearing or disappearing, floating or "
    "levitating objects, floating ring in hand, hovering props not touching palm, "
    "objects defying gravity, people or objects passing through walls or furniture, "
    "melting, extra limbs, two tails, multiple tails, duplicate tails, deformed hands, "
    "wrong character speaking, silent listener moving mouth during voice-over, "
    "distorted faces, duplicated objects, physically impossible motion, flickering"
)

STORYBOARD_REVIEWER_PROMPT = """You are a Strict Film Continuity, Physics, Anatomy & Audio Script Supervisor.
Review the entire multi-scene storyboard below as a unified film. Look for any continuity flaws, ambiguities, or prompt phrasings that cause AI video generators (Veo / Gemini Omni) to produce vibe-killing hallucinations, and REWRITE the continuity block and scenes to eliminate them.

Specifically audit and fix ALL 6 categories across the entire storyboard:
1. SPEECH & MONOLOGUE ATTRIBUTION (`speech_speaker`):
   - Check every scene's `narration` and `visual_description`.
   - Never allow ambiguity about WHO is speaking. For example, if Jamvant is delivering a monologue to Hanuman, the prompt MUST explicitly state in `visual_description` and `speaker_notes` that "Jamvant speaks on-screen with expressive mouth movement while Hanuman listens attentively with his mouth firmly closed (Hanuman does NOT speak or move his mouth)".
   - If `narration` is an off-screen narrator/voice-over, set `speaker_notes` to "Off-screen voice-over narrator only; all on-screen characters keep their mouths closed and do NOT lip-sync".
2. PROP & HAND CONTACT PHYSICS (`prop_physics`):
   - Check every held, carried, or transferred object (e.g., a signet ring in Hanuman's hand, a mace, weapon, or vessel).
   - Video models frequently hallucinate small objects floating above open palms. Rewrite `visual_description` to enforce explicit physical contact: e.g., "the gold ring rests flat against the center of Hanuman's palm with his fingers curled firmly around it in solid physical contact — never floating or hovering".
3. CHARACTER ANATOMY & CONSISTENCY (`character_anatomy`):
   - Enforce strict anatomical invariants in `continuity.characters` AND in every scene where the character appears.
   - For tailed or mythological characters (e.g., Hanuman, vanaras, creatures), explicitly state "with strictly ONE single monkey tail (never two tails), two arms, and two hands" and keep wardrobe, jewelry, and facial features identical across all scenes.
4. ENVIRONMENTAL & WORLD-STATE CONTINUITY (`environment_continuity`):
   - Remember that each scene clip is generated in isolation! If an environmental state is established (e.g., Lanka illuminated by dramatic firelight, a storm raging, nightfall, atmospheric smoke), every subsequent scene in that location MUST explicitly repeat the active environment in `visual_description` (e.g., "surrounded by dramatic golden-orange firelight, glowing embers, and atmospheric smoke across the ancient palace towers of Lanka") so the environment never disappears between cuts.
   - IMPORTANT RESPONSIBLE AI SAFETY RULE: Keep all visual descriptions theatrical, mythological, and cinematic — avoid graphic violence, gore, real-world terrorism/arson phrasing, or destructive harm terms that could trigger automated safety filters (`content_blocked`).
5. ACTION DENSITY & TRANSITIONS (`transition_action`):
   - Ensure each scene describes ONE clear, continuous physical action with a distinct opening pose (start frame) and closing pose (end frame) that fits naturally within its 4-8 second duration.
6. AUDIO & MUSIC FLOW (`audio_music`):
   - Ensure `music_description` and `music_transition` maintain a cohesive musical arc and instrumentation across all scenes without jarring genre resets.

Preserve the exact number of scenes and their `timestamp_start` / `timestamp_end` timings. Return the complete JSON matching the requested schema."""

FINISHED_VIDEO_EVAL_PROMPT = """You are a Strict Multimodal Film Quality & Continuity Evaluator.
Watch the rendered video(s) carefully alongside the intended storyboard specification below.
Your job is to inspect the ACTUAL rendered video frames and audio track for vibe-killing inconsistencies and hallucinations across all scenes:

1. SPEECH & LIP-SYNC ATTRIBUTION (`speech_speaker`):
   - Did the wrong character start speaking or moving their mouth during another character's monologue or off-screen voice-over (e.g., Hanuman speaking Jamvant's monologue)?
2. PROP & OBJECT PHYSICS (`prop_physics`):
   - Are any held props floating, hovering in mid-air, detached from the character's hand/palm (e.g., a ring floating above Hanuman's hand), morphing, or vanishing?
3. CHARACTER ANATOMY & IDENTITY (`character_anatomy`):
   - Does any character have extra limbs, deformed hands, or duplicate tails (e.g., Hanuman having two tails instead of strictly one tail), or sudden wardrobe/appearance shifts between shots?
4. ENVIRONMENTAL & WORLD-STATE CONTINUITY (`environment_continuity`):
   - Did critical environmental elements disappear across cuts (e.g., no fire or smoke in Lanka when Lanka is supposed to be burning)?
5. ACTION & TRANSITION COHERENCE (`transition_action`):
   - Are there jarring visual glitches, impossible motion, or broken transitions between scenes?
6. AUDIO & MUSIC COHERENCE (`audio_music`):
   - Is the speech clear, properly timed, and free of conflicting voices or abrupt audio cutoffs?

INSTRUCTIONS FOR YOUR VERDICT:
- Be strict. If you observe ANY critical inconsistency in a scene, set `passed` to `false`.
- For each defective scene, add an entry in `findings` with its 1-based `scene_number`:
  - Set `regenerate_frame = true` if the defect is already visible in the static composition/anatomy/environment (e.g., two tails in the pose, missing fire in the background, wrong character setup) so the keyframe image is regenerated too.
  - Set `regenerate_video = true` so the video clip is regenerated.
  - Provide a concrete `corrected_visual_description` and `corrected_speaker_notes` that explicitly forbid the observed hallucination and enforce the right physics, anatomy, environment, and speaker behavior.
- If all scenes look and sound consistent with the storyboard and physical realism rules, set `passed = true` and `findings = []`."""

DEFAULT_BRIEF_PROMPT = """Act as a professional film director and scriptwriter.
Break the following creative brief into a scene-by-scene cinematic script.
Total length: {length} seconds.
Each scene must be between 2 and 8 seconds.

PHYSICAL REALISM & CONTINUITY RULES (critical — each scene is rendered literally and in isolation by the video model):
- Each scene is ONE clear, continuous, physically plausible action. Do not stack multiple distinct actions into a single scene.
- Objects are solid and obey gravity. Held props (rings, weapons, tools) must rest firmly in the palm with fingers gripping them — never floating or hovering.
- Enforce strict character anatomy (e.g., monkey/vanara characters like Hanuman have strictly ONE tail, two arms, two hands) and repeat ongoing environmental states (such as active fire and smoke in Lanka) in every scene set in that location.
- Clearly specify `speaker_notes` for every scene: state who speaks on-screen vs. who listens with their mouth closed vs. off-screen narrator voice-over.
- If the story needs a transformation or a change of object/place, express it as a hard CUT between two separate scenes — never an in-frame morph.

For each scene, provide:
- A detailed visual description for video generation, written as a single coherent action
- Voice-over narration text spoken during the scene
- speaker_notes: explicit rule on whose mouth moves vs. who keeps their mouth closed
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
