import type { Viewport } from './viewport'

/** Candidate spacings between labelled ruler ticks, in seconds. */
const TICK_STEPS_SEC = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200]

export interface RulerTicks {
  /** Seconds between labelled ticks. */
  step: number
  /** Labelled tick times inside the viewport. */
  major: number[]
  /** Unlabelled subdivision times inside the viewport (excludes majors). */
  minor: number[]
}

/** Smallest "nice" step that keeps labels at least `minLabelPx` apart. */
export function pickTickStep(spanSec: number, widthPx: number, minLabelPx = 72): number {
  const last = TICK_STEPS_SEC[TICK_STEPS_SEC.length - 1]
  if (spanSec <= 0 || widthPx <= 0) return last
  const wanted = (spanSec / widthPx) * minLabelPx
  return TICK_STEPS_SEC.find((step) => step >= wanted) ?? last
}

/** Subdivisions per major step: 5 for steps on a 1/5 grid, otherwise 4 or 2. */
function minorDivisions(step: number): number {
  if (step === 15 || step === 900) return 3
  if (step === 0.2 || step === 2 || step === 120 || step === 7200) return 4
  return 5
}

/** Multiples of `step` inside `[start, end]`, computed on integers to avoid drift. */
function multiplesWithin(step: number, start: number, end: number): number[] {
  const out: number[] = []
  const first = Math.ceil(start / step - 1e-9)
  const last = Math.floor(end / step + 1e-9)
  // `|| 0` folds the negative zero that a multiple of the step at t = 0 would produce.
  for (let i = first; i <= last; i++) out.push(Math.round(i * step * 1000) / 1000 || 0)
  return out
}

export function buildTicks(view: Viewport, widthPx: number, minLabelPx = 72): RulerTicks {
  const step = pickTickStep(view.end - view.start, widthPx, minLabelPx)
  const divisions = minorDivisions(step)
  const major = multiplesWithin(step, view.start, view.end)
  const minor = multiplesWithin(step / divisions, view.start, view.end).filter((_, i, all) => {
    const index = Math.round(all[i] / (step / divisions))
    return index % divisions !== 0
  })
  return { step, major, minor }
}
