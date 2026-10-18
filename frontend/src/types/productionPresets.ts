import type { ProjectType } from './project'

export interface CreativePresetOption {
  id: string
  label: string
  category: string
  shortDescription: string
  boundScreenplayId?: string
  boundScreenplayLabel?: string
  boundMusicId?: string
  boundMusicLabel?: string
  swatches?: string[]
}

export interface ModeFormatProfile {
  type: ProjectType
  title: string
  subtitle: string
  defaultOrientation: '16:9' | '9:16'
  allowedOrientations: ('16:9' | '9:16')[]
  defaultDuration: string
  indicativeDurations: { value: string; label: string; tag: string }[]
  durationNote: string
}

export const MODE_FORMAT_PROFILES: Record<ProjectType, ModeFormatProfile> = {
  movie: {
    type: 'movie',
    title: 'Cinematic Film',
    subtitle: 'Long-form widescreen narrative storytelling (1m to 3m+)',
    defaultOrientation: '16:9',
    allowedOrientations: ['16:9'],
    defaultDuration: '120',
    indicativeDurations: [
      { value: '60', label: '1m', tag: 'Short Act' },
      { value: '120', label: '2m', tag: 'Feature Sequence' },
      { value: '180', label: '3m+', tag: 'Extended Cinema' },
    ],
    durationNote: 'Indicative pacing target — story depth & algorithmic scene steps determine final film length.',
  },
  advertizement: {
    type: 'advertizement',
    title: 'Commercial / Ad Spot',
    subtitle: 'High-impact brand & product spot (up to 30s)',
    defaultOrientation: '16:9',
    allowedOrientations: ['16:9', '9:16'],
    defaultDuration: '30',
    indicativeDurations: [
      { value: '15', label: '15s', tag: 'Bumper / Hook' },
      { value: '30', label: '30s', tag: 'Standard Broadcast' },
    ],
    durationNote: 'Indicative spot cap (up to 30s) — hook, product reveal & CTA beats pace the exact cut.',
  },
  social: {
    type: 'social',
    title: 'Social Story / Reel',
    subtitle: 'Vertical or widescreen creator story (30s to 1m+)',
    defaultOrientation: '9:16',
    allowedOrientations: ['9:16', '16:9'],
    defaultDuration: '60',
    indicativeDurations: [
      { value: '30', label: '30s', tag: 'Fast Reel' },
      { value: '60', label: '1m', tag: 'Story Arc' },
      { value: '90', label: '1.5m+', tag: 'Deep Dive' },
    ],
    durationNote: 'Indicative duration — content momentum & character interactions decide final reel length.',
  },
}

export const VISUAL_STYLE_PRESETS_UI: CreativePresetOption[] = [
  {
    id: 'pixar_3d',
    label: '3D Feature Animation',
    category: '3D & Toy',
    shortDescription: 'Tactile subsurface skin, expressive eyes & warm Pixar-grade global illumination',
  },
  {
    id: 'lego_brick',
    label: 'Lego Brick Animation',
    category: '3D & Toy',
    shortDescription: 'Interlocking ABS plastic bricks, glossy minifigures & stop-motion micro-scratches',
  },
  {
    id: 'clay_stopmotion',
    label: 'Claymation / Stop-Motion',
    category: '3D & Toy',
    shortDescription: 'Hand-sculpted plasticine clay with visible thumbprints & miniature studio lighting',
  },
  {
    id: 'pixelated_voxel',
    label: 'Pixelated / 16-Bit Voxel',
    category: '3D & Toy',
    shortDescription: 'Crisp pixel-art / voxel aesthetic with quantized color steps & arcade parallax',
  },
  {
    id: 'ghibli_handpainted',
    label: 'Hand-Painted Pastoral Anime',
    category: '2D & Anime',
    shortDescription: 'Lush gouache watercolor skies, fluttering grass & naturalistic Ghibli warmth',
  },
  {
    id: 'niji_expressive',
    label: 'Vibrant Illustrative Anime',
    category: '2D & Anime',
    shortDescription: 'Iridescent Niji rim lighting, luminous particle bokeh & hyper-detailed anime eyes',
  },
  {
    id: 'chibi_stylized',
    label: 'Stylized Chibi',
    category: '2D & Anime',
    shortDescription: 'Super-deformed 2-head proportions, bold cel outlines & playful expressive poses',
  },
  {
    id: 'manga_anime',
    label: 'Cinematic Seinen Manga / Anime',
    category: '2D & Anime',
    shortDescription: 'Razor-sharp ink linework, dramatic speed-line framing & high-contrast cel shading',
  },
  {
    id: 'superhero_blockbuster',
    label: 'Comic-Book Blockbuster',
    category: 'Cinema',
    shortDescription: 'Large-format IMAX anamorphic lens flares, heroic low angles & kinetic VFX',
  },
  {
    id: 'indie_arthouse',
    label: 'Indie A24 Arthouse',
    category: 'Cinema',
    shortDescription: '35mm Kodak Vision3 film grain, available window light & intimate handheld framing',
  },
  {
    id: 'retro_80s',
    label: '1980s Synth & Practical Analog',
    category: 'Cinema',
    shortDescription: 'Anamorphic halation, neon magenta/cyan reflections & atmospheric practical smoke',
  },
  {
    id: 'new_hollywood_70s',
    label: '1970s Gritty Film Stock',
    category: 'Cinema',
    shortDescription: ' coarse 35mm grain, split-diopter focus, warm tungsten practicals & raw realism',
  },
  {
    id: 'mythological_epic',
    label: 'Grand Mythological Epic',
    category: 'Cinema',
    shortDescription: 'Oil-lamp brass glow, ornate silk/gold textures & monumental temple architecture',
  },
]

