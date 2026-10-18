"""Curated Directorial, Screenplay, and Music presets with O(1) auto-binding resolver."""

from __future__ import annotations

from .models import (
    DirectorPresetSpec,
    MusicPresetSpec,
    ResolvedProductionPresets,
    ScreenplayPresetSpec,
)
from .visual_and_palette import COLOR_PALETTE_PRESETS, VISUAL_STYLE_PRESETS

SCREENPLAY_STYLE_PRESETS: dict[str, ScreenplayPresetSpec] = {
    "algorithmic_wonder": ScreenplayPresetSpec(
        "algorithmic_wonder",
        "Emotional Discovery & Visual Reveal",
        "Step-by-step discovery beats building to a single clear emotional reveal",
        "Structure every scene as a crystal-clear causal chain of discovery: each step shows ONE observable physical action or reaction leading to an emotional reveal.",
    ),
    "operatic_crescendo": ScreenplayPresetSpec(
        "operatic_crescendo",
        "Poetic High-Drama & Ritual",
        "Ceremonial gestures, heightened emotional poise & resonant dramatic dialogue",
        "Write heightened, poetic dialogue and deliberate ceremonial physical steps (posture shifts, gaze turns, sacred object handling) one beat at a time.",
    ),
    "propulsive_puzzle": ScreenplayPresetSpec(
        "propulsive_puzzle",
        "Propulsive Time-Pressure & Precision",
        "Tightly wound cause-and-effect mechanics where every object action advances the clock",
        "Write lean, high-stakes procedural steps where every single physical action on a prop or environment immediately triggers the next causal consequence.",
    ),
    "razor_tension_duel": ScreenplayPresetSpec(
        "razor_tension_duel",
        "Simmering Standoff & Sudden Release",
        "Deliberate micro-actions (setting down a cup, a slow look) building to a sharp turn",
        "Pace the scene through tense, unhurried physical micro-actions (picking up an object, pausing, locking eyes) with sharp, memorable dialogue exchanges.",
    ),
    "minimalist_visual_poem": ScreenplayPresetSpec(
        "minimalist_visual_poem",
        "Austere Visual Behavior & Subtext",
        "Minimal spoken words; story told through precise spatial movement and stillness",
        "Minimize dialogue; express psychology through exact geometric movement, silent pauses, and methodical physical interactions with the environment.",
    ),
    "kinetic_heist_wit": ScreenplayPresetSpec(
        "kinetic_heist_wit",
        "Snappy Relay & Prop Handoff",
        "Brisk domino-effect object handoffs, witty retorts & punchy Cause -> Effect steps",
        "Write brisk domino-effect physical steps where characters pass, grab, or trigger props in rapid, unmistakable sequential order with punchy dialogue.",
    ),
}

