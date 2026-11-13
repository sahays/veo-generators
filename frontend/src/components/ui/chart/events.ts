/** The part of the state recharts passes to a chart's `onClick` / `onMouseMove` that names the active datum. */
export interface ChartPointerState {
  activeTooltipIndex?: number | string | null
}

/** Index of the datum under the pointer, or null when the pointer is not over one. */
export function activeIndexOf(state: ChartPointerState): number | null {
  const raw = state.activeTooltipIndex
  if (raw === null || raw === undefined || raw === '') return null
  const index = Number(raw)
  return Number.isInteger(index) && index >= 0 ? index : null
}