export const COLOR_PALETTE_PRESETS_UI: CreativePresetOption[] = [
  {
    id: 'warm_golden_amber',
    label: 'Warm Golden & Amber',
    category: 'Palette',
    shortDescription: 'Sun-drenched gold highlights, bronze midtones & warm mahogany shadows',
    swatches: ['#D4AF37', '#C87D32', '#7C3F1C', '#2B1810'],
  },
  {
    id: 'pastel_dreamy',
    label: 'Pastel & Soft Dreamy',
    category: 'Palette',
    shortDescription: 'Powdery rose, mint mist, lavender haze & buttercream highlights',
    swatches: ['#F4C2C2', '#B8E0D2', '#D6CDEA', '#FFF4D2'],
  },
  {
    id: 'monochromatic_noir',
    label: 'Monochromatic Silver / Noir',
    category: 'Palette',
    shortDescription: 'High-contrast silver halides, charcoal midtones & deep obsidian blacks',
    swatches: ['#E5E7EB', '#9CA3AF', '#374151', '#111827'],
  },
  {
    id: 'vibrant_saturated',
    label: 'Vibrant & Hyper-Saturated',
    category: 'Palette',
    shortDescription: 'Punchy primaries — electric crimson, cobalt blue, canary yellow & emerald',
    swatches: ['#E11D48', '#2563EB', '#FACC15', '#10B981'],
  },
  {
    id: 'cool_teal_cinema',
    label: 'Cool Teal & Steel Cinema',
    category: 'Palette',
    shortDescription: 'Cyan-teal shadows, slate-blue midtones & crisp tungsten skin separation',
    swatches: ['#0D9488', '#334155', '#E0F2FE', '#F59E0B'],
  },
  {
    id: 'earthy_organic',
    label: 'Earthy Terracotta & Moss',
    category: 'Palette',
    shortDescription: 'Ochre clay, olive foliage, raw linen & weathered walnut tones',
    swatches: ['#C26D4B', '#5F6F52', '#E5D9B6', '#4A3728'],
  },
  {
    id: 'neon_cyber_contrast',
    label: 'Neon Magenta & Electric Cyan',
    category: 'Palette',
    shortDescription: 'Bioluminescent magenta, laser cyan & ultraviolet against asphalt black',
    swatches: ['#EC4899', '#06B6D4', '#7C3AED', '#090D16'],
  },
  {
    id: 'jewel_toned_opulent',
    label: 'Opulent Jewel Tones',
    category: 'Palette',
    shortDescription: 'Ruby vermilion, peacock sapphire, emerald silk & burnished antique gold',
    swatches: ['#9F1239', '#1E3A8A', '#065F46', '#D97706'],
  },
]

