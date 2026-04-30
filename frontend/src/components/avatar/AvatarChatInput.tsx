import { useState, useEffect, useRef } from 'react'
import { Send, Mic, Square } from 'lucide-react'
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

export const AvatarChatInput = ({
  onSubmitText,
  onSubmitAudio,
  disabled,
  disabledReason,
}: AvatarChatInputProps) => {
  const [text, setText] = useState('')
  const [recording, setRecording] = useState(false)
  const [secondsLeft, setSecondsLeft] = useState(MAX_RECORD_MS / 1000)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const stopTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const tickTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const chunksRef = useRef<BlobPart[]>([])

  const supported = typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia

  useEffect(() => () => stopRecording(false), []) // cleanup on unmount

  const stopRecording = (emit: boolean) => {
    if (stopTimerRef.current) clearTimeout(stopTimerRef.current)
    if (tickTimerRef.current) clearInterval(tickTimerRef.current)
    stopTimerRef.current = null
    tickTimerRef.current = null
    const recorder = recorderRef.current
    if (recorder && recorder.state !== 'inactive') {
      // Override onstop to emit-or-discard depending on context.
      recorder.onstop = () => {
        streamRef.current?.getTracks().forEach((t) => t.stop())
        streamRef.current = null
        recorderRef.current = null
        const blob = new Blob(chunksRef.current, {
          type: recorder.mimeType || 'audio/webm',
        })
        chunksRef.current = []
        if (emit && blob.size > 0) onSubmitAudio(blob)
      }
      try {
        recorder.stop()
      } catch {
        /* ignore */
      }
    }
    setRecording(false)
  }

  const startRecording = async () => {
    if (!supported || disabled) return
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      const mimeType = pickRecorderMimeType()
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      recorderRef.current = recorder
      chunksRef.current = []
      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data)
      }
      recorder.start()
      setRecording(true)
      setSecondsLeft(MAX_RECORD_MS / 1000)
      stopTimerRef.current = setTimeout(() => stopRecording(true), MAX_RECORD_MS)
      tickTimerRef.current = setInterval(() => {
        setSecondsLeft((s) => Math.max(0, s - 1))
      }, 1000)
    } catch (err) {
      console.error('Mic capture failed:', err)
      streamRef.current?.getTracks().forEach((t) => t.stop())
      streamRef.current = null
      setRecording(false)
    }
  }

  const handleMicClick = () => {
    if (recording) stopRecording(true)
    else startRecording()
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = text.trim()
    if (!trimmed || disabled) return
    onSubmitText(trimmed)
    setText('')
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="glass bg-card/95 rounded-2xl shadow-2xl border border-border p-2 flex items-center gap-2"
    >
      {supported && (
        <button
          type="button"
          onClick={handleMicClick}
          disabled={disabled}
          title={recording ? `Stop (${secondsLeft}s left)` : 'Tap to record up to 10s'}
          className={cn(
            'p-2.5 rounded-xl transition-all flex items-center gap-1.5',
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
        </button>
      )}
      <input
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={
          recording
            ? 'Listening…'
            : disabled
              ? disabledReason || 'Disabled'
              : 'Ask the avatar…'
        }
        disabled={disabled || recording}
        className="flex-1 bg-transparent border-none outline-none text-sm placeholder:text-muted-foreground disabled:cursor-not-allowed"
      />
      <button
        type="submit"
        disabled={disabled || recording || !text.trim()}
        className="p-2.5 rounded-xl bg-accent text-slate-900 hover:bg-accent-dark transition-all disabled:opacity-40 disabled:cursor-not-allowed"
        title="Send"
      >
        <Send size={18} />
      </button>
    </form>
  )
}
