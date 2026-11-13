import * as React from 'react'
import { Legend, type LegendPayload, type LegendProps } from 'recharts'
import { cn } from '@/lib/utils'
import { getPayloadConfig, pickKey } from './config'
import { useChart } from './context'

/**
 * Every prop is optional: recharts clones the `content` element and injects `payload` (plus the
 * props set on `ChartLegend` itself, e.g. `verticalAlign`) at render time.
 */
export type ChartLegendContentProps = {
  className?: string
  payload?: ReadonlyArray<LegendPayload>
  verticalAlign?: LegendProps['verticalAlign']
  /** Show the colour swatch even for series whose config declares an icon. */
  hideIcon?: boolean
  /** Field (on the item or its datum) holding the series key used to look up each entry's config. */
  nameKey?: string
}

export const ChartLegend = Legend

type LegendItemProps = Pick<ChartLegendContentProps, 'hideIcon' | 'nameKey'> & {
  item: LegendPayload
}

function LegendItem({ item, hideIcon, nameKey }: LegendItemProps) {
  const { config } = useChart()
  const itemConfig = getPayloadConfig(config, item, pickKey(nameKey, item.dataKey))
  const Icon = hideIcon ? undefined : itemConfig?.icon
  return (
    <div className="flex items-center gap-1.5 [&>svg]:h-3 [&>svg]:w-3 [&>svg]:text-muted-foreground">
      {Icon ? <Icon /> : <div className="h-2 w-2 shrink-0 rounded-[2px]" style={{ backgroundColor: item.color }} />}
      {itemConfig?.label ?? item.value}
    </div>
  )
}

/** Themed legend body for `<ChartLegend content={<ChartLegendContent />} />`. */
export function ChartLegendContent(props: ChartLegendContentProps) {
  const { className, payload, verticalAlign = 'bottom', hideIcon = false, nameKey } = props
  if (!payload?.length) return null
  const items = payload.filter((item) => item.type !== 'none')
  return (
    <div className={cn('flex flex-wrap items-center justify-center gap-x-4 gap-y-1.5', verticalAlign === 'top' ? 'pb-3' : 'pt-3', className)}>
      {items.map((item, index) => (
        <LegendItem key={index} item={item} hideIcon={hideIcon} nameKey={nameKey} />
      ))}
    </div>
  )
}
