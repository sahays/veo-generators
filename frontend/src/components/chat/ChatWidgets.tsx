import React, { useState, useEffect } from 'react'
import { Play, FileVideo, CheckCircle2, Clock, ChevronRight, Film, Upload, Sparkles, Loader2, AlertCircle, X, RefreshCw, Clapperboard, Smartphone, Image, Search, LayoutGrid } from 'lucide-react'
import { Link } from 'react-router-dom'
import { cn, getTimeAgo, formatFileSize } from '@/lib/utils'
import { api } from '@/lib/api'

// ── Types ────────────────────────────────────────────────────────────

type ConfirmationJobType = 'promo' | 'reframe' | 'production' | 'key_moments' | 'thumbnails' | 'adapts'
type ConfirmationStatus = 'pending' | 'confirming' | 'confirmed' | 'cancelled' | 'failed'

export interface ConfirmationData {
  job_type: ConfirmationJobType
  title: string
  params: Record<string, any>
  resolved: Record<string, string>
}

// ── Helpers ──────────────────────────────────────────────────────────

const JOB_ICONS: Record<ConfirmationJobType, React.ReactNode> = {
  promo: <Clapperboard size={16} />,
  reframe: <Smartphone size={16} />,
  production: <Film size={16} />,
  key_moments: <Search size={16} />,
  thumbnails: <Image size={16} />,
  adapts: <LayoutGrid size={16} />,
}

const ROUTE_MAP: Record<ConfirmationJobType, (id: string) => string> = {
  promo: (id) => `/promos/${id}`,
  reframe: (id) => `/orientations/${id}`,
  production: (id) => `/productions/${id}`,
  key_moments: (id) => `/key-moments/${id}`,
  thumbnails: (id) => `/thumbnails/${id}`,
  adapts: (id) => `/adapts/${id}`,
}

async function executeJob(jobType: ConfirmationJobType, params: Record<string, any>): Promise<any> {
  // params are dynamically built from agent proposals — cast to satisfy typed API signatures
  const p = params as any
  switch (jobType) {
    case 'promo': return api.promo.create(p)
    case 'reframe': return api.reframe.create(p)
    case 'production': return api.projects.create(p)
    case 'key_moments': return api.keyMoments.analyze(p)
    case 'thumbnails': return api.thumbnails.analyze(p)
    case 'adapts': return api.adapts.create(p)
  }
}

const DURATION_OPTIONS = [
  { value: 60, label: '1m' },
  { value: 90, label: '1.5m' },
  { value: 120, label: '2m' },
  { value: 150, label: '2.5m' },
  { value: 180, label: '3m' },
]

const CONTENT_TYPE_OPTIONS = [
  { value: 'movies', label: 'Movies' },
  { value: 'documentaries', label: 'Documentaries' },
  { value: 'sports', label: 'Sports' },
  { value: 'podcasts', label: 'Podcasts' },
  { value: 'promos', label: 'Promos' },
  { value: 'news', label: 'News' },
  { value: 'other', label: 'Other' },
]

// ── Per-type field renderers ─────────────────────────────────────────

const DisplayField: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="flex items-center justify-between gap-2 py-1">
    <span className="text-[10px] font-medium uppercase tracking-wider text-slate-400">{label}</span>
    <span className="text-[11px] font-medium text-slate-700 dark:text-slate-200 truncate max-w-[60%] text-right">{value || 'Default'}</span>
  </div>
)

const ToggleField: React.FC<{ label: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }> = ({ label, checked, onChange, disabled }) => (
  <label className={cn("flex items-center justify-between gap-2 py-1 cursor-pointer", disabled && "opacity-50 pointer-events-none")}>
    <span className="text-[10px] font-medium uppercase tracking-wider text-slate-400">{label}</span>
    <button
      type="button"
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative h-4 w-7 rounded-full transition-colors",
        checked ? "bg-indigo-500" : "bg-slate-300 dark:bg-slate-600"
      )}
    >
      <span className={cn(
        "absolute top-0.5 left-0.5 h-3 w-3 rounded-full bg-white shadow transition-transform",
        checked && "translate-x-3"
      )} />
    </button>
  </label>
)

