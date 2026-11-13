/**
 * Width of the label gutter on the left of every lane, in pixels. Every lane
 * row is `[gutter | plot]` with this same gutter, inside the same container,
 * so all plots start at the same x and have the same width by construction.
 */
export const TIMELINE_GUTTER_PX = 132

/** Default plot heights of the kit's lanes, in pixels. */
export const LANE_HEIGHT = {
  ruler: 30,
  filmstrip: 54,
  segments: 30,
  markers: 48,
  beats: 24,
  emotions: 30,
  entity: 20,
  density: 32,
  minimap: 30,
} as const
