import { useMemo } from 'react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, XAxis, YAxis } from 'recharts'
import { ChartContainer, ChartTooltip, ChartTooltipContent, activeIndexOf, type ChartConfig } from '@/components/ui/chart'
import { useSeek, useSelectItem, useTimelineKit } from '@/hooks/timeline/timelineContext'
import { usePrefersReducedMotion } from '@/hooks/timeline/usePrefersReducedMotion'
import type { TimelineEntity } from '@/types/insights'
import { categoryLabel } from '@/types/timeline/glyphs'
import type { TimelineModel } from '@/types/timeline/model'
import { emotionIntensitySeries, type EmotionSample } from '@/types/timeline/series'
import { formatSpan, formatTimecode } from '@/types/timeline/timeFormat'

const MAX_BARS = 8
const CHART_CLASS = 'aspect-auto h-[210px] w-full cursor-pointer'

const SCREEN_TIME_CONFIG: ChartConfig = {
  seconds: { label: 'Screen time' },
  character: { label: 'Character', color: 'var(--chart-1)' },
  object: { label: 'Object', color: 'var(--chart-2)' },
  location: { label: 'Location', color: 'var(--chart-3)' },
}

const EMOTION_CONFIG: ChartConfig = {
  intensity: { label: 'Intensity', color: 'var(--chart-1)' },
}

function ChartLegendRow({ config, keys }: { config: ChartConfig; keys: string[] }): JSX.Element {
  return (
    <ul className="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
      {keys.map((key) => (
        <li key={key} className="flex items-center gap-1">
          <span aria-hidden className="h-2 w-2 rounded-[2px]" style={{ background: config[key].color }} />
          {config[key].label}
        </li>
      ))}
    </ul>
  )
}

/**
 * Screen time of the most visible entities. Clicking a bar selects the
 * entity, seeks to its first appearance and pins it to the timeline.
 */
export function ScreenTimeChart({ entities }: { entities: readonly TimelineEntity[] }): JSX.Element {
  const { store } = useTimelineKit()
  const select = useSelectItem()
  const reducedMotion = usePrefersReducedMotion()
  const data = useMemo(() => entities.slice(0, MAX_BARS).map((e) => ({ id: e.id, name: e.name, kind: e.kind, seconds: e.screen_time_sec })), [entities])
  const pick = (index: number | null): void => {
    const entity = index === null ? undefined : entities[index]
    const first = entity?.appearances[0]
    if (!entity || !first) return
    if (!store.getState().pinnedEntityIds.includes(entity.id)) store.getState().togglePin(entity.id)
    select({ kind: 'entity', id: entity.id, label: entity.name, range: first })
  }
  return (
    <figure className="space-y-1.5" data-testid="screen-time-chart">
      <figcaption className="text-xs font-semibold text-foreground">Screen time by entity</figcaption>
      <ChartContainer config={SCREEN_TIME_CONFIG} className={CHART_CLASS} role="img" aria-label={`Screen time of the ${data.length} most visible entities. The Entities tab lists the same figures.`}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 4 }} onClick={(state) => pick(activeIndexOf(state))}>
          <CartesianGrid horizontal={false} />
          <XAxis type="number" dataKey="seconds" tickLine={false} axisLine={false} tickFormatter={(value: number) => `${value}s`} />
          <YAxis type="category" dataKey="name" width={112} tickLine={false} axisLine={false} interval={0} />
          <ChartTooltip content={<ChartTooltipContent formatter={(value) => <span className="font-mono font-medium text-foreground">{formatSpan(Number(value))} on screen</span>} />} />
          <Bar dataKey="seconds" radius={3} isAnimationActive={!reducedMotion}>
            {data.map((entry) => (
              <Cell key={entry.id} fill={`var(--color-${entry.kind})`} />
            ))}
          </Bar>
        </BarChart>
      </ChartContainer>
      <ChartLegendRow config={SCREEN_TIME_CONFIG} keys={['character', 'object', 'location']} />
    </figure>
  )
}

function emotionTooltipRow(sample: EmotionSample | undefined): JSX.Element {
  const name = sample?.emotion ? categoryLabel(sample.emotion) : 'No emotion tagged'
  return (
    <span className="font-medium text-foreground">
      {name} <span className="font-mono text-muted-foreground">{Math.round((sample?.intensity ?? 0) * 100)}%</span>
    </span>
  )
}

/** Strongest emotion intensity over time. Clicking the chart seeks to that moment. */
export function EmotionChart({ model }: { model: TimelineModel }): JSX.Element {
  const seek = useSeek()
  const reducedMotion = usePrefersReducedMotion()
  const data = useMemo(() => emotionIntensitySeries(model.emotions, model.duration), [model])
  const seekToIndex = (index: number | null): void => {
    const sample = index === null ? undefined : data[index]
    if (sample) seek(sample.time)
  }
  return (
    <figure className="space-y-1.5" data-testid="emotion-chart">
      <figcaption className="text-xs font-semibold text-foreground">Emotion intensity over time</figcaption>
      <ChartContainer config={EMOTION_CONFIG} className={CHART_CLASS} role="img" aria-label="Strongest emotion intensity across the video. The Emotions lane on the timeline shows the same spans.">
        <AreaChart data={data} margin={{ top: 6, right: 12, bottom: 0, left: -18 }} onClick={(state) => seekToIndex(activeIndexOf(state))}>
          <CartesianGrid vertical={false} />
          <XAxis type="number" dataKey="time" domain={[0, model.duration]} tickLine={false} axisLine={false} tickFormatter={(value: number) => formatTimecode(value)} />
          <YAxis domain={[0, 1]} tickCount={3} tickLine={false} axisLine={false} tickFormatter={(value: number) => `${Math.round(value * 100)}%`} />
          <ChartTooltip content={<ChartTooltipContent labelFormatter={(label) => formatTimecode(Number(label), { tenths: true })} formatter={(_value, _name, item) => emotionTooltipRow(item.payload as EmotionSample | undefined)} />} />
          <Area type="stepAfter" dataKey="intensity" stroke="var(--color-intensity)" strokeWidth={1.5} fill="var(--color-intensity)" fillOpacity={0.22} isAnimationActive={!reducedMotion} />
        </AreaChart>
      </ChartContainer>
    </figure>
  )
}
