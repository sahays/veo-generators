import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Languages, Loader2, RotateCcw } from 'lucide-react'
import { Button } from '@/components/Common'
import { api } from '@/lib/api'
import type { DubLanguage } from '@/lib/api/dubbing'
import { useAuthStore } from '@/store/useAuthStore'
import { cn } from '@/lib/utils'
import { usePolling } from '@/hooks/usePolling'
import { useVideoSourceState } from '@/hooks/useVideoSourceState'
import { buildStatusConfig } from '@/hooks/jobStatus'
import { VideoSourceSelector } from '@/components/shared/VideoSourceSelector'
import type { ProductionItem, UploadItem } from '@/components/shared/VideoSourceSelector'
import { DubbingResults } from '@/components/pages/dubbing/DubbingResults'
import { ProgressBar } from '@/components/shared/ProgressBar'
import { ErrorDisplay } from '@/components/shared/ErrorDisplay'
import { WorkPageHeader } from '@/components/shared/WorkPageHeader'

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
  const canWrite = useAuthStore((s) => s.isMaster || s.isPower)
  const isViewMode = !!id

  const {
    sourceTab, setSourceTab,
    videoUrl, gcsUri, videoFilename,
    productions, uploads, loading: loadingSources,
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
  const [retrying, setRetrying] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Language list comes from the backend so it can never disagree with the
  // allowlist the create endpoint validates against.
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

  // Group for display, preserving the order the backend sent — that order is
  // the language table's own, so groups stay contiguous without sorting here.
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

  const handleRetry = async () => {
    if (!id) return
    setRetrying(true)
    try {
      await api.dubbing.retry(id)
    } catch (err: any) {
      console.error('Failed to retry dub', err)
    } finally {
      setRetrying(false)
    }
  }

  // --- View Mode ---
  if (isViewMode) {
    if (recordLoading) {
      return (
        <div className="flex flex-col items-center justify-center py-32 space-y-4">
          <Loader2 className="animate-spin text-accent" size={32} />
          <p className="text-sm text-muted-foreground">Loading dub...</p>
        </div>
      )
    }

    if (pollError && !record) {
      return (
        <div className="space-y-4">
          <button onClick={() => navigate('/dubbing')} className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors">
            <ArrowLeft size={16} /> Back to Dubbing
          </button>
          <ErrorDisplay error={pollError} size="md" />
        </div>
      )
    }

    if (!record) return null

    const isProcessing = ACTIVE_STATUSES.includes(record.status)
    const canRetry = record.status === 'failed' || record.status === 'partial'

    return (
      <div className="space-y-6">
        <WorkPageHeader
          backPath="/dubbing"
          backLabel="Back to Dubbing"
          record={record}
          defaultName="Dub"
          onSaveName={(name) => api.dubbing.update(record.id, { display_name: name })}
          statusConfig={STATUS_CONFIG}
          activeStatuses={ACTIVE_STATUSES}
        />

        {isProcessing && <ProgressBar progress={record.progress_pct} />}

        {canRetry && (
          <div className="space-y-3">
            {record.error_message && <ErrorDisplay error={record.error_message} size="md" />}
            {canWrite && (
              <Button icon={retrying ? Loader2 : RotateCcw} onClick={handleRetry} disabled={retrying}>
                {retrying ? 'Retrying...' : 'Retry failed languages'}
              </Button>
            )}
          </div>
        )}

        {!!record.variants?.length && (
          <DubbingResults variants={record.variants} languageNames={languageNames} />
        )}

        {record.source_transcript && (
          <details className="glass bg-card rounded-xl p-4">
            <summary className="text-xs font-bold uppercase tracking-wider text-muted-foreground cursor-pointer">
              Original transcript
            </summary>
            <p className="mt-3 text-xs text-foreground/80 leading-relaxed whitespace-pre-wrap">
              {record.source_transcript}
            </p>
          </details>
        )}
      </div>
    )
  }

  // --- Create Mode ---
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <button onClick={() => navigate('/dubbing')} className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors">
          <ArrowLeft size={16} /> Back to Dubbing
        </button>
      </div>

      <div className="space-y-1">
        <h2 className="text-lg font-heading font-bold text-foreground">New Dub</h2>
        <p className="text-sm text-muted-foreground">
          Select a video with spoken audio. Each language is returned as its own dubbed video, with a transcript and subtitles.
        </p>
      </div>

      <VideoSourceSelector
        uploads={uploads}
        productions={productions}
        loading={loadingSources}
        sourceTab={sourceTab}
        onTabChange={setSourceTab}
        selectedUri={gcsUri}
        onSelectUpload={(upload) =>
          select(upload.video_signed_url, upload.gcs_uri, upload.display_name || upload.filename)
        }
        onSelectProduction={(prod) =>
          select(prod.video_signed_url, prod.final_video_url, prod.name)
        }
      />

      {videoUrl && (
        <div className="space-y-3">
          <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Selected Video</h3>
          <div className="aspect-video bg-black rounded-xl overflow-hidden border border-border max-w-lg">
            <video src={videoUrl} controls className="w-full h-full object-contain" />
          </div>
          <p className="text-sm text-foreground font-medium">{videoFilename}</p>
        </div>
      )}

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
                      <button
                        key={lang.code}
                        type="button"
                        onClick={() => toggleLanguage(lang.code)}
                        disabled={atLimit}
                        className={cn(
                          'flex flex-col items-center gap-1 px-4 py-3 rounded-xl border transition-all text-center min-w-[100px]',
                          isOn
                            ? 'bg-accent/10 border-accent text-accent-dark'
                            : 'border-border text-muted-foreground hover:border-accent/30',
                          atLimit && 'opacity-40 cursor-not-allowed',
                        )}
                      >
                        <span className="text-[11px] font-bold uppercase tracking-widest">{lang.name}</span>
                        <span className="text-[10px] text-muted-foreground">{lang.code}</span>
                      </button>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            The original audio is replaced by the dubbed speech, so background music and effects are not preserved.
            Live Translate offers a single English voice — it has no regional English variants.
          </p>
        </div>
      )}

      <ErrorDisplay error={error} />

      <div className="flex items-center justify-end gap-4">
        <Button
          icon={Languages}
          onClick={handleStartDub}
          disabled={!gcsUri || !selected.length || submitting}
          className={cn(submitting && '[&_svg]:animate-spin')}
        >
          {submitting ? 'Starting...' : 'Start Dubbing'}
        </Button>
      </div>
    </div>
  )
}
