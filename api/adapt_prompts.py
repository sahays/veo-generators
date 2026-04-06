"""Adapt prompt template and per-ratio metadata for image adaptation."""

# ---------------------------------------------------------------------------
# Adapt prompt template — variables filled per generation call
# ---------------------------------------------------------------------------

ADAPT_PROMPT_TEMPLATE = """\
You are a professional creative asset producer creating a {aspect_ratio} adapt \
of the provided source image for {use_case}.

TARGET: {aspect_ratio} ({orientation} format, {dimension_description})

STEP 1 — ANALYZE THE SOURCE IMAGE:
Before generating anything, carefully identify and catalog every element:
- PEOPLE: faces, full bodies, hands, poses, expressions, skin tones, hair
- TEXT: every piece of text — titles, subtitles, taglines, logos with text, \
credits, dates, ratings, call-to-action labels. Note the exact wording, font \
style (bold, italic, serif, sans-serif), color, size relative to the image, \
and position (top, center, bottom, overlaid on subject, etc.)
- BRANDING: logos, icons, watermarks, channel bugs, network identifiers
- KEY OBJECTS: products, props, vehicles, weapons, instruments, food — anything \
that tells the story or sells the concept
- BACKGROUND: scenery, environment, gradients, patterns, textures, sky, interior
- VISUAL STYLE: color grading, lighting direction, contrast, saturation, mood, \
film grain or clean digital look, any overlays or effects (light leaks, bokeh)
- LAYOUT: how elements are arranged relative to each other — who/what is in \
front, behind, left, right; any layering or depth

STEP 2 — PLAN THE NEW COMPOSITION:
{objective}
- Decide where each element from Step 1 goes in the {aspect_ratio} frame
- People MUST remain the same — same face, same expression, same pose, same \
clothing, same skin tone. Do NOT alter, age, or replace any person.
- Text MUST be reproduced exactly — same wording, same language. Reposition \
and resize text to fit the new layout but NEVER change the words, drop words, \
or invent new text. If the source says "STRANGER THINGS" the output must say \
"STRANGER THINGS" — not a paraphrase, not a translation.
- Logos and branding MUST be reproduced faithfully in shape, color, and proportion

STEP 3 — GENERATE THE ADAPTED IMAGE:

COMPOSITION RULES:
- {composition_primary}
- Reconstruct the scene in the new aspect ratio — this is a new composition, \
not a crop. Extend backgrounds, environments, or negative space as needed.
- Maintain the EXACT visual style: same color grading, lighting, contrast, \
saturation, film look, and mood as the source
- All people must be fully visible — do NOT crop out faces, limbs, or bodies
- All text must be fully legible — resize proportionally if needed but keep \
every word intact and readable
- All logos and brand marks must be fully visible and correctly proportioned
- Preserve the visual hierarchy: if a person is the hero, they stay the hero; \
if a title is prominent, it stays prominent

TEXT FIDELITY (CRITICAL):
- Copy text character-for-character from the source image
- Maintain the original language — do NOT translate
- Preserve font style (bold, thin, condensed, decorative) as closely as possible
- Keep text color and any text effects (shadow, outline, glow) consistent
- If text overlays a subject, maintain that overlay relationship
- If text is in a banner or box, recreate that container

PEOPLE FIDELITY (CRITICAL):
- Every person in the source must appear in the output
- Same face, same features, same expression, same hair, same clothing
- Same pose and body positioning relative to other elements
- Same skin tone and lighting on skin — no alterations
- If multiple people are present, maintain their spatial relationship to each other

HANDLING EXTREME RATIOS:
- {extreme_ratio_guidance}

{template_instructions}

OUTPUT: A single high-quality image at {aspect_ratio} that looks like it was \
intentionally designed as an original asset for this format. It must contain \
every person, every word of text, every logo, and every key object from the \
source — faithfully reproduced, not approximated."""