const PromoFields: React.FC<{ params: Record<string, any>; resolved: Record<string, string>; onChange: (p: Record<string, any>) => void; disabled: boolean }> = ({ params, resolved, onChange, disabled }) => (
  <div className="space-y-1">
    <DisplayField label="Source" value={resolved.source_name} />
    <div className="py-1">
      <span className="text-[10px] font-medium uppercase tracking-wider text-slate-400">Duration</span>
      <div className="flex gap-1 mt-1">
        {DURATION_OPTIONS.map(opt => (
          <button
            key={opt.value}
            disabled={disabled}
            onClick={() => onChange({ ...params, target_duration: opt.value })}
            className={cn(
              "flex-1 py-1 rounded-md text-[10px] font-bold transition-all",
              params.target_duration === opt.value
                ? "bg-indigo-500 text-white shadow-sm"
                : "bg-slate-100 text-slate-500 hover:bg-slate-200 dark:bg-slate-700 dark:text-slate-400 dark:hover:bg-slate-600",
              disabled && "pointer-events-none"
            )}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
    <ToggleField label="Text overlays" checked={params.text_overlay} onChange={v => onChange({ ...params, text_overlay: v })} disabled={disabled} />
    <ToggleField label="Thumbnail card" checked={params.generate_thumbnail} onChange={v => onChange({ ...params, generate_thumbnail: v })} disabled={disabled} />
  </div>
)

const ReframeFields: React.FC<{ params: Record<string, any>; resolved: Record<string, string>; onChange: (p: Record<string, any>) => void; disabled: boolean }> = ({ params, resolved, onChange, disabled }) => (
  <div className="space-y-1">
    <DisplayField label="Source" value={resolved.source_name} />
    <div className="flex items-center justify-between gap-2 py-1">
      <span className="text-[10px] font-medium uppercase tracking-wider text-slate-400">Content type</span>
      <select
        value={params.content_type}
        onChange={e => onChange({ ...params, content_type: e.target.value })}
        disabled={disabled}
        className="rounded-md border border-slate-200 bg-white px-2 py-0.5 text-[11px] font-medium text-slate-700 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-200"
      >
        {CONTENT_TYPE_OPTIONS.map(opt => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
    </div>
    <ToggleField label="Blurred background" checked={params.blurred_bg} onChange={v => onChange({ ...params, blurred_bg: v, ...(v ? { vertical_split: false } : {}) })} disabled={disabled} />
    <ToggleField label="Vertical split" checked={params.vertical_split} onChange={v => onChange({ ...params, vertical_split: v, ...(v ? { blurred_bg: false } : {}) })} disabled={disabled} />
  </div>
)

const ProductionFields: React.FC<{ params: Record<string, any>; resolved: Record<string, string>; onChange: (p: Record<string, any>) => void; disabled: boolean }> = ({ params, resolved, onChange, disabled }) => (
  <div className="space-y-1.5">
    <div>
      <span className="text-[10px] font-medium uppercase tracking-wider text-slate-400">Name</span>
      <input
        type="text"
        value={params.name}
        onChange={e => onChange({ ...params, name: e.target.value })}
        disabled={disabled}
        className="mt-0.5 w-full rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-700 focus:border-indigo-400 focus:outline-none dark:border-slate-600 dark:bg-slate-700 dark:text-slate-200"
      />
    </div>
    <div>
      <span className="text-[10px] font-medium uppercase tracking-wider text-slate-400">Concept</span>
      <textarea
        value={params.base_concept}
        onChange={e => onChange({ ...params, base_concept: e.target.value })}
        disabled={disabled}
        rows={2}
        className="mt-0.5 w-full rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-700 focus:border-indigo-400 focus:outline-none resize-none dark:border-slate-600 dark:bg-slate-700 dark:text-slate-200"
      />
    </div>
    {resolved.prompt_name && <DisplayField label="Prompt" value={resolved.prompt_name} />}
  </div>
)

const KeyMomentsFields: React.FC<{ resolved: Record<string, string> }> = ({ resolved }) => (
  <div className="space-y-1">
    <DisplayField label="Source" value={resolved.source_name} />
    {resolved.prompt_name && <DisplayField label="Prompt" value={resolved.prompt_name} />}
  </div>
)

const AdaptsFields: React.FC<{ params: Record<string, any>; resolved: Record<string, string>; onChange: (p: Record<string, any>) => void; disabled: boolean }> = ({ params, resolved, onChange, disabled }) => {
  const ratios: string[] = params.aspect_ratios || []
  const allRatios = ['16:9', '9:16', '1:1', '4:5', '4:3', '3:4']
  const toggle = (r: string) => {
    const next = ratios.includes(r) ? ratios.filter(x => x !== r) : [...ratios, r]
    onChange({ ...params, aspect_ratios: next })
  }
  return (
    <div className="space-y-1">
      <DisplayField label="Source" value={resolved.source_name} />
      <div className="py-1">
        <span className="text-[10px] font-medium uppercase tracking-wider text-slate-400">Aspect ratios</span>
        <div className="flex flex-wrap gap-1 mt-1">
          {allRatios.map(r => (
            <button
              key={r}
              disabled={disabled}
              onClick={() => toggle(r)}
              className={cn(
                "px-2 py-0.5 rounded-md text-[10px] font-bold transition-all",
                ratios.includes(r)
                  ? "bg-indigo-500 text-white"
                  : "bg-slate-100 text-slate-500 hover:bg-slate-200 dark:bg-slate-700 dark:text-slate-400",
                disabled && "pointer-events-none"
              )}
            >
              {r}
            </button>
          ))}
        </div>
      </div>
      {resolved.preset_name && <DisplayField label="Preset" value={resolved.preset_name} />}
    </div>
  )
}

// ── ConfirmationCard ─────────────────────────────────────────────────

export const ConfirmationCard: React.FC<{
  confirmation: ConfirmationData
  onConfirmed: (jobType: ConfirmationJobType, result: any) => void
  onFailed: (error: string) => void
}> = ({ confirmation, onConfirmed, onFailed }) => {
  const [localParams, setLocalParams] = useState(confirmation.params)
  const [status, setStatus] = useState<ConfirmationStatus>('pending')
  const [error, setError] = useState<string | null>(null)
  const [resultId, setResultId] = useState<string | null>(null)

  const disabled = status !== 'pending'
  const { job_type, title, resolved } = confirmation

  const handleConfirm = async () => {
    setStatus('confirming')
    setError(null)
    try {
      const result = await executeJob(job_type, localParams)
      setStatus('confirmed')
      setResultId(result.id)
      onConfirmed(job_type, result)
    } catch (err: any) {
      setStatus('failed')
      const msg = err.message || 'Something went wrong'
      setError(msg)
      onFailed(msg)
    }
  }

  const handleRetry = () => {
    setStatus('pending')
    setError(null)
  }

  const handleCancel = () => {
    setStatus('cancelled')
  }

  return (
    <div className="mt-3 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-800">
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-slate-100 bg-slate-50 px-3 py-2 dark:border-slate-700 dark:bg-slate-800/80">
        <div className="flex h-6 w-6 items-center justify-center rounded-md bg-indigo-100 text-indigo-600 dark:bg-indigo-900/40 dark:text-indigo-400">
          {JOB_ICONS[job_type]}
        </div>
        <span className="text-[11px] font-semibold text-slate-900 dark:text-white flex-1 truncate">{title}</span>
        {status === 'confirmed' && <CheckCircle2 size={14} className="text-green-500" />}
        {status === 'cancelled' && <X size={14} className="text-slate-400" />}
      </div>

      {/* Body */}
      <div className="px-3 py-2">
        {status === 'cancelled' ? (
          <p className="text-[11px] text-slate-400 italic">Cancelled</p>
        ) : status === 'confirmed' && resultId ? (
          <div className="flex items-center gap-2">
            <CheckCircle2 size={14} className="text-green-500 flex-shrink-0" />
            <span className="text-[11px] text-slate-600 dark:text-slate-300">Job created</span>
            <Link
              to={ROUTE_MAP[job_type](resultId)}
              className="ml-auto text-[10px] font-bold text-indigo-600 hover:text-indigo-500 dark:text-indigo-400"
            >
              View
            </Link>
          </div>
        ) : (
          <>
            {job_type === 'promo' && <PromoFields params={localParams} resolved={resolved} onChange={setLocalParams} disabled={disabled} />}
            {job_type === 'reframe' && <ReframeFields params={localParams} resolved={resolved} onChange={setLocalParams} disabled={disabled} />}
            {job_type === 'production' && <ProductionFields params={localParams} resolved={resolved} onChange={setLocalParams} disabled={disabled} />}
            {(job_type === 'key_moments' || job_type === 'thumbnails') && <KeyMomentsFields resolved={resolved} />}
            {job_type === 'adapts' && <AdaptsFields params={localParams} resolved={resolved} onChange={setLocalParams} disabled={disabled} />}

            {error && (
              <div className="mt-2 flex items-start gap-1.5 rounded-lg bg-red-50 px-2 py-1.5 dark:bg-red-900/20">
                <AlertCircle size={12} className="mt-0.5 text-red-500 flex-shrink-0" />
                <span className="text-[10px] text-red-600 dark:text-red-400">{error}</span>
              </div>
            )}
          </>
        )}
      </div>

      {/* Footer */}
      {(status === 'pending' || status === 'confirming' || status === 'failed') && (
        <div className="flex items-center gap-2 border-t border-slate-100 px-3 py-2 dark:border-slate-700">
          {status === 'failed' ? (
            <button
              onClick={handleRetry}
              className="flex items-center gap-1 rounded-lg px-3 py-1 text-[10px] font-bold text-slate-500 transition-colors hover:bg-slate-100 dark:hover:bg-slate-700"
            >
              <RefreshCw size={10} /> Retry
            </button>
          ) : (
            <button
              onClick={handleCancel}
              disabled={status === 'confirming'}
              className="rounded-lg px-3 py-1 text-[10px] font-bold text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 disabled:pointer-events-none dark:hover:bg-slate-700"
            >
              Cancel
            </button>
          )}
          <button
            onClick={handleConfirm}
            disabled={status === 'confirming'}
            className="ml-auto flex items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1 text-[10px] font-bold text-white shadow-sm transition-all hover:bg-indigo-500 disabled:opacity-60 disabled:pointer-events-none"
          >
            {status === 'confirming' ? (
              <><Loader2 size={10} className="animate-spin" /> Confirming...</>
            ) : (
              <><CheckCircle2 size={10} /> Confirm</>
            )}
          </button>
        </div>
      )}
    </div>
  )
}

// --- Video Result Card ---
export const VideoResultCard: React.FC<{ 
  title: string, 
  status: string, 
  id: string, 
  type: 'promo' | 'reframe' | 'production' 
}> = ({ title, status, id, type }) => {
  const pathMap = {
    promo: `/promos/${id}`,
    reframe: `/orientations/${id}`,
    production: `/productions/${id}`
  }

  return (
    <div className="mt-2 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-800">
      <div className="flex items-center gap-3 p-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-100 text-indigo-600 dark:bg-indigo-900/40 dark:text-indigo-400">
          <FileVideo size={20} />
        </div>
        <div className="flex-1 min-w-0">
          <h5 className="truncate text-xs font-semibold text-slate-900 dark:text-white">{title || 'Untitled Video'}</h5>
          <div className="flex items-center gap-1.5 mt-0.5">
            {status === 'completed' ? (
              <CheckCircle2 size={12} className="text-green-500" />
            ) : (
              <Clock size={12} className="text-amber-500 animate-pulse" />
            )}
            <span className="text-[10px] uppercase tracking-wider text-slate-500">{status}</span>
          </div>
        </div>
        <Link 
          to={pathMap[type]}
          className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-100 text-slate-600 transition-colors hover:bg-indigo-600 hover:text-white dark:bg-slate-700 dark:text-slate-300"
        >
          <ChevronRight size={16} />
        </Link>
      </div>
      {status === 'completed' && (
        <div className="aspect-video bg-slate-900 flex items-center justify-center group relative cursor-pointer">
           <Play size={24} className="text-white opacity-50 group-hover:opacity-100 transition-opacity" />
           <div className="absolute inset-0 bg-gradient-to-t from-black/40 to-transparent" />
        </div>
      )}
    </div>
  )
}

// --- Universal Video Source Picker (Reused logic from VideoSourceSelector) ---
export const VideoSourcePicker: React.FC<{
  onSelect: (gcs_uri: string, filename: string, type: string) => void
}> = ({ onSelect }) => {
  const [tab, setTab] = useState<'uploads' | 'productions'>('uploads')
  const [uploads, setUploads] = useState<any[]>([])
  const [productions, setProductions] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      api.promo.listUploadSources().catch(() => []),
      api.promo.listProductionSources().catch(() => [])
    ]).then(([ups, prods]) => {
      setUploads(ups)
      setProductions(prods)
      setLoading(false)
    })
  }, [])

  return (
    <div className="mt-3 space-y-2">
      <div className="flex gap-1 bg-slate-100 p-1 rounded-lg dark:bg-slate-800">
        {([['uploads', Upload, 'Uploads'], ['productions', Film, 'Productions']] as const).map(([key, Icon, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={cn(
              "flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all",
              tab === key ? "bg-white text-indigo-600 shadow-sm dark:bg-slate-700 dark:text-indigo-400" : "text-slate-500"
            )}
          >
            <Icon size={12} /> {label}
          </button>
        ))}
      </div>

      <div className="max-h-48 overflow-y-auto space-y-1 pr-1 scrollbar-thin">
        {loading ? (
          <div className="py-8 flex justify-center"><Clock className="animate-spin text-slate-300" size={16} /></div>
        ) : tab === 'uploads' ? (
          uploads.map(u => (
            <button
              key={u.id}
              onClick={() => onSelect(u.gcs_uri, u.display_name || u.filename, 'upload')}
              className="flex w-full items-center gap-2 rounded-lg border border-slate-200 bg-white p-2 text-left text-[11px] transition-all hover:border-indigo-500 hover:bg-indigo-50 dark:border-slate-700 dark:bg-slate-800 dark:hover:bg-indigo-900/20"
            >
              <FileVideo size={12} className="text-slate-400" />
              <div className="flex-1 min-w-0">
                <p className="truncate font-medium text-slate-900 dark:text-white">{u.display_name || u.filename}</p>
                <p className="text-[9px] text-slate-500">{formatFileSize(u.file_size_bytes)}</p>
              </div>
            </button>
          ))
        ) : (
          productions.map(p => (
            <button
              key={p.id}
              onClick={() => onSelect(p.final_video_url, p.name, 'production')}
              className="flex w-full items-center gap-2 rounded-lg border border-slate-200 bg-white p-2 text-left text-[11px] transition-all hover:border-indigo-500 hover:bg-indigo-50 dark:border-slate-700 dark:bg-slate-800 dark:hover:bg-indigo-900/20"
            >
              <Film size={12} className="text-slate-400" />
              <div className="flex-1 min-w-0">
                <p className="truncate font-medium text-slate-900 dark:text-white">{p.name}</p>
                <p className="text-[9px] text-slate-500">{p.orientation}</p>
              </div>
            </button>
          ))
        )}
      </div>
    </div>
  )
}

// --- Prompt Picker Widget ---
export const PromptPicker: React.FC<{
  category: string,
  onSelect: (id: string, name: string) => void
}> = ({ category, onSelect }) => {
  const [prompts, setPrompts] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.system.listResources('prompt', category).then(res => {
      setPrompts(res)
      setLoading(false)
    })
  }, [category])

  return (
    <div className="mt-3 space-y-2">
      <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500 flex items-center gap-1">
        <Sparkles size={10} /> Select {category} Prompt
      </p>
      <div className="space-y-1">
        {loading ? (
          <div className="py-4 flex justify-center"><Clock className="animate-spin text-slate-300" size={16} /></div>
        ) : (
          prompts.map(p => (
            <button
              key={p.id}
              onClick={() => onSelect(p.id, p.name)}
              className={cn(
                "flex w-full items-center gap-2 rounded-lg border border-slate-200 bg-white p-2 text-left text-[11px] transition-all hover:border-indigo-500 hover:bg-indigo-50 dark:border-slate-700 dark:bg-slate-800 dark:hover:bg-indigo-900/20",
                p.is_active && "border-amber-200 bg-amber-50/30 dark:border-amber-900/50 dark:bg-amber-900/10"
              )}
            >
              <div className="flex-1 min-w-0">
                <p className="truncate font-medium text-slate-900 dark:text-white">{p.name}</p>
                <p className="text-[9px] text-slate-500 truncate">{p.description}</p>
              </div>
              {p.is_active && <span className="text-[8px] font-bold bg-amber-100 text-amber-700 px-1 rounded dark:bg-amber-900/40 dark:text-amber-400">ACTIVE</span>}
            </button>
          ))
        )}
      </div>
    </div>
  )
}
