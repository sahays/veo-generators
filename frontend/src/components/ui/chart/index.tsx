/**
 * shadcn-style chart primitives on top of recharts 3.
 *
 * Usage: wrap one recharts chart in `ChartContainer` with a `ChartConfig`, colour each series with
 * `var(--color-<seriesKey>)`, and pass `ChartTooltipContent` / `ChartLegendContent` as the `content`
 * of `ChartTooltip` / `ChartLegend`. Palette tokens `--chart-1` … `--chart-8` live in `index.css`.
 */
export type { ChartColorVars, ChartConfig, ChartSeriesConfig, ChartTheme } from './config'
export { useChart, type ChartContextValue } from './context'
export { ChartContainer, type ChartContainerProps } from './container'
export {
  ChartTooltip,
  ChartTooltipContent,
  type ChartTooltipContentProps,
  type ChartTooltipFormatter,
  type ChartTooltipIndicator,
  type ChartTooltipItem,
  type ChartTooltipPayload,
} from './tooltip'
export { ChartLegend, ChartLegendContent, type ChartLegendContentProps } from './legend'
export { activeIndexOf, type ChartPointerState } from './events'