RATIO_META: dict[str, dict[str, str]] = {
    "1:1": {
        "orientation": "square",
        "dimension_description": "equal width and height",
        "use_case": "social media profiles, app icons, and grid layouts",
        "composition_primary": "Center the key subject; use symmetrical or radial balance",
        "extreme_ratio_guidance": "Standard ratio — no extreme adjustments needed",
    },
    "16:9": {
        "orientation": "landscape",
        "dimension_description": "wide cinematic frame",
        "use_case": "TV screens, desktop banners, YouTube thumbnails, and OTT hero images",
        "composition_primary": "Use the full width; place subjects using rule-of-thirds horizontally",
        "extreme_ratio_guidance": "Standard ratio — no extreme adjustments needed",
    },
    "9:16": {
        "orientation": "portrait",
        "dimension_description": "tall vertical frame",
        "use_case": "mobile stories, reels, TikTok, and vertical digital signage",
        "composition_primary": "Stack elements vertically; place the hero subject in the upper two-thirds",
        "extreme_ratio_guidance": "Standard ratio — no extreme adjustments needed",
    },
    "4:3": {
        "orientation": "landscape",
        "dimension_description": "classic broadcast ratio",
        "use_case": "tablets, presentations, and traditional print",
        "composition_primary": "Slightly tighter than 16:9; keep subjects within the center 80%",
        "extreme_ratio_guidance": "Standard ratio — no extreme adjustments needed",
    },
    "3:4": {
        "orientation": "portrait",
        "dimension_description": "classic portrait ratio",
        "use_case": "book covers, portrait prints, and product packaging",
        "composition_primary": "Favor vertical arrangement; keep the main subject in the upper half",
        "extreme_ratio_guidance": "Standard ratio — no extreme adjustments needed",
    },
    "4:5": {
        "orientation": "portrait",
        "dimension_description": "near-square vertical",
        "use_case": "Instagram feed posts and portrait advertisements",
        "composition_primary": "Tightly frame the subject; minimal wasted space top and bottom",
        "extreme_ratio_guidance": "Standard ratio — no extreme adjustments needed",
    },
    "5:4": {
        "orientation": "landscape",
        "dimension_description": "near-square horizontal",
        "use_case": "large-format prints and monitor displays",
        "composition_primary": "Balanced framing; center the subject with even margins",
        "extreme_ratio_guidance": "Standard ratio — no extreme adjustments needed",
    },
    "2:3": {
        "orientation": "portrait",
        "dimension_description": "standard photo portrait",
        "use_case": "photo prints (4x6), movie posters, and magazine covers",
        "composition_primary": "Classic portrait framing; subject in the upper 60% with bottom space for text",
        "extreme_ratio_guidance": "Standard ratio — no extreme adjustments needed",
    },
    "3:2": {
        "orientation": "landscape",
        "dimension_description": "standard photo landscape",
        "use_case": "photo prints, DSLR native ratio, and landscape photography",
        "composition_primary": "Natural landscape framing; use full width with rule-of-thirds",
        "extreme_ratio_guidance": "Standard ratio — no extreme adjustments needed",
    },
    "21:9": {
        "orientation": "ultra-wide landscape",
        "dimension_description": "cinematic ultra-wide (2.33:1)",
        "use_case": "ultra-wide monitors, cinema displays, and panoramic banners",
        "composition_primary": "Spread subjects across the width; use the extra horizontal space for environmental context",
        "extreme_ratio_guidance": (
            "Very wide — extend backgrounds and environment horizontally. "
            "Never stretch the subject. Add contextual scenery to fill width naturally."
        ),
    },
    "1:4": {
        "orientation": "extreme portrait",
        "dimension_description": "very tall, narrow vertical strip",
        "use_case": "vertical banners, skyscraper ads, and tall digital signage",
        "composition_primary": "Stack the subject and supporting elements in a strong vertical flow",
        "extreme_ratio_guidance": (
            "Extremely tall — arrange elements in a vertical column. "
            "Place the hero subject at the visual center and extend the background above and below. "
            "Avoid cramming; use the height for visual storytelling."
        ),
    },
    "4:1": {
        "orientation": "extreme landscape",
        "dimension_description": "very wide horizontal strip",
        "use_case": "website headers, leaderboard ads, and panoramic banners",
        "composition_primary": "Spread elements horizontally; use repeating rhythm or panoramic context",
        "extreme_ratio_guidance": (
            "Extremely wide — extend backgrounds and scenery horizontally. "
            "Keep the subject compact in the center and fill sides with relevant environment. "
            "Think of a panoramic vista, not a stretched image."
        ),
    },
    "1:8": {
        "orientation": "extreme portrait",
        "dimension_description": "ultra-tall narrow column",
        "use_case": "tall skyscraper ads and narrow vertical signage",
        "composition_primary": "Use a bold vertical composition with the subject centered",
        "extreme_ratio_guidance": (
            "Ultra-tall — isolate the key subject vertically and extend with "
            "complementary gradients, patterns, or environment above and below. "
            "This is almost a column; keep the subject narrow and let the format breathe."
        ),
    },
    "8:1": {
        "orientation": "extreme landscape",
        "dimension_description": "ultra-wide horizontal strip",
        "use_case": "ticker-style banners and ultra-wide panoramic displays",
        "composition_primary": "Minimal vertical content; spread a panoramic scene horizontally",
        "extreme_ratio_guidance": (
            "Ultra-wide — create a panoramic scene. Keep the subject compact in center "
            "and extend scenery or a complementary environment to the sides. "
            "Think landscape photograph, not a cropped image."
        ),
    },
}

