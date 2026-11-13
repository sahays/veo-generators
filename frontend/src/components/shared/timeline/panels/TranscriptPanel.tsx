import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { NativeSelect } from '@/components/ui/select'
import { useSelectItem, useTimelineKit, useWorkspace } from '@/hooks/timeline/timelineContext'
import { useClockValue } from '@/hooks/timeline/useMediaClock'
import { useWindowedList } from '@/hooks/timeline/useWindowedList'
import { cn } from '@/lib/utils'
import type { CueKind, TimelineCue } from '@/types/insights'
import type { IntervalIndex } from '@/types/timeline/intervalIndex'
import { listSpeakers } from '@/types/timeline/model'
import { matchesQuery } from '@/types/timeline/textSearch'
import { formatTimecode } from '@/types/timeline/timeFormat'
import { estimateRowHeight } from '@/types/timeline/windowing'
import { Highlighted, PanelSearch } from './PanelSearch'

const CUE_KINDS: CueKind[] = ['dialogue', 'narration', 'music', 'sfx', 'silence']
const ALL = ''
const CHAR_PX = 6.4
const LINE_PX = 18
const ROW_CHROME_PX = 34
const identity = (value: string | null): string | null => value

interface CueFilters {
  speaker: string
  kind: string
}

function useFilteredCues(cues: IntervalIndex<TimelineCue>, filters: CueFilters): TimelineCue[] {
  const search = useWorkspace((state) => state.search)
  return useMemo(
    () =>
      cues.items.filter(
        (cue) =>
          (filters.kind === ALL || cue.kind === filters.kind) &&
          (filters.speaker === ALL || cue.speaker === filters.speaker) &&
          matchesQuery(search, cue.text, cue.speaker),
      ),
    [cues, filters.kind, filters.speaker, search],
  )
}

interface CueRowProps {
  cue: TimelineCue
  active: boolean
  query: string
}

function CueRow({ cue, active, query }: CueRowProps): JSX.Element {
  const select = useSelectItem()
  const spoken = cue.kind === 'dialogue' || cue.kind === 'narration'
  return (
    <div role="listitem" data-cue-id={cue.id} data-active={active || undefined}>
      <Button
        variant="unstyled"
        aria-current={active ? 'true' : undefined}
        className={cn('block w-full rounded-md border-l-2 px-2.5 py-1.5 text-left transition-colors hover:bg-muted/60', active ? 'border-accent bg-accent/10' : 'border-transparent')}
        onClick={() => select({ kind: 'cue', id: cue.id, label: cue.text, range: cue })}
      >
        <span className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
          <span className="font-mono tabular-nums">{formatTimecode(cue.start_sec)}</span>
          {cue.speaker && <span className="font-semibold text-accent-dark"><Highlighted text={cue.speaker} query={query} /></span>}
          {!spoken && <Badge>{cue.kind}</Badge>}
        </span>
        <span className={cn('block text-xs leading-[18px] text-foreground', !spoken && 'italic text-muted-foreground')}>
          <Highlighted text={cue.text} query={query} />
        </span>
      </Button>
    </div>
  )
}

interface FiltersBarProps {
  speakers: string[]
  filters: CueFilters
  onChange: (filters: CueFilters) => void
  shown: number
  total: number
}

function FiltersBar({ speakers, filters, onChange, shown, total }: FiltersBarProps): JSX.Element {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <PanelSearch placeholder="Search transcript" className="flex-1" />
      <NativeSelect aria-label="Filter by speaker" className="h-8 px-1.5 py-0 text-xs" value={filters.speaker} onChange={(event) => onChange({ ...filters, speaker: event.target.value })}>
        <option value={ALL}>All speakers</option>
        {speakers.map((speaker) => (
          <option key={speaker} value={speaker}>{speaker}</option>
        ))}
      </NativeSelect>
      <NativeSelect aria-label="Filter by cue kind" className="h-8 px-1.5 py-0 text-xs" value={filters.kind} onChange={(event) => onChange({ ...filters, kind: event.target.value })}>
        <option value={ALL}>All kinds</option>
        {CUE_KINDS.map((kind) => (
          <option key={kind} value={kind}>{kind}</option>
        ))}
      </NativeSelect>
      <span aria-live="polite" className="text-[10px] tabular-nums text-muted-foreground">{shown} of {total}</span>
    </div>
  )
}

/** Keep the active cue in view, unless the reader is using the list (pointer over it or focus inside). */
function useFollowActive(activeIndex: number | undefined, reveal: (index: number) => void): React.RefObject<HTMLDivElement> {
  const busy = useRef<HTMLDivElement>(null)
  const follow = useWorkspace((state) => state.followPlayhead)
  useEffect(() => {
    const node = busy.current
    if (activeIndex === undefined || !follow || !node) return
    if (node.matches(':hover') || node.contains(document.activeElement)) return
    reveal(activeIndex)
  }, [activeIndex, follow, reveal])
  return busy
}

export interface TranscriptPanelProps {
  cues: IntervalIndex<TimelineCue>
  className?: string
}

/**
 * Full cue list. Search (highlighted), filter by speaker and kind, click a
 * line to seek. The line under the playhead is highlighted and kept in view
 * by scrolling the list itself, never the page. Only the rows near the
 * scroll position are mounted, so long transcripts stay light.
 */
export function TranscriptPanel({ cues, className }: TranscriptPanelProps): JSX.Element {
  const { clock } = useTimelineKit()
  const query = useWorkspace((state) => state.search)
  const [filters, setFilters] = useState<CueFilters>({ speaker: ALL, kind: ALL })
  const speakers = useMemo(() => listSpeakers(cues.items), [cues])
  const filtered = useFilteredCues(cues, filters)
  const [charsPerLine, setCharsPerLine] = useState(60)
  const heights = useMemo(() => filtered.map((cue) => estimateRowHeight(cue.text.length, charsPerLine, LINE_PX, ROW_CHROME_PX)), [filtered, charsPerLine])
  const list = useWindowedList(heights)
  useEffect(() => setCharsPerLine(Math.max(Math.floor((list.width - 24) / CHAR_PX), 20)), [list.width])
  const indexById = useMemo(() => new Map(filtered.map((cue, i) => [cue.id, i])), [filtered])
  const activeAt = useCallback((timeSec: number) => cues.firstAt(timeSec)?.id ?? null, [cues])
  const activeId = useClockValue(clock, activeAt, identity)
  const hoverRef = useFollowActive(activeId ? indexById.get(activeId) : undefined, list.reveal)

  return (
    <div className={cn('flex min-h-0 flex-col gap-2', className)}>
      <FiltersBar speakers={speakers} filters={filters} onChange={setFilters} shown={filtered.length} total={cues.size} />
      <div ref={hoverRef} className="min-h-0 flex-1">
        <div ref={list.containerRef} role="list" aria-label="Transcript" data-testid="transcript-list" className="h-full overflow-y-auto overscroll-contain pr-1">
          <div style={{ height: list.window.padTop }} />
          {filtered.slice(list.window.start, list.window.end).map((cue) => (
            <CueRow key={cue.id} cue={cue} active={cue.id === activeId} query={query} />
          ))}
          <div style={{ height: list.window.padBottom }} />
          {filtered.length === 0 && <p className="py-8 text-center text-xs text-muted-foreground">No cues match.</p>}
        </div>
      </div>
    </div>
  )
}
