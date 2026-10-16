import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Languages } from 'lucide-react'
import { Button } from '@/components/Common'
import { api } from '@/lib/api'
import type { DubLanguage } from '@/lib/api/dubbing'
import { cn } from '@/lib/utils'
import { usePolling } from '@/hooks/usePolling'
import { useVideoSourceState } from '@/hooks/useVideoSourceState'
import { buildStatusConfig } from '@/hooks/jobStatus'
import { VideoSourceSelector } from '@/components/shared/VideoSourceSelector'
import type { ProductionItem, UploadItem } from '@/components/shared/VideoSourceSelector'
import { DubbingResults } from '@/components/pages/dubbing/DubbingResults'
import {
  WorkViewShell,
  WorkCreateShell,
  SelectedVideoPreview,
} from '@/components/shared/WorkPageShell'

const ACTIVE_STATUSES = ['pending', 'generating']

const STATUS_CONFIG = buildStatusConfig(
  {
    pending: { label: 'Queued for dubbing...', color: 'text-amber-500' },
    generating: { label: 'Translating and dubbing...', color: 'text-blue-500' },
  },
  {
    completed: { label: 'Dubbing complete', color: 'text-emerald-500' },
    partial: { label: 'Some languages failed', color: 'text-amber-500' },
    failed: { label: 'Dubbing failed', color: 'text-red-500' },
  },
)

export const DubbingWorkPage = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const isViewMode = !!id

  const {
    sourceTab,
    setSourceTab,
    videoUrl,
    gcsUri,
    videoFilename,
    productions,
    uploads,
    loading: loadingSources,
    select,
  } = useVideoSourceState<UploadItem, ProductionItem>(
    {
      loadUploads: () => api.dubbing.listUploadSources(),
      loadProductions: () => api.dubbing.listProductionSources(),
    },
    { enabled: !isViewMode },
  )

  const [languages, setLanguages] = useState<DubLanguage[]>([])
  const [maxLanguages, setMaxLanguages] = useState(4)
  const [selected, setSelected] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.dubbing
      .listLanguages()
      .then((res) => {
        setLanguages(res.languages)
        setMaxLanguages(res.max_languages)
      })
      .catch((err) => console.error('Failed to load dubbing languages', err))
  }, [])

  const { record, loading: recordLoading, error: pollError } = usePolling(
    id,
    api.dubbing.get,
    ACTIVE_STATUSES,
  )

  const languageNames = Object.fromEntries(languages.map((l) => [l.code, l.name]))

  const languageGroups = languages.reduce<{ region: string; items: DubLanguage[] }[]>(
    (groups, lang) => {
      const open = groups[groups.length - 1]
      if (open && open.region === lang.region) open.items.push(lang)
      else groups.push({ region: lang.region, items: [lang] })
      return groups
    },
    [],
  )

  const toggleLanguage = (code: string) =>
    setSelected((prev) =>
      prev.includes(code)
        ? prev.filter((c) => c !== code)
        : prev.length >= maxLanguages
          ? prev
          : [...prev, code],
    )

  const handleStartDub = async () => {
    if (!gcsUri || !selected.length) return
    setSubmitting(true)
    setError(null)
    try {
      const result = await api.dubbing.create({
        gcs_uri: gcsUri,
        source_filename: videoFilename,
        language_codes: selected,
      })
      navigate(`/dubbing/${result.id}`, { replace: true })
    } catch (err: any) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  if (isViewMode) {
    return (
      <WorkViewShell
        backPath="/dubbing"
        backLabel="Back to Dubbing"
        defaultName="Dub"
        loadingLabel="Loading dub..."
        record={record}
        loading={recordLoading}
        pollError={pollError}
        statusConfig={STATUS_CONFIG}
        activeStatuses={ACTIVE_STATUSES}
        onSaveName={(name) => api.dubbing.update(record!.id, { display_name: name })}
        onRetry={id ? () => api.dubbing.retry(id) : undefined}
        retryLabel="Retry failed languages"
        retryStatuses={['failed', 'partial']}
      >
        {(rec) => (
          <>
            {!!rec.variants?.length && (
              <DubbingResults variants={rec.variants} languageNames={languageNames} />
            )}

            {rec.source_transcript && (
              <details className="glass bg-card rounded-xl p-4">
                <summary className="text-xs font-bold uppercase tracking-wider text-muted-foreground cursor-pointer">
                  Original transcript
                </summary>
                <p className="mt-3 text-xs text-foreground/80 leading-relaxed whitespace-pre-wrap">
                  {rec.source_transcript}
                </p>
              </details>
            )}
          </>
        )}
      </WorkViewShell>
    )
  }

  return (
    <WorkCreateShell
      backPath="/dubbing"
      backLabel="Back to Dubbing"
      title="New Dub"
      subtitle="Select a video with spoken audio. Each language is returned as its own dubbed video, with a transcript and subtitles."
      error={error}
      actionIcon={Languages}
      actionLabel="Start Dubbing"
      submitting={submitting}
      disabled={!gcsUri || !selected.length}
      onSubmit={handleStartDub}
    >
      <VideoSourceSelector
        uploads={uploads}
        productions={productions}
        loading={loadingSources}
        sourceTab={sourceTab}
        onTabChange={setSourceTab}
        selectedUri={gcsUri}
        onSelectUpload={(u) =>
          select(u.video_signed_url, u.gcs_uri, u.display_name || u.filename)
        }
        onSelectProduction={(p) =>
          select(p.video_signed_url, p.final_video_url, p.name)
        }
      />

      <SelectedVideoPreview videoUrl={videoUrl} videoFilename={videoFilename} />

      {videoUrl && (
        <div className="space-y-2">
          <div className="flex items-baseline gap-2">
            <span className="text-sm font-medium text-foreground">Target languages</span>
            <span className="text-xs text-muted-foreground">
              {selected.length}/{maxLanguages} selected
            </span>
          </div>
          <div className="space-y-4">
            {languageGroups.map((group) => (
              <div key={group.region} className="space-y-2">
                <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                  {group.region}
                </span>
                <div className="flex flex-wrap gap-3">
                  {group.items.map((lang) => {
                    const isOn = selected.includes(lang.code)
                    const atLimit = !isOn && selected.length >= maxLanguages
                    return (
                      <Button
                        key={lang.code}
                        variant="unstyled"
                        onClick={() => toggleLanguage(lang.code)}
                        disabled={atLimit}
                        className={cn(
                          'flex flex-col items-center gap-1 px-4 py-3 rounded-[6px] border transition-all text-center min-w-[100px]',
                          isOn
                            ? 'bg-accent/10 border-accent text-accent-dark'
                            : 'border-border text-muted-foreground hover:border-accent/30',
                          atLimit && 'opacity-40 cursor-not-allowed',
                        )}
                      >
                        <span className="text-[11px] font-bold uppercase tracking-widest">
                          {lang.name}
                        </span>
                        <span className="text-[10px] text-muted-foreground">{lang.code}</span>
                      </Button>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            The original audio is replaced by the dubbed speech, so background music and effects
            are not preserved. Live Translate offers a single English voice — it has no regional
            English variants.
          </p>
        </div>
      )}
    </WorkCreateShell>
  )
}
