import { glyphPath, type GlyphShape } from '@/types/timeline/glyphs'

export interface GlyphIconProps {
  shape: GlyphShape
  color: string
  size?: number
  className?: string
}

/** A marker glyph as a standalone icon, for lists and legends next to the timeline. */
export function GlyphIcon({ shape, color, size = 14, className }: GlyphIconProps): JSX.Element {
  const half = size / 2
  return (
    <svg aria-hidden width={size} height={size} viewBox={`${-half} ${-half} ${size} ${size}`} className={className}>
      <path d={glyphPath(shape, half - 1.5)} fill={color} stroke="var(--card)" strokeWidth={0.75} />
    </svg>
  )
}
