import * as React from 'react'
import { ResponsiveContainer } from 'recharts'
import { cn } from '@/lib/utils'
import { buildColorVars, type ChartConfig, type ChartTheme } from './config'
import { ChartContext } from './context'

/**
 * Layout plus the recharts class overrides that map its hard-coded greys onto the theme tokens.
 * `scheme-light dark:scheme-dark` pins `color-scheme` to the app's `.dark` class so that
 * `light-dark()` series colours (see `resolveSeriesColor`) follow the app theme, not the OS one.
 *
 * The bar hover band and radial-bar track use a 6% `foreground` tint rather than upstream's `muted`:
 * in dark mode `--muted` (#171D26) is indistinguishable from `--card` (#151A23), where charts sit.
 */
const CHART_CLASSES = [
  'flex aspect-video justify-center text-xs scheme-light dark:scheme-dark',
  '[&_.recharts-cartesian-axis-tick_text]:fill-muted-foreground',
  "[&_.recharts-cartesian-grid_line[stroke='#ccc']]:stroke-border",
  '[&_.recharts-curve.recharts-tooltip-cursor]:stroke-border',
  '[&_.recharts-rectangle.recharts-tooltip-cursor]:fill-foreground/6',
  "[&_.recharts-polar-grid_[stroke='#ccc']]:stroke-border",
  '[&_.recharts-radial-bar-background-sector]:fill-foreground/6',
  "[&_.recharts-reference-line_[stroke='#ccc']]:stroke-border",
  "[&_.recharts-dot[stroke='#fff']]:stroke-transparent",
  "[&_.recharts-sector[stroke='#fff']]:stroke-transparent",
  '[&_.recharts-layer]:outline-hidden [&_.recharts-sector]:outline-hidden [&_.recharts-surface]:outline-hidden',
]

export type ChartContainerProps = React.ComponentPropsWithoutRef<'div'> & {
  /** Series presentation, exposed to descendants via `useChart` and as `--color-<series>` variables. */
  config: ChartConfig
  /** A single recharts chart element (`BarChart`, `AreaChart`, …). */
  children: React.ComponentProps<typeof ResponsiveContainer>['children']
  /**
   * Force `theme: { light, dark }` colours to one theme. Leave unset (the default) to follow the
   * app's `.dark` class automatically.
   */
  theme?: ChartTheme
}

export const ChartContainer = React.forwardRef<HTMLDivElement, ChartContainerProps>(function ChartContainer(
  { id, className, style, children, config, theme, ...props },
  ref,
) {
  const uniqueId = React.useId()
  const contextValue = React.useMemo(() => ({ config }), [config])
  const colorVars = React.useMemo(() => buildColorVars(config, theme), [config, theme])
  return (
    <ChartContext.Provider value={contextValue}>
      <div
        ref={ref}
        data-slot="chart"
        data-chart={`chart-${id || uniqueId.replace(/:/g, '')}`}
        className={cn(CHART_CLASSES, className)}
        style={{ ...colorVars, ...style }}
        {...props}
      >
        <ResponsiveContainer>{children}</ResponsiveContainer>
      </div>
    </ChartContext.Provider>
  )
})
