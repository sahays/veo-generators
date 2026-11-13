import { useEffect, useState } from 'react'
import { Loader2, ScanSearch } from 'lucide-react'
import { ErrorDisplay } from '@/components/shared/ErrorDisplay'
import { VideoSourcePicker } from '@/components/shared/media/VideoSourcePicker'
import { DurationPill, RecordStatusPill } from '@/components/shared/timeline'
import { SelectedVideoPreview } from '@/components/shared/WorkPageShell'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { api } from '@/hooks/useApiClient'
import type { EngagementAnalysisSource } from '@/lib/api/endpoints/engagement'
import { cn, getTimeAgo } from '@/lib/utils'
import type { VideoChoice } from '@/types/engagement/createForm'
import type { EngagementForm } from './useEngagementForm'

type AnalysisSource = EngagementAnalysisSource

interface AnalysisSources {
  items: AnalysisSource[]
  loading: boolean
  error: string | null
}

const sourceName = (source: AnalysisSource): string => source.display_name || source.video_filename || 'Untitled video'

function analysisChoice(source: AnalysisSource): VideoChoice {
  return { kind: 'analysis', analysisId: source.id, name: sourceName(source), videoUrl: source.video_signed_url }
}

/** Scene analyses an engagement job can reuse. `preselectId` (from `?analysis=`) is picked once the list has loaded. */
function useAnalysisSources(preselectId: string | null, pick: (choice: VideoChoice) => void): AnalysisSources {
  const [state, setState] = useState<AnalysisSources>({ items: [], loading: true, error: null })
  useEffect(() => {
    let current = true
    api.engagement
      .listAnalysisSources()
      .then((items) => {
        if (!current) return
        setState({ items, loading: false, error: null })
        const wanted = items.find((item) => item.id === preselectId && item.status !== 'failed')
        if (wanted) pick(analysisChoice(wanted))
      })
      .catch((cause: unknown) => current && setState({ items: [], loading: false, error: cause instanceof Error ? cause.message : 'Could not list the analysed videos' }))
    return () => {
      current = false
    }
    // Runs once: the list is loaded when the form opens and `pick` is only used for the preselection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return state
}

/** What choosing this analysis means for the job, by its status. */
function statusNote(source: AnalysisSource): string {
  if (source.status === 'completed') return 'Analysis is reused'
  if (source.status === 'failed') return 'Analysis failed. Retry it in Scene Analysis first'
  return 'Still being analysed. The report starts when it finishes'
}

interface AnalysisRowProps {
  source: AnalysisSource
  selected: boolean
  onPick: () => void
}

function AnalysisRow({ source, selected, onPick }: AnalysisRowProps): JSX.Element {
  return (
    <li>
      <Button
        variant="unstyled"
        aria-pressed={selected}
        disabled={source.status === 'failed'}
        data-testid={`analysis-${source.id}`}
        onClick={onPick}
        className={cn('flex w-full items-center gap-3 rounded-[6px] border p-3 text-left transition-all disabled:cursor-not-allowed disabled:opacity-60', selected ? 'border-accent bg-accent/5' : 'border-border bg-card hover:border-accent/40')}
      >
        <ScanSearch size={18} aria-hidden className="shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-foreground">{sourceName(source)}</span>
          <span className="block text-[10px] text-muted-foreground">{statusNote(source)} · {getTimeAgo(source.createdAt)}</span>
        </span>
        {source.duration_sec > 0 && <DurationPill seconds={source.duration_sec} />}
        <RecordStatusPill status={source.status} />
      </Button>
    </li>
  )
}

interface AnalysisListProps {
  sources: AnalysisSources
  selectedId: string | null
  missingId: string | null
  onPick: (choice: VideoChoice) => void
}

function AnalysisList({ sources, selectedId, missingId, onPick }: AnalysisListProps): JSX.Element {
  if (sources.loading) {
    return (
      <div role="status" className="flex justify-center py-10">
        <Loader2 size={24} className="animate-spin text-accent motion-reduce:animate-none" aria-label="Loading analysed videos" />
      </div>
    )
  }
  if (sources.error) return <ErrorDisplay error={sources.error} />
  return (
    <div className="space-y-2">
      {missingId && <p role="status" className="text-xs text-amber-600 dark:text-amber-400">The scene analysis from the link is not available. Pick a video below.</p>}
      {sources.items.length === 0 && <p className="py-6 text-center text-sm text-muted-foreground">No analysed videos yet. Pick one under “Other videos”; it is analysed first, automatically.</p>}
      <ul aria-label="Analysed videos" className="max-h-80 space-y-2 overflow-y-auto pr-1">
        {sources.items.map((source) => (
          <AnalysisRow key={source.id} source={source} selected={source.id === selectedId} onPick={() => onPick(analysisChoice(source))} />
        ))}
      </ul>
    </div>
  )
}

export interface VideoStepProps {
  form: EngagementForm
  /** Scene analysis id from `?analysis=`, selected when the list loads. */
  preselectId: string | null
}

/** Step 1: an already analysed video (reused as is), or any other upload or production (analysed first). */
export function VideoStep({ form, preselectId }: VideoStepProps): JSX.Element {
  const sources = useAnalysisSources(preselectId, form.pickAnalysis)
  const video = form.state.video
  const selectedId = video?.kind === 'analysis' ? video.analysisId : null
  const missing = preselectId && !sources.loading && !sources.items.some((item) => item.id === preselectId) ? preselectId : null
  return (
    <div className="space-y-4">
      <Tabs defaultValue="analysed">
        <TabsList aria-label="Where the video comes from">
          <TabsTrigger value="analysed">Analysed videos</TabsTrigger>
          <TabsTrigger value="other">Other videos</TabsTrigger>
        </TabsList>
        <TabsContent value="analysed" className="space-y-2">
          <p className="text-xs text-muted-foreground">These videos already have a scene analysis. It is reused; the video is not analysed again.</p>
          <AnalysisList sources={sources} selectedId={selectedId} missingId={missing} onPick={form.pickAnalysis} />
        </TabsContent>
        <TabsContent value="other" className="space-y-2">
          <p className="text-xs text-muted-foreground">Pick any upload or production. The video is analysed first, automatically (an existing analysis of it is reused); the engagement report starts when that finishes.</p>
          <VideoSourcePicker picker={form.picker} />
        </TabsContent>
      </Tabs>
      <SelectedVideoPreview videoUrl={video?.videoUrl ?? null} videoFilename={video?.name} />
    </div>
  )
}
