/**
 * Visual encoding for timeline categories. Every category gets a shape as
 * well as a colour, so markers stay distinguishable without colour vision.
 * Colours are CSS custom properties (`--chart-N`, defined per theme in
 * `index.css`) so both themes are covered.
 */

export type GlyphShape =
  | 'circle'
  | 'diamond'
  | 'triangle'
  | 'triangle-down'
  | 'square'
  | 'star'
  | 'hexagon'
  | 'cross'

export interface Glyph {
  shape: GlyphShape
  color: string
}

const SHAPES: GlyphShape[] = ['circle', 'diamond', 'triangle', 'square', 'star', 'hexagon', 'triangle-down', 'cross']
const PALETTE_SIZE = 8

export function chartColor(index: number): string {
  return `var(--chart-${(((index % PALETTE_SIZE) + PALETTE_SIZE) % PALETTE_SIZE) + 1})`
}

/** Stable small hash so unknown categories always map to the same glyph. */
export function hashString(text: string): number {
  let hash = 0
  for (let i = 0; i < text.length; i++) hash = (hash * 31 + text.charCodeAt(i)) >>> 0
  return hash
}

function glyph(shape: GlyphShape, colorIndex: number): Glyph {
  return { shape, color: chartColor(colorIndex) }
}

/** Key-moment types and narrative beats named by the timeline schema. */
const KNOWN_GLYPHS: Record<string, Glyph> = {
  hook: glyph('star', 0),
  reveal: glyph('diamond', 1),
  twist: glyph('cross', 5),
  cliffhanger: glyph('triangle', 3),
  punchline: glyph('circle', 4),
  action_peak: glyph('triangle', 5),
  emotional_peak: glyph('hexagon', 3),
  song: glyph('circle', 6),
  product_reveal: glyph('square', 2),
  call_to_action: glyph('triangle-down', 0),
  setup: glyph('square', 7),
  inciting_incident: glyph('diamond', 4),
  rising_action: glyph('triangle', 1),
  climax: glyph('star', 5),
  falling_action: glyph('triangle-down', 6),
  resolution: glyph('circle', 2),
}

export function glyphFor(category: string): Glyph {
  const key = category.trim().toLowerCase()
  const known = KNOWN_GLYPHS[key]
  if (known) return known
  const hash = hashString(key)
  return glyph(SHAPES[hash % SHAPES.length], Math.floor(hash / SHAPES.length))
}

/** `Lord Ganesh` -> `lord-ganesh`: safe to embed in a CSS custom property name. */
export function cssSlug(text: string): string {
  return text.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
}

/**
 * Colour for an emotion. The schema's emotions have their own theme tokens
 * (`--emotion-joy`, ... in `index.css`); any other label falls back to a
 * stable palette colour.
 */
export function emotionColor(emotion: string): string {
  const slug = cssSlug(emotion)
  const fallback = chartColor(hashString(slug))
  return slug ? `var(--emotion-${slug}, ${fallback})` : fallback
}

function polygon(points: number, radius: number, rotation: number, innerRatio = 1): string {
  const total = innerRatio === 1 ? points : points * 2
  const coords: string[] = []
  for (let i = 0; i < total; i++) {
    const r = innerRatio !== 1 && i % 2 === 1 ? radius * innerRatio : radius
    const angle = rotation + (i * 2 * Math.PI) / total
    coords.push(`${(r * Math.cos(angle)).toFixed(2)},${(r * Math.sin(angle)).toFixed(2)}`)
  }
  return `M${coords.join('L')}Z`
}

function crossPath(r: number): string {
  const a = (r * 0.38).toFixed(2)
  const b = r.toFixed(2)
  return `M-${a},-${b}H${a}V-${a}H${b}V${a}H${a}V${b}H-${a}V${a}H-${b}V-${a}H-${a}Z`
}

const UP = -Math.PI / 2

/** SVG path for a glyph centred on the origin with the given radius. */
export function glyphPath(shape: GlyphShape, radius: number): string {
  const r = radius
  switch (shape) {
    case 'circle':
      return `M${-r},0A${r},${r} 0 1,0 ${r},0A${r},${r} 0 1,0 ${-r},0Z`
    case 'diamond':
      return polygon(4, r, UP)
    case 'triangle':
      return polygon(3, r * 1.1, UP)
    case 'triangle-down':
      return polygon(3, r * 1.1, -UP)
    case 'square':
      return polygon(4, r * 1.1, Math.PI / 4)
    case 'star':
      return polygon(5, r * 1.15, UP, 0.45)
    case 'hexagon':
      return polygon(6, r, 0)
    case 'cross':
      return crossPath(r)
  }
}

/** Human label for a schema category key: `call_to_action` -> `Call to action`. */
export function categoryLabel(category: string): string {
  const text = category.replace(/[_-]+/g, ' ').trim()
  return text ? text[0].toUpperCase() + text.slice(1) : ''
}