MUSIC_STYLE_PRESETS: dict[str, MusicPresetSpec] = {
    "symphonic_leitmotif": MusicPresetSpec(
        "symphonic_leitmotif",
        "Soaring Symphonic Leitmotif & Natural Foley",
        "Warm orchestral strings, French horns, woodwinds & tactile footsteps/breeze",
        "warm symphonic strings, noble French horns, expressive solo woodwinds, orchestral timpani",
        92,
        "Crisp footsteps on terrain, gentle wind/breeze rustling clothing, and tactile prop-handling foley",
    ),
    "classical_grandeur": MusicPresetSpec(
        "classical_grandeur",
        "Opulent Classical Raga, Percussion & Resonant Hall",
        "Sitar/sarangi, bansuri flute, resonant tabla/pakhawaj & echoing temple/palace acoustics",
        "soaring sarangi and bansuri flute, grand sitar, resonant pakhawaj and tabla percussion, choral swells",
        96,
        "Silk garment rustle, jewelry/ankle-bell chime on step, flickering oil-lamp crackle, and courtyard breeze",
    ),
    "braam_shepard_pulse": MusicPresetSpec(
        "braam_shepard_pulse",
        "Ticking Isochronous Pulse & Sub-Bass Tension",
        "Ticking pocket-watch percussion, Shepard-tone strings, low brass & sharp mechanical foley",
        "ticking clockwork percussion, ascending Shepard-tone strings, deep analog synth brass",
        112,
        "Crisp measured footsteps, tense breathing, wind pressure hum, and sharp metallic/object contact clicks",
    ),
    "retro_tension_needle": MusicPresetSpec(
        "retro_tension_needle",
        "Surf-Guitar / Ennio-Style Whistle & Hyper-Real Foley",
        "Twangy tremolo guitar, tense whistle/trumpets & amplified close-mic action foley",
        "tremolo baritone guitar, lone dramatic trumpet, taut upright bass, dry snare rimshots",
        100,
        "Hyper-detailed close-mic foley: boot heels on floor, cloth snap, wind across open space, and sharp prop impact",
    ),
    "hypnotic_minimalist_drone": MusicPresetSpec(
        "hypnotic_minimalist_drone",
        "Classical Minimalist String Sustain & Room Tone",
        "Sustained Ligeti/pendulum strings, deep room tone & isolated precision footsteps",
        "sustained low cello cluster, glacial solo piano notes, deep architectural room resonance",
        72,
        "Stark isolated footsteps echoing in space, subtle room air tone, and deliberate object placement sounds",
    ),
    "percussive_street_funk": MusicPresetSpec(
        "percussive_street_funk",
        "Punchy Breakbeat Bass & Whip-Action SFX",
        "Driving acoustic drums, upright bass riff, handclaps & kinetic whoosh/impact SFX",
        "punchy dry funk drum kit, driving slap upright bass, acoustic guitar stabs, brass hits",
        124,
        "Snappy footsteps, tactile grab/drop foley, quick movement cloth whooshes, and crisp action-focus impacts",
    ),
}

DIRECTOR_STYLE_PRESETS: dict[str, DirectorPresetSpec] = {
    "wonder_spectacle": DirectorPresetSpec(
        "wonder_spectacle",
        "Wonder & Emotional Spectacle",
        "Orchestrated push-ins, awe-struck reaction shots & fluid tracking (e.g., Spielberg-style)",
        "algorithmic_wonder",
        "symphonic_leitmotif",
        "Stage scenes with fluid dolly push-ins into awe-struck reaction close-ups, over-the-shoulder reveals, and clear foreground-to-background staging.",
        35,
        "dolly_in",
    ),
    "operatic_maximalism": DirectorPresetSpec(
        "operatic_maximalism",
        "Operatic Grandeur & Symmetrical Maximalism",
        "Palatial centered compositions, opulent choreography & emotional crescendo (e.g., Bhansali-style)",
        "operatic_crescendo",
        "classical_grandeur",
        "Frame shots with majestic architectural symmetry, rich layered foreground elements (pillars, lamps, curtains), graceful slow-motion movement, and intense emotional close-ups.",
        50,
        "track",
    ),
    "cerebral_imax_tension": DirectorPresetSpec(
        "cerebral_imax_tension",
        "Cerebral Time-Puzzle & Large-Format Tension",
        "Architectural scale, cross-cut momentum & grounded practical realism (e.g., Nolan-style)",
        "propulsive_puzzle",
        "braam_shepard_pulse",
        "Use grounded large-format camera framing, tight tactile insert shots on hands/objects, relentless forward tracking, and strict spatial geography.",
        35,
        "track",
    ),
    "kinetic_wit_chapters": DirectorPresetSpec(
        "kinetic_wit_chapters",
        "Razor-Sharp Tension, Low Angles & Sudden Impact",
        "Lingering suspense holds, trunk/low angles & stylized standoff geometry (e.g., Tarantino-style)",
        "razor_tension_duel",
        "retro_tension_needle",
        "Combine lingering two-shot tension holds with bold low-angle heroic framing, extreme close-ups on eyes and props, and sudden decisive action beats.",
        40,
        "static",
    ),
    "clinical_symmetry": DirectorPresetSpec(
        "clinical_symmetry",
        "Clinical One-Point Perspective & Hypnotic Precision",
        "Dead-center geometry, slow deliberate Steadicam & unblinking framing (e.g., Kubrick-style)",
        "minimalist_visual_poem",
        "hypnotic_minimalist_drone",
        "Enforce mathematical one-point perspective symmetry, unblinking wide-angle geometry, and slow, hypnotic longitudinal dolly movement along the central axis.",
        24,
        "dolly_out",
    ),
    "fast_cut_street_rhythm": DirectorPresetSpec(
        "fast_cut_street_rhythm",
        "Snap-Zoom Kinetic Caper & Hyper-Edited Rhythm",
        "Whip-cuts, visual match-cuts, macro prop inserts & kinetic street rhythm (e.g., Ritchie-style)",
        "kinetic_heist_wit",
        "percussive_street_funk",
        "Use punchy center-framed action beats, crisp macro close-ups on prop handoffs, energetic camera push-ins, and high-momentum visual rhythm.",
        35,
        "dolly_in",
    ),
}

