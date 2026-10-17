import { useState, useEffect, useRef } from 'react'
import { Send, Mic, Square } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

interface AvatarChatInputProps {
  onSubmitText: (text: string) => void
  onSubmitAudio: (audio: Blob) => void
  disabled?: boolean
  disabledReason?: string
}

const MAX_RECORD_MS = 10_000

function pickRecorderMimeType(): string | undefined {
  // Try opus-flavored containers first; fall back to whatever the browser ships.
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/ogg;codecs=opus',
    'audio/mp4;codecs=mp4a.40.2',
    'audio/webm',
    'audio/ogg',
    'audio/mp4',
  ]
  for (const t of candidates) {
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported?.(t)) {
      return t
    }
  }
  return undefined
}

interface RecorderRefs {
  recorderRef: React.MutableRefObject<MediaRecorder | null>
  streamRef: React.MutableRefObject<MediaStream | null>
  stopTimerRef: React.MutableRefObject<ReturnType<typeof setTimeout> | null>
  tickTimerRef: React.MutableRefObject<ReturnType<typeof setInterval> | null>
  chunksRef: React.MutableRefObject<BlobPart[]>
}

function stopMediaRecording(
  emit: boolean,
  refs: RecorderRefs,
  onSubmitAudio: (audio: Blob) => void,
  setRecording: (v: boolean) => void,
): void {
  if (refs.stopTimerRef.current) clearTimeout(refs.stopTimerRef.current)
  if (refs.tickTimerRef.current) clearInterval(refs.tickTimerRef.current)
  refs.stopTimerRef.current = null
  refs.tickTimerRef.current = null
  const recorder = refs.recorderRef.current
  if (recorder && recorder.state !== 'inactive') {
    recorder.onstop = () => {
      refs.streamRef.current?.getTracks().forEach((t) => t.stop())
      refs.streamRef.current = null
      refs.recorderRef.current = null
      const blob = new Blob(refs.chunksRef.current, { type: recorder.mimeType || 'audio/webm' })
      refs.chunksRef.current = []
      if (emit && blob.size > 0) onSubmitAudio(blob)
    }
    try { recorder.stop() } catch { /* ignore */ }
  }
  setRecording(false)
}

async function startMediaRecording(
  refs: RecorderRefs,
  stopFn: (emit: boolean) => void,
  setRecording: (v: boolean) => void,
  setSecondsLeft: React.Dispatch<React.SetStateAction<number>>,
): Promise<void> {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    refs.streamRef.current = stream
    const mimeType = pickRecorderMimeType()
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
    refs.recorderRef.current = recorder
    refs.chunksRef.current = []
    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) refs.chunksRef.current.push(e.data)
    }
    recorder.start()
    setRecording(true)
    setSecondsLeft(MAX_RECORD_MS / 1000)
    refs.stopTimerRef.current = setTimeout(() => stopFn(true), MAX_RECORD_MS)
    refs.tickTimerRef.current = setInterval(() => setSecondsLeft((s) => Math.max(0, s - 1)), 1000)
  } catch {
    refs.streamRef.current?.getTracks().forEach((t) => t.stop())
    refs.streamRef.current = null
    setRecording(false)
  }
}

function MicRecordButton({
  recording,
  secondsLeft,
  disabled,
  onClick,
}: {
  recording: boolean
  secondsLeft: number
  disabled?: boolean
  onClick: () => void
}) {
  return (
    <Button
      type="button"
      variant="unstyled"
      onClick={onClick}
      disabled={disabled}
      title={recording ? `Stop (${secondsLeft}s left)` : 'Tap to record up to 10s'}
      className={cn(
        'p-2.5 rounded-[6px] transition-all flex items-center gap-1.5',
        recording
          ? 'bg-red-500/15 text-red-500'
          : 'hover:bg-muted text-muted-foreground hover:text-foreground',
        disabled && 'opacity-40 cursor-not-allowed',
      )}
    >
      {recording ? (
        <>
          <Square size={14} fill="currentColor" />
          <span className="text-[10px] font-mono font-bold tabular-nums">{secondsLeft}s</span>
        </>
      ) : (
        <Mic size={18} />
      )}
    </Button>
  )
}

function useAudioRecorder(onSubmitAudio: (audio: Blob) => void, disabled?: boolean) {
  const [recording, setRecording] = useState(false)
  const [secondsLeft, setSecondsLeft] = useState(MAX_RECORD_MS / 1000)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const stopTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const tickTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const chunksRef = useRef<BlobPart[]>([])
  const supported = typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia
  const refs: RecorderRefs = { recorderRef, streamRef, stopTimerRef, tickTimerRef, chunksRef }

  const stopRecording = (emit: boolean) =>
    stopMediaRecording(emit, refs, onSubmitAudio, setRecording)

  useEffect(() => () => stopRecording(false), [])

  const toggleMic = () => {
    if (recording) stopRecording(true)
    else if (supported && !disabled) {
      void startMediaRecording(refs, stopRecording, setRecording, setSecondsLeft)
    }
  }
  return { recording, secondsLeft, supported, toggleMic }
}

export const AvatarChatInput = ({ onSubmitText, onSubmitAudio, disabled, disabledReason }: AvatarChatInputProps) => {
  const [text, setText] = useState('')
  const { recording, secondsLeft, supported, toggleMic } = useAudioRecorder(onSubmitAudio, disabled)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = text.trim()
    if (!trimmed || disabled) return
    onSubmitText(trimmed)
    setText('')
  }

  const placeholder = recording ? 'Listening…' : disabled ? disabledReason || 'Disabled' : 'Ask the avatar…'

  return (
    <form onSubmit={handleSubmit} className="glass bg-card/95 rounded-2xl shadow-2xl border border-border p-2 flex items-center gap-2">
      {supported && <MicRecordButton recording={recording} secondsLeft={secondsLeft} disabled={disabled} onClick={toggleMic} />}
      <Input
        type="text" value={text} onChange={(e) => setText(e.target.value)} placeholder={placeholder} disabled={disabled || recording}
        className="flex-1 bg-transparent border-none shadow-none focus-visible:ring-0 text-sm placeholder:text-muted-foreground disabled:cursor-not-allowed"
      />
      <Button type="submit" size="icon" disabled={disabled || recording || !text.trim()} className="h-10 w-10" title="Send">
        <Send size={18} />
      </Button>
    </form>
  )
}
