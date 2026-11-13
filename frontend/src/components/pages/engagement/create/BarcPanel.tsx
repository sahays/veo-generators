import { useId } from 'react'
import { ErrorDisplay } from '@/components/shared/ErrorDisplay'
import { ProgressBar } from '@/components/shared/media/ProgressBar'
import type { BarcSelection } from '@/types/engagement/createForm'
import { BarcPreview } from './BarcPreview'
import { useBarcUpload, type BarcUploadState } from './useBarcUpload'

const FILE_INPUT_CLASS =
  'block w-full cursor-pointer rounded-[5px] border border-border bg-card text-xs text-muted-foreground file:mr-3 file:cursor-pointer file:border-0 file:bg-muted file:px-3 file:py-2 file:text-xs file:font-medium file:text-foreground hover:border-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'

function UploadProgress({ state }: { state: BarcUploadState }): JSX.Element | null {
  if (state.phase !== 'uploading' && state.phase !== 'previewing') return null
  const text = state.phase === 'uploading' ? `Uploading ${state.filename}… ${Math.round(state.progress)}%` : `Reading ${state.filename}…`
  return (
    <div role="status" aria-live="polite" data-testid="barc-progress" className="space-y-1.5">
      <ProgressBar progress={state.progress} showSpinner={false} />
      <p className="text-[11px] text-muted-foreground">{text}</p>
    </div>
  )
}

export interface BarcPanelProps {
  barc: BarcSelection
  onChange: (barc: BarcSelection) => void
}

/**
 * Upload of a BARC CSV: the file goes through the shared direct-upload flow,
 * then the server previews it and the detected column mapping can be adjusted.
 */
export function BarcPanel({ barc, onChange }: BarcPanelProps): JSX.Element {
  const inputId = useId()
  const helpId = `${inputId}-help`
  const upload = useBarcUpload(onChange)
  const onFile = (event: React.ChangeEvent<HTMLInputElement>): void => {
    const file = event.target.files?.[0]
    if (file) upload.start(file)
  }
  return (
    <div data-testid="barc-panel" className="space-y-3 rounded-lg border border-border bg-muted/20 p-3">
      <div className="space-y-1.5">
        <label htmlFor={inputId} className="block text-sm font-medium text-foreground">BARC file</label>
        <input type="file" id={inputId} accept=".csv,text/csv" aria-describedby={helpId} data-testid="barc-file" className={FILE_INPUT_CLASS} onChange={onFile} />
        <p id={helpId} className="text-[11px] text-muted-foreground">A .csv export with a time column and one or more numeric metrics, up to 10 MB. It is stored with your other files.</p>
      </div>
      <UploadProgress state={upload.state} />
      {upload.state.error && (
        <div role="alert">
          <ErrorDisplay error={upload.state.error} />
        </div>
      )}
      {barc.preview && <BarcPreview barc={barc} onChange={onChange} />}
    </div>
  )
}
