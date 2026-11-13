import { useEffect, useRef, useState } from 'react'
import { api } from '@/hooks/useApiClient'
import { EMPTY_BARC, barcFromPreview, type BarcSelection } from '@/types/engagement/createForm'

/** The server rejects signal files over 10 MB. */
const MAX_CSV_BYTES = 10 * 1024 * 1024

export type BarcUploadPhase = 'idle' | 'uploading' | 'previewing' | 'ready' | 'error'

export interface BarcUploadState {
  phase: BarcUploadPhase
  /** Upload progress, 0..100. */
  progress: number
  filename: string
  error: string | null
}

export interface BarcUpload {
  state: BarcUploadState
  /** Upload a CSV, then ask the server to preview it. A new call replaces a running one. */
  start: (file: File) => void
}

const IDLE: BarcUploadState = { phase: 'idle', progress: 0, filename: '', error: null }
const noop = (): void => undefined

function phase(file: File, name: BarcUploadPhase, progress: number, error: string | null = null): BarcUploadState {
  return { phase: name, progress, filename: file.name, error }
}

/** Why a chosen file cannot be uploaded as a signal, or null when it can. */
function fileProblem(file: File): string | null {
  if (!/\.csv$/i.test(file.name)) return 'Choose a .csv file. Export the BARC sheet as CSV first.'
  if (file.size === 0) return 'The file is empty.'
  if (file.size > MAX_CSV_BYTES) return 'The file is larger than 10 MB. Export a shorter time range or a coarser interval.'
  return null
}

interface UploadRun {
  result: Promise<BarcSelection>
  abort: () => void
}

/** Upload through the shared direct-upload flow, then fetch the server's preview of the file. */
function runUpload(file: File, report: (state: BarcUploadState) => void): UploadRun {
  const upload = api.assets.directUpload(file, (progress) => report(phase(file, 'uploading', progress)))
  const result = upload.promise.then(async (uploaded) => {
    report(phase(file, 'previewing', 100))
    return barcFromPreview(uploaded.id, await api.engagement.signalPreview(uploaded.id))
  })
  return { result, abort: upload.abort }
}

/**
 * Upload state of the BARC file. `onChange` receives the selection: empty as
 * soon as a new file is chosen, then the uploaded file with the mapping the
 * server detected.
 */
export function useBarcUpload(onChange: (selection: BarcSelection) => void): BarcUpload {
  const [state, setState] = useState<BarcUploadState>(IDLE)
  const active = useRef({ token: 0, abort: noop })
  useEffect(() => () => active.current.abort(), [])

  const start = (file: File): void => {
    active.current.abort()
    const token = active.current.token + 1
    // A run that was replaced by a newer file must not touch the state any more.
    const report = (next: BarcUploadState): void => {
      if (active.current.token === token) setState(next)
    }
    const problem = fileProblem(file)
    const run = problem ? null : runUpload(file, report)
    active.current = { token, abort: run?.abort ?? noop }
    onChange(EMPTY_BARC)
    report(problem ? phase(file, 'error', 0, problem) : phase(file, 'uploading', 0))
    run?.result
      .then((selection) => {
        if (active.current.token !== token) return
        onChange(selection)
        report(phase(file, 'ready', 100))
      })
      .catch((cause: unknown) => report(phase(file, 'error', 0, cause instanceof Error ? cause.message : 'The upload failed')))
  }

  return { state, start }
}
