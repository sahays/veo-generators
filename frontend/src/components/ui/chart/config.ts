import type * as React from 'react'

/** The app's two colour themes; `dark` is active whenever an ancestor carries the `.dark` class. */
export type ChartTheme = 'light' | 'dark'

/** Presentation of one series: a label, an optional icon, and either one colour or a colour per theme. */
export type ChartSeriesConfig = {
  label?: React.ReactNode
  icon?: React.ComponentType
} & ({ color?: string; theme?: never } | { color?: never; theme: Record<ChartTheme, string> })

/** Chart configuration keyed by series (usually the recharts `dataKey`, or a category value). */
export type ChartConfig = Record<string, ChartSeriesConfig>

/** Inline style carrying one `--color-<series>` custom property per coloured series. */
export type ChartColorVars = React.CSSProperties & Record<`--color-${string}`, string>

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

/** Read `source[key]` when `source` is an object and the value is a string. */
export function readString(source: unknown, key: string): string | undefined {
  if (!isRecord(source)) return undefined
  const value = source[key]
  return typeof value === 'string' ? value : undefined
}

/** Own-property lookup, so a series named e.g. `constructor` never resolves to `Object.prototype`. */
export function getSeriesConfig(config: ChartConfig, key: string): ChartSeriesConfig | undefined {
  return Object.hasOwn(config, key) ? config[key] : undefined
}

/** First candidate that is a usable key (string or number), as a string; `'value'` when none is. */
export function pickKey(...candidates: unknown[]): string {
  for (const candidate of candidates) {
    if (typeof candidate === 'number' || (typeof candidate === 'string' && candidate)) return String(candidate)
  }
  return 'value'
}

/**
 * Resolve the CSS colour of one series.
 *
 * A `theme: { light, dark }` entry has to follow the app theme without an injected style tag (raw
 * HTML injection is banned in this repo) and without reading the layout store (`components/ui` may
 * not import `store/`). So by default it becomes a CSS `light-dark(light, dark)` expression, which
 * the browser resolves from the `color-scheme` that `ChartContainer` pins to the `.dark` class. When
 * the caller passes an explicit `theme`, the matching colour is used verbatim instead.
 */
export function resolveSeriesColor(item: ChartSeriesConfig, theme?: ChartTheme): string | undefined {
  if (!item.theme) return item.color
  return theme ? item.theme[theme] : `light-dark(${item.theme.light}, ${item.theme.dark})`
}

/** Build the `--color-<series>` custom properties that `ChartContainer` sets through its `style` prop. */
export function buildColorVars(config: ChartConfig, theme?: ChartTheme): ChartColorVars {
  const vars: ChartColorVars = {}
  for (const [key, item] of Object.entries(config)) {
    const color = resolveSeriesColor(item, theme)
    if (color) vars[`--color-${key}`] = color
  }
  return vars
}

/**
 * Find the config entry for a tooltip or legend payload item.
 *
 * `key` names a field on the item, or on its underlying datum (`item.payload`), whose string value
 * is the series key (e.g. `nameKey="browser"` with a datum `{ browser: 'chrome' }` resolves
 * `config.chrome`). When neither holds such a field, `key` itself is the series key.
 */
export function getPayloadConfig(config: ChartConfig, item: unknown, key: string): ChartSeriesConfig | undefined {
  if (!isRecord(item)) return undefined
  const seriesKey = readString(item, key) ?? readString(item.payload, key) ?? key
  return getSeriesConfig(config, seriesKey) ?? getSeriesConfig(config, key)
}
