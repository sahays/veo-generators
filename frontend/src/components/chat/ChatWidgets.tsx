import React, { useState } from 'react'
import {
  CheckCircle2,
  Film,
  Loader2,
  AlertCircle,
  X,
  RefreshCw,
  Clapperboard,
  Smartphone,
  Image,
  Search,
  LayoutGrid,
  Languages,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import {
  ROUTE_MAP,
  executeConfirmationJob,
  type ConfirmationData,
  type ConfirmationJobParams,
  type ConfirmationJobResult,
  type ConfirmationJobType,
} from './widgets/useChatWidgetActions'
import {
  PromoFields,
  ReframeFields,
  ProductionFields,
  KeyMomentsFields,
  AdaptsFields,
  DubbingFields,
} from './widgets/ChatConfirmationFields'
import {
  VideoResultCard,
  VideoSourcePicker,
  ImageSourcePicker,
  PromptPicker,
} from './widgets/ChatSourcePickers'

export {
  VideoResultCard,
  VideoSourcePicker,
  ImageSourcePicker,
  PromptPicker,
  type ConfirmationData,
  type ConfirmationJobType,
  type ConfirmationJobResult,
}

type ConfirmationStatus = 'pending' | 'confirming' | 'confirmed' | 'cancelled' | 'failed'

const JOB_ICONS: Record<ConfirmationJobType, React.ReactNode> = {
  promo: <Clapperboard size={16} />,
  reframe: <Smartphone size={16} />,
  production: <Film size={16} />,
  key_moments: <Search size={16} />,
  thumbnails: <Image size={16} />,
  adapts: <LayoutGrid size={16} />,
  dubbing: <Languages size={16} />,
}

const ConfirmationHeader: React.FC<{
  jobType: ConfirmationJobType
  title: string
  status: ConfirmationStatus
}> = ({ jobType, title, status }) => (
  <div className="flex items-center gap-2 border-b border-slate-100 bg-slate-50 px-3 py-2 dark:border-slate-700 dark:bg-slate-800/80">
    <div className="flex h-6 w-6 items-center justify-center rounded-md bg-orange-100 text-orange-600 dark:bg-orange-900/40 dark:text-orange-400">
      {JOB_ICONS[jobType]}
    </div>
    <span className="text-[11px] font-semibold text-slate-900 dark:text-white flex-1 truncate">{title}</span>
    {status === 'confirmed' && <CheckCircle2 size={14} className="text-green-500" />}
    {status === 'cancelled' && <X size={14} className="text-slate-400" />}
  </div>
)

const ConfirmationFieldSwitch: React.FC<{
  jobType: ConfirmationJobType
  params: ConfirmationJobParams
  resolved: Record<string, string>
  onChange: (p: ConfirmationJobParams) => void
  disabled: boolean
}> = ({ jobType, params, resolved, onChange, disabled }) => {
  if (jobType === 'promo') return <PromoFields params={params} resolved={resolved} onChange={onChange} disabled={disabled} />
  if (jobType === 'reframe') return <ReframeFields params={params} resolved={resolved} onChange={onChange} disabled={disabled} />
  if (jobType === 'production') return <ProductionFields params={params} resolved={resolved} onChange={onChange} disabled={disabled} />
  if (jobType === 'key_moments' || jobType === 'thumbnails') return <KeyMomentsFields resolved={resolved} />
  if (jobType === 'adapts') return <AdaptsFields params={params} resolved={resolved} onChange={onChange} disabled={disabled} />
  if (jobType === 'dubbing') return <DubbingFields params={params} resolved={resolved} onChange={onChange} disabled={disabled} />
  return null
}

const ConfirmationActiveBody: React.FC<{
  jobType: ConfirmationJobType
  localParams: ConfirmationJobParams
  localResolved: Record<string, string>
  setLocalParams: (p: ConfirmationJobParams) => void
  setLocalResolved: (r: Record<string, string>) => void
  needsVideoSource: boolean
  needsImageSource: boolean
  disabled: boolean
  error: string | null
}> = ({
  jobType,
  localParams,
  localResolved,
  setLocalParams,
  setLocalResolved,
  needsVideoSource,
  needsImageSource,
  disabled,
  error,
}) => (
  <>
    {needsVideoSource && (
      <VideoSourcePicker
        onSelect={(uri, name) => {
          setLocalParams({ ...localParams, gcs_uri: uri, source_filename: name })
          setLocalResolved({ ...localResolved, source_name: name })
        }}
      />
    )}
    {needsImageSource && (
      <ImageSourcePicker
        onSelect={(uri, name) => {
          setLocalParams({ ...localParams, gcs_uri: uri, source_filename: name })
          setLocalResolved({ ...localResolved, source_name: name })
        }}
      />
    )}
    <ConfirmationFieldSwitch
      jobType={jobType}
      params={localParams}
      resolved={localResolved}
      onChange={setLocalParams}
      disabled={disabled}
    />
    {error && (
      <div className="mt-2 flex items-start gap-1.5 rounded-lg bg-red-50 px-2 py-1.5 dark:bg-red-900/20">
        <AlertCircle size={12} className="mt-0.5 text-red-500 flex-shrink-0" />
        <span className="text-[10px] text-red-600 dark:text-red-400">{error}</span>
      </div>
    )}
  </>
)

const ConfirmationFooter: React.FC<{
  status: ConfirmationStatus
  disableConfirm: boolean
  onConfirm: () => void
  onRetry: () => void
  onCancel: () => void
}> = ({ status, disableConfirm, onConfirm, onRetry, onCancel }) => (
  <div className="flex items-center gap-2 border-t border-slate-100 px-3 py-2 dark:border-slate-700">
    {status === 'failed' ? (
      <Button variant="ghost" size="xs" icon={RefreshCw} onClick={onRetry}>
        Retry
      </Button>
    ) : (
      <Button variant="ghost" size="xs" onClick={onCancel} disabled={status === 'confirming'}>
        Cancel
      </Button>
    )}
    <Button size="xs" onClick={onConfirm} disabled={disableConfirm} className="ml-auto">
      {status === 'confirming' ? (
        <>
          <Loader2 size={10} className="animate-spin" /> Confirming...
        </>
      ) : (
        <>
          <CheckCircle2 size={10} /> Confirm
        </>
      )}
    </Button>
  </div>
)

export const ConfirmationCard: React.FC<{
  confirmation: ConfirmationData
  onConfirmed: (jobType: ConfirmationJobType, result: ConfirmationJobResult) => void
  onFailed: (error: string) => void
}> = ({ confirmation, onConfirmed, onFailed }) => {
  const [localParams, setLocalParams] = useState<ConfirmationJobParams>(confirmation.params)
  const [localResolved, setLocalResolved] = useState(confirmation.resolved)
  const [status, setStatus] = useState<ConfirmationStatus>('pending')
  const [error, setError] = useState<string | null>(null)
  const [resultId, setResultId] = useState<string | null>(null)

  const { job_type, title } = confirmation
  const needsVideoSource =
    ['promo', 'reframe', 'key_moments', 'thumbnails', 'dubbing'].includes(job_type) &&
    !localParams.gcs_uri
  const needsImageSource = job_type === 'adapts' && !localParams.gcs_uri

  const handleConfirm = async () => {
    setStatus('confirming')
    setError(null)
    try {
      const result = await executeConfirmationJob(job_type, localParams)
      setStatus('confirmed')
      setResultId(result.id || null)
      onConfirmed(job_type, result)
    } catch (err: unknown) {
      setStatus('failed')
      const msg = err instanceof Error ? err.message : 'Something went wrong'
      setError(msg)
      onFailed(msg)
    }
  }

  return (
    <div className="mt-3 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-800">
      <ConfirmationHeader jobType={job_type} title={title} status={status} />
      <div className="px-3 py-2">
        {status === 'cancelled' ? (
          <p className="text-[11px] text-slate-400 italic">Cancelled</p>
        ) : status === 'confirmed' && resultId ? (
          <div className="flex items-center gap-2">
            <CheckCircle2 size={14} className="text-green-500 flex-shrink-0" />
            <span className="text-[11px] text-slate-600 dark:text-slate-300">Job created</span>
            <Link
              to={ROUTE_MAP[job_type](resultId)}
              className="ml-auto text-[10px] font-bold text-orange-600 hover:text-orange-500 dark:text-orange-400"
            >
              View
            </Link>
          </div>
        ) : (
          <ConfirmationActiveBody
            jobType={job_type}
            localParams={localParams}
            localResolved={localResolved}
            setLocalParams={setLocalParams}
            setLocalResolved={setLocalResolved}
            needsVideoSource={needsVideoSource}
            needsImageSource={needsImageSource}
            disabled={status !== 'pending'}
            error={error}
          />
        )}
      </div>
      {(status === 'pending' || status === 'confirming' || status === 'failed') && (
        <ConfirmationFooter
          status={status}
          disableConfirm={status === 'confirming' || needsVideoSource || needsImageSource}
          onConfirm={handleConfirm}
          onRetry={() => {
            setStatus('pending')
            setError(null)
          }}
          onCancel={() => setStatus('cancelled')}
        />
      )}
    </div>
  )
}