export const DIRECTOR_STYLE_PRESETS_UI: CreativePresetOption[] = [
  {
    id: 'wonder_humanist_blocking',
    label: 'Humanist Wonder & Kinetic Staging',
    category: 'Directorial Style',
    shortDescription: 'e.g., Spielberg — Fluid multi-plane blocking, emotional push-ins & awe-inspiring reveals',
    boundScreenplayId: 'classical_causal_chain',
    boundScreenplayLabel: 'Classical Causal Chain',
    boundMusicId: 'symphonic_leitmotif_natural_foley',
    boundMusicLabel: 'Symphonic Leitmotif + Natural Foley',
  },
  {
    id: 'opulent_operatic_tableau',
    label: 'Opulent Operatic Tableau',
    category: 'Directorial Style',
    shortDescription: 'e.g., Bhansali — Sweeping crane choreography, palatial symmetry & heightened emotion',
    boundScreenplayId: 'poetic_minimalist_ritual',
    boundScreenplayLabel: 'Poetic Ritual & Gesture',
    boundMusicId: 'classical_percussive_ornate_foley',
    boundMusicLabel: 'Classical Strings/Tabla + Ornate Foley',
  },
  {
    id: 'architectural_tension_realism',
    label: 'Architectural Tension & IMAX Realism',
    category: 'Directorial Style',
    shortDescription: 'e.g., Nolan — Grounded physical scale, relentless forward momentum & tight cross-cutting',
    boundScreenplayId: 'nonlinear_puzzle_convergence',
    boundScreenplayLabel: 'Convergent Tension Chain',
    boundMusicId: 'pulse_braam_tactile_foley',
    boundMusicLabel: 'Ticking Pulse + Tactile Mechanical Foley',
  },
  {
    id: 'razor_tension_crash_zoom',
    label: 'Razor-Sharp Standoff & Trunk-Angle Snap',
    category: 'Directorial Style',
    shortDescription: 'e.g., Tarantino — Lingering wide tension, low-angle power shots & sudden kinetic eruptions',
    boundScreenplayId: 'pressure_cooker_escalation',
    boundScreenplayLabel: 'Pressure-Cooker Escalation',
    boundMusicId: 'diegetic_drop_hyper_foley',
    boundMusicLabel: 'Diegetic Needle-Drop + Hyper-Crisp Foley',
  },
  {
    id: 'one_point_geometric_precision',
    label: 'One-Point Perspective & Cold Precision',
    category: 'Directorial Style',
    shortDescription: 'e.g., Kubrick — Hypnotic centered symmetry, deliberate slow tracking & clinical geometry',
    boundScreenplayId: 'poetic_minimalist_ritual',
    boundScreenplayLabel: 'Poetic Ritual & Gesture',
    boundMusicId: 'minimalist_ambient_hyper_real_foley',
    boundMusicLabel: 'Minimalist Drone + Isolated Foley',
  },
  {
    id: 'kinetic_montage_whip_pan',
    label: 'Kinetic Whip-Pan & Hyper-Rhythmic Cut',
    category: 'Directorial Style',
    shortDescription: 'e.g., Ritchie — Snap-zooms, whip-pans, match-cuts on props & propulsive street energy',
    boundScreenplayId: 'kinetic_action_relay',
    boundScreenplayLabel: 'Kinetic Prop-Driven Relay',
    boundMusicId: 'rhythmic_percussive_action_sfx',
    boundMusicLabel: 'Percussive Breakbeat + Whoosh/Impact SFX',
  },
]

export const CANONICAL_PRODUCTION_DEFINITIONS = [
  {
    id: '9.1',
    title: '9.1 Continuity',
    summary:
      'Seamless flow of action, time, and camera movement between consecutive shots. Aligns motion direction, object states, and lighting progressions across sequential clips.',
  },
  {
    id: '9.2',
    title: '9.2 Character Consistency',
    summary:
      'Keeping a subject’s facial features, body type, and clothing identical across shots by repeating fixed identity descriptors and anchoring prompts with reference images.',
  },
  {
    id: '9.3',
    title: '9.3 Scene Consistency',
    summary:
      'Preserving the exact environment, architecture, lighting, and visual style throughout a sequence by reusing setting, atmosphere, and camera lens keywords in every prompt.',
  },
] as const