for _alias, _target in (
    ("classical_causal_chain", "algorithmic_wonder"),
    ("poetic_minimalist_ritual", "operatic_crescendo"),
    ("nonlinear_puzzle_convergence", "propulsive_puzzle"),
    ("pressure_cooker_escalation", "razor_tension_duel"),
    ("kinetic_action_relay", "kinetic_heist_wit"),
):
    SCREENPLAY_STYLE_PRESETS[_alias] = SCREENPLAY_STYLE_PRESETS[_target]

for _alias, _target in (
    ("symphonic_leitmotif_natural_foley", "symphonic_leitmotif"),
    ("classical_percussive_ornate_foley", "classical_grandeur"),
    ("pulse_braam_tactile_foley", "braam_shepard_pulse"),
    ("diegetic_drop_hyper_foley", "retro_tension_needle"),
    ("minimalist_ambient_hyper_real_foley", "hypnotic_minimalist_drone"),
    ("rhythmic_percussive_action_sfx", "percussive_street_funk"),
):
    MUSIC_STYLE_PRESETS[_alias] = MUSIC_STYLE_PRESETS[_target]

for _alias, _target in (
    ("wonder_humanist_blocking", "wonder_spectacle"),
    ("opulent_operatic_tableau", "operatic_maximalism"),
    ("architectural_tension_realism", "cerebral_imax_tension"),
    ("razor_tension_crash_zoom", "kinetic_wit_chapters"),
    ("one_point_geometric_precision", "clinical_symmetry"),
    ("kinetic_montage_whip_pan", "fast_cut_street_rhythm"),
):
    DIRECTOR_STYLE_PRESETS[_alias] = DIRECTOR_STYLE_PRESETS[_target]


def resolve_production_presets(
    visual_style_id: str | None = None,
    color_palette_id: str | None = None,
    director_style_id: str | None = None,
    screenplay_style_id: str | None = None,
    music_style_id: str | None = None,
) -> ResolvedProductionPresets:
    """Resolve Visual Style, Color Palette, and Director preset (with O(1) auto-bound Screenplay & Music)."""
    vis = VISUAL_STYLE_PRESETS.get(
        visual_style_id or "pixar_3d", VISUAL_STYLE_PRESETS["pixar_3d"]
    )
    pal = COLOR_PALETTE_PRESETS.get(
        color_palette_id or "warm_golden_amber",
        COLOR_PALETTE_PRESETS["warm_golden_amber"],
    )
    dir_spec = DIRECTOR_STYLE_PRESETS.get(
        director_style_id or "wonder_spectacle",
        DIRECTOR_STYLE_PRESETS["wonder_spectacle"],
    )
    sw_spec = SCREENPLAY_STYLE_PRESETS.get(
        screenplay_style_id or dir_spec.bound_screenplay_preset,
        SCREENPLAY_STYLE_PRESETS[dir_spec.bound_screenplay_preset],
    )
    mus_spec = MUSIC_STYLE_PRESETS.get(
        music_style_id or dir_spec.bound_music_preset,
        MUSIC_STYLE_PRESETS[dir_spec.bound_music_preset],
    )
    combined_palette = list(
        dict.fromkeys([*pal.palette_keywords, *vis.default_palette[:2]])
    )
    combined_lighting = f"{vis.lighting_rules}. {pal.lighting_tint}."
    return ResolvedProductionPresets(
        visual_style=vis,
        color_palette=pal,
        director_style=dir_spec,
        screenplay_style=sw_spec,
        music_style=mus_spec,
        combined_palette=combined_palette,
        combined_lighting_rules=combined_lighting,
    )
