import { useMemo } from 'react'
import { LaneItem, LaneSvg, TimelineLane, spanBox, spokenRange } from '@/components/shared/timeline'
import { useSelectItem, useTimeScale } from '@/hooks/timeline/timelineContext'
import { driverLabel } from '@/types/engagement/reportFormat'
import type { ReportModel } from '@/types/engagement/reportModel'
import type { ReportInfluence, TimeRange } from '@/types/insights'
import { IntervalIndex } from '@/types/timeline/intervalIndex'
import { fitLabel } from '@/types/timeline/shortcuts'
import { driverColor, useEngagementUi } from './engagementUi'

/** Id of the lane that shows the selected drivers. */
export const DRIVER_LANES_ID = 'drivers'
const LANE_HEIGHT_PX = 48
/** Rows thinner than this carry no text. */
const MIN_TEXT_ROW_PX = 14
const SHADE_OPACITY = 0.16

interface SelectedDriver {
  driver: ReportInfluence
  color: string
  /** The driver's ranges, indexed so only the visible ones are drawn. */
  ranges: IntervalIndex<TimeRange>
}

/** The selected drivers with their colours (by selection order) and indexed ranges. */
function useSelectedDrivers(report: ReportModel): SelectedDriver[] {
  const keys = useEngagementUi((state) => state.selectedDrivers)
  return useMemo(
    () =>
      keys.flatMap((key, position) => {
        const driver = report.influenceByKey.get(key)
        return driver ? [{ driver, color: driverColor(position), ranges: new IntervalIndex(driver.ranges) }] : []
      }),
    [keys, report],
  )
}

/** Translucent bands over the curve for the time each selected driver is present. Put it under the chart. */
export function DriverShading({ report, height }: { report: ReportModel; height: number }): JSX.Element | null {
  const scale = useTimeScale()
  const selected = useSelectedDrivers(report)
  if (selected.length === 0) return null
  return (
    <svg aria-hidden data-testid="driver-shading" width={scale.width} height={height} className="pointer-events-none absolute inset-0">
      {selected.map(({ driver, color, ranges }) =>
        ranges.overlapping(scale.view.start, scale.view.end).map((range) => {
          const box = spanBox(scale, range)
          return <rect key={`${driver.key}:${range.start_sec}`} data-driver={driver.key} x={box.x} y={0} width={box.width} height={height} fill={color} fillOpacity={SHADE_OPACITY} />
        }),
      )}
    </svg>
  )
}

interface DriverBarProps {
  driver: ReportInfluence
  range: TimeRange
  color: string
  /** Top of the driver's row and its height, in pixels. */
  y: number
  rowHeight: number
  tabStop: boolean
}

/** One range a driver is present for. Activating it selects the range, which the range inspector then summarises. */
function DriverBar({ driver, range, color, y, rowHeight, tabStop }: DriverBarProps): JSX.Element {
  const scale = useTimeScale()
  const select = useSelectItem()
  const box = spanBox(scale, range)
  const name = driverLabel(driver)
  const label = `${name} present`
  const text = rowHeight >= MIN_TEXT_ROW_PX ? fitLabel(name, box.visibleWidth - 10) : ''
  return (
    <LaneItem label={`${label}, ${spokenRange(range)}`} tabStop={tabStop} onActivate={() => select({ kind: 'range', id: null, label, range })}>
      <rect className="tl-shape" data-driver={driver.key} x={box.x + 0.5} y={y + 1.5} width={Math.max(box.width - 1, 1)} height={rowHeight - 3} rx={2.5} fill={color} fillOpacity={0.85} />
      {text && (
        <text x={box.visibleX + 5} y={y + rowHeight / 2 + 3.5} fontSize={10} className="pointer-events-none fill-foreground">
          {text}
        </text>
      )}
    </LaneItem>
  )
}

interface DriverRowProps {
  item: SelectedDriver
  row: number
  rowHeight: number
}

function DriverRow({ item, row, rowHeight }: DriverRowProps): JSX.Element {
  const scale = useTimeScale()
  const visible = item.ranges.overlapping(scale.view.start, scale.view.end)
  return (
    <>
      {visible.map((range, i) => (
        <DriverBar key={range.start_sec} driver={item.driver} range={range} color={item.color} y={row * rowHeight} rowHeight={rowHeight} tabStop={row === 0 && i === 0} />
      ))}
    </>
  )
}

/**
 * The drivers selected in the Drivers tab, one row each in a single lane
 * right under the curve, so several can be compared against it and against
 * each other. The lane keeps its height whatever is selected: toggling a
 * driver never moves the page under the pointer.
 */
export function DriverLanes({ report }: { report: ReportModel }): JSX.Element {
  const selected = useSelectedDrivers(report)
  const rowHeight = LANE_HEIGHT_PX / Math.max(selected.length, 1)
  return (
    <TimelineLane id={DRIVER_LANES_ID} label={selected.length > 0 ? `Drivers (${selected.length})` : 'Drivers'} height={LANE_HEIGHT_PX}>
      {selected.length === 0 ? (
        <p className="flex h-full cursor-default items-center px-2 text-[10.5px] text-muted-foreground">Select drivers in the Drivers tab to shade them on the curve and compare them here.</p>
      ) : (
        <LaneSvg label="Selected drivers" height={LANE_HEIGHT_PX}>
          {selected.map((item, row) => (
            <DriverRow key={item.driver.key} item={item} row={row} rowHeight={rowHeight} />
          ))}
        </LaneSvg>
      )}
    </TimelineLane>
  )
}