DEFAULT_RATIO_META = {
    "orientation": "custom",
    "dimension_description": "custom aspect ratio",
    "use_case": "multi-platform distribution",
    "composition_primary": "Center the key subject and recompose naturally for the target dimensions",
    "extreme_ratio_guidance": "Adapt the composition intelligently; preserve all key elements",
}


def adapt_prompt_variables(
    aspect_ratio: str, template_gcs_uri: str | None
) -> dict[str, str]:
    """Build placeholder variables for the adapt prompt template."""
    meta = RATIO_META.get(aspect_ratio, DEFAULT_RATIO_META)

    if template_gcs_uri:
        template_instructions = (
            "TEMPLATE GUIDE:\n"
            "A layout template image is also provided. Use it as a composition reference:\n"
            "- Follow its safe zones, text placement areas, and visual hierarchy\n"
            "- Place the source image's key elements within the template's active areas\n"
            "- Respect any margins or gutters indicated by the template"
        )
    else:
        template_instructions = ""

    w, h = aspect_ratio.split(":")
    w_int, h_int = int(w), int(h)
    if w_int > h_int:
        objective = (
            "Recompose the source image into a wider format. Extend the scene "
            "horizontally with coherent background, environment, or context that "
            "matches the source's visual style. Do NOT stretch or distort the subject."
        )
    elif h_int > w_int:
        objective = (
            "Recompose the source image into a taller format. Extend the scene "
            "vertically with coherent background, environment, or context that "
            "matches the source's visual style. Do NOT stretch or distort the subject."
        )
    else:
        objective = (
            "Recompose the source image into a square format. Tighten or balance "
            "the framing to work as a square, keeping the main subject prominent "
            "and centered. Do NOT stretch or distort the subject."
        )

    return {
        "aspect_ratio": aspect_ratio,
        "orientation": meta["orientation"],
        "dimension_description": meta["dimension_description"],
        "use_case": meta["use_case"],
        "objective": objective,
        "composition_primary": meta["composition_primary"],
        "extreme_ratio_guidance": meta["extreme_ratio_guidance"],
        "template_instructions": template_instructions,
    }
