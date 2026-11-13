import * as React from 'react'
import { Tooltip } from 'recharts'
import type { NameType, Payload, ValueType } from 'recharts/types/component/DefaultTooltipContent'
import { cn } from '@/lib/utils'
import { getPayloadConfig, getSeriesConfig, pickKey, readString } from './config'
import { useChart } from './context'

export type ChartTooltipItem = Payload<ValueType, NameType>
export type ChartTooltipPayload = ReadonlyArray<ChartTooltipItem>
export type ChartTooltipIndicator = 'dot' | 'line' | 'dashed'

/** Replaces a whole tooltip row. Same arguments as the recharts `Tooltip` formatter. */
export type ChartTooltipFormatter = (
  value: ValueType,
  name: NameType,
  item: ChartTooltipItem,
  index: number,
  payload: ChartTooltipPayload,
) => React.ReactNode

/**
 * Every prop is optional: recharts clones the `content` element and injects `active`, `payload` and
 * `label` (plus whatever was set on `ChartTooltip` itself, e.g. `formatter`) at render time.
 */
export type ChartTooltipContentProps = {
  active?: boolean
  payload?: ChartTooltipPayload
  label?: string | number
  className?: string
  labelClassName?: string
  /** Overrides the indicator colour of every row. */
  color?: string
  indicator?: ChartTooltipIndicator
  hideLabel?: boolean
  hideIndicator?: boolean
  /** Field (on the item or its datum) holding the series key used to look up each row's config. */
  nameKey?: string
  /** Field (on the first item or its datum) holding the series key used to look up the heading. */
  labelKey?: string
  formatter?: ChartTooltipFormatter
  labelFormatter?: (label: React.ReactNode, payload: ChartTooltipPayload) => React.ReactNode
}

export const ChartTooltip = Tooltip

type LabelProps = Pick<ChartTooltipContentProps, 'label' | 'labelKey' | 'labelFormatter' | 'labelClassName'> & {
  payload: ChartTooltipPayload
}

/** Tooltip heading: the axis label (mapped through the config when it names a series) or a series label. */
function TooltipLabel({ payload, label, labelKey, labelFormatter, labelClassName }: LabelProps) {
  const { config } = useChart()
  const [item] = payload
  const hasAxisLabel = !labelKey && (typeof label === 'string' || typeof label === 'number')
  const value: React.ReactNode = hasAxisLabel
    ? getSeriesConfig(config, String(label))?.label || label
    : getPayloadConfig(config, item, pickKey(labelKey, item?.dataKey, item?.name))?.label
  const content = labelFormatter ? labelFormatter(value, payload) : value
  if (content === undefined || content === null || content === '') return null
  return <div className={cn('font-medium', labelClassName)}>{content}</div>
}

type IndicatorProps = {
  icon?: React.ComponentType
  indicator: ChartTooltipIndicator
  color?: string
  hidden: boolean
  nested: boolean
}

function TooltipIndicator({ icon: Icon, indicator, color, hidden, nested }: IndicatorProps) {
  if (Icon) return <Icon />
  if (hidden) return null
  const shape = {
    'h-2.5 w-2.5': indicator === 'dot',
    'w-1': indicator === 'line',
    'w-0 border-[1.5px] border-dashed bg-transparent': indicator === 'dashed',
    'my-0.5': nested && indicator === 'dashed',
  }
  // A private variable name: reusing `--color-border` here would shadow the theme's border token.
  const style = { '--chart-indicator': color } as React.CSSProperties
  return <div className={cn('shrink-0 rounded-[2px] border-(--chart-indicator) bg-(--chart-indicator)', shape)} style={style} />
}

type RowOptions = Pick<ChartTooltipContentProps, 'color' | 'nameKey' | 'formatter'> & {
  indicator: ChartTooltipIndicator
  hideIndicator: boolean
  payload: ChartTooltipPayload
  /** Single-series `line`/`dashed` tooltips render the heading inside the row instead of above it. */
  nestLabel: boolean
  labelNode: React.ReactNode
}

type RowProps = RowOptions & {
  item: ChartTooltipItem
  index: number
}

/** Default row body: indicator (or the series icon), series label and the formatted value. */
function TooltipRowBody({ item, color, nameKey, indicator, hideIndicator, nestLabel, labelNode }: RowProps) {
  const { config } = useChart()
  const itemConfig = getPayloadConfig(config, item, pickKey(nameKey, item.name, item.dataKey))
  const swatch = color || readString(item.payload, 'fill') || item.color
  const hasValue = item.value !== undefined && item.value !== null
  return (
    <>
      <TooltipIndicator icon={itemConfig?.icon} indicator={indicator} color={swatch} hidden={hideIndicator} nested={nestLabel} />
      <div className={cn('flex flex-1 justify-between gap-2 leading-none', nestLabel ? 'items-end' : 'items-center')}>
        <div className="grid gap-1.5">
          {nestLabel ? labelNode : null}
          <span className="text-muted-foreground">{itemConfig?.label || item.name}</span>
        </div>
        {hasValue && (
          <span className="font-mono font-medium tabular-nums text-foreground">{item.value?.toLocaleString()}</span>
        )}
      </div>
    </>
  )
}

function TooltipRow(props: RowProps) {
  const { item, index, formatter, payload, indicator } = props
  const body =
    formatter && item.value !== undefined && item.name !== undefined ? (
      formatter(item.value, item.name, item, index, payload)
    ) : (
      <TooltipRowBody {...props} />
    )
  return (
    <div
      className={cn(
        'flex w-full flex-wrap items-stretch gap-2 [&>svg]:h-2.5 [&>svg]:w-2.5 [&>svg]:text-muted-foreground',
        indicator === 'dot' && 'items-center',
      )}
    >
      {body}
    </div>
  )
}

/** Heading element for the tooltip, or `null` when hidden. */
function renderLabel(props: ChartTooltipContentProps, payload: ChartTooltipPayload): React.ReactNode {
  const { hideLabel = false, label, labelKey, labelFormatter, labelClassName } = props
  if (hideLabel) return null
  return (
    <TooltipLabel
      payload={payload}
      label={label}
      labelKey={labelKey}
      labelFormatter={labelFormatter}
      labelClassName={labelClassName}
    />
  )
}

/** Themed tooltip body for `<ChartTooltip content={<ChartTooltipContent />} />`. */
export function ChartTooltipContent(props: ChartTooltipContentProps) {
  const { active, payload, className, indicator = 'dot', hideIndicator = false, color, nameKey, formatter } = props
  if (!active || !payload?.length) return null
  const nestLabel = payload.length === 1 && indicator !== 'dot'
  const labelNode = renderLabel(props, payload)
  const rowOptions: RowOptions = { color, nameKey, formatter, indicator, hideIndicator, payload, nestLabel, labelNode }
  const rows = payload.filter((item) => item.type !== 'none')
  return (
    <div
      className={cn(
        'grid min-w-[8rem] items-start gap-1.5 rounded-lg border border-border bg-popover px-2.5 py-1.5 text-xs text-popover-foreground shadow-xl',
        className,
      )}
    >
      {nestLabel ? null : labelNode}
      <div className="grid gap-1.5">
        {rows.map((item, index) => (
          <TooltipRow key={index} item={item} index={index} {...rowOptions} />
        ))}
      </div>
    </div>
  )
}
