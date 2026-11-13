/** Time formatting and parsing for the timeline kit. All inputs are seconds. */

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

function safeSeconds(sec: number): number {
  return Number.isFinite(sec) && sec > 0 ? sec : 0
}

/**
 * Player-style timecode: `0:07`, `12:34`, `1:02:03`. With `tenths` the
 * fraction is kept (`0:07.5`), which the ruler needs when zoomed in.
 */
export function formatTimecode(sec: number, options: { tenths?: boolean } = {}): string {
  const tenthsTotal = Math.floor(safeSeconds(sec) * 10 + 1e-6)
  const whole = Math.floor(tenthsTotal / 10)
  const hours = Math.floor(whole / 3600)
  const minutes = Math.floor((whole % 3600) / 60)
  const seconds = whole % 60
  const head = hours > 0 ? `${hours}:${pad2(minutes)}` : String(minutes)
  const tail = options.tenths ? `.${tenthsTotal % 10}` : ''
  return `${head}:${pad2(seconds)}${tail}`
}

/** Human length of a span: `0.8s`, `12s`, `1m 05s`, `1h 02m`. */
export function formatSpan(sec: number): string {
  const value = safeSeconds(sec)
  if (value < 10) return `${Math.round(value * 10) / 10}s`
  const whole = Math.round(value)
  if (whole < 60) return `${whole}s`
  if (whole < 3600) return `${Math.floor(whole / 60)}m ${pad2(whole % 60)}s`
  return `${Math.floor(whole / 3600)}h ${pad2(Math.floor((whole % 3600) / 60))}m`
}

/** Subtitle timestamp `HH:MM:SS<sep>mmm` (`,` for SRT, `.` for WebVTT). */
export function formatSubtitleTime(sec: number, fractionSeparator: ',' | '.'): string {
  const totalMs = Math.round(safeSeconds(sec) * 1000)
  const ms = totalMs % 1000
  const whole = Math.floor(totalMs / 1000)
  const clock = [Math.floor(whole / 3600), Math.floor((whole % 3600) / 60), whole % 60].map(pad2).join(':')
  return `${clock}${fractionSeparator}${String(ms).padStart(3, '0')}`
}

/** Value for the `?t=` query parameter: seconds with at most one decimal. */
export function toTimeParam(sec: number): string {
  return String(Math.round(safeSeconds(sec) * 10) / 10)
}

/**
 * Parse a `?t=` value. Accepts plain seconds (`12.5`) and clock forms
 * (`1:05`, `1:02:03`). Returns null for anything else, including negatives.
 */
export function parseTimeParam(raw: string | null | undefined): number | null {
  const text = (raw ?? '').trim()
  if (!/^\d+(\.\d+)?(:\d{1,2}(\.\d+)?){0,2}$/.test(text)) return null
  const total = text.split(':').reduce((acc, part) => acc * 60 + Number(part), 0)
  return Number.isFinite(total) ? total : null
}
