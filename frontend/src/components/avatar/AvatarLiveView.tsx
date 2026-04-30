// v2 (Low Latency) avatar UI. Renders a fixed avatar that streams real-time
// audio + video from the Gemini Live API, via our backend WebSocket proxy.
//
// Architecture: see frontend/src/components/avatar/live/* for the building
// blocks. This component only wires them together and renders a small UI.

import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  ArrowLeft,
  Loader2,
  Mic,
  MicOff,
  Pencil,
  Power,
  Send,
} from 'lucide-react'
import { api, buildAvatarLiveUrl } from '@/lib/api'
import { useAuthStore } from '@/store/useAuthStore'
import { AvatarEditModal } from '@/components/avatar/AvatarEditModal'
import { GeminiLiveSession } from '@/components/avatar/live/GeminiLiveSession'
import { AudioCapture } from '@/components/avatar/live/AudioCapture'
import { VideoCanvasSink } from '@/components/avatar/live/VideoCanvasSink'
import { AudioPlayer } from '@/components/avatar/live/AudioPlayer'
import type { Avatar } from '@/types/avatar'

type Status = 'idle' | 'connecting' | 'connected' | 'error' | 'closed'

interface Props {
  avatar: Avatar
}

export const AvatarLiveView = ({ avatar }: Props) => {
  const navigate = useNavigate()
  const { isMaster } = useAuthStore()

  const canvasRef = useRef<HTMLCanvasElement>(null)
  const sessionRef = useRef<GeminiLiveSession | null>(null)
  const captureRef = useRef<AudioCapture | null>(null)
  const sinkRef = useRef<VideoCanvasSink | null>(null)
  const audioPlayerRef = useRef<AudioPlayer | null>(null)

  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState<string | null>(null)
  const [muted, setMuted] = useState(false)
  const [textInput, setTextInput] = useState('')
  const [editing, setEditing] = useState(false)
  const [editedAvatar, setEditedAvatar] = useState<Avatar>(avatar)
  // Set true when the user explicitly disconnects; suppresses the auto-start
  // useEffect from spinning a fresh session right back up.
  const [disconnected, setDisconnected] = useState(false)

  // Sync prop -> local state when caller updates the avatar
  useEffect(() => setEditedAvatar(avatar), [avatar])

  useEffect(() => {
    if (!isMaster) return
    if (disconnected) return
    let cancelled = false

    async function start() {
      setStatus('connecting')
      setError(null)
      try {
        // /live-config still gates the session (auth, voice, system prompt)
        // even though we no longer need its image URL — keep calling it.
        await api.avatars.liveConfig(avatar.id)
        if (cancelled) return

        if (!canvasRef.current) throw new Error('Canvas not ready')
        const sink = new VideoCanvasSink(canvasRef.current, (reason) => {
          setError(reason)
        })
        sinkRef.current = sink

        const player = new AudioPlayer()
        audioPlayerRef.current = player

        const session = new GeminiLiveSession()
        sessionRef.current = session

        session.addEventListener('connected', () => setStatus('connected'))
        session.addEventListener('disconnected', () => setStatus('closed'))
        session.addEventListener('error', (e: any) => {
          setStatus('error')
          setError(e?.detail?.error?.message ?? 'Live session error')
        })
        session.addEventListener('video-chunk', (e: any) => {
          sink.pushChunk(e.detail.mimeType, e.detail.data)
        })
        let audioChunkCount = 0
        session.addEventListener('audio-chunk', (e: any) => {
          audioChunkCount += 1
          if (audioChunkCount <= 3 || audioChunkCount % 50 === 0) {
            // eslint-disable-next-line no-console
            console.log(
              `[audio-chunk] #${audioChunkCount}`,
              { mime: e.detail.mimeType, size: e.detail.data.byteLength },
            )
          }
          player.pushChunk(e.detail.mimeType, e.detail.data)
        })

        await session.connect(buildAvatarLiveUrl(avatar.id))
        if (cancelled) return

        const capture = new AudioCapture()
        captureRef.current = capture
        await capture.start((pcm) => session.sendAudioChunk(pcm))
      } catch (err) {
        if (cancelled) return
        setStatus('error')
        setError(err instanceof Error ? err.message : 'Failed to start session')
      }
    }

    start()

    return () => {
      cancelled = true
      captureRef.current?.stop()
      sessionRef.current?.close()
      sinkRef.current?.destroy()
      audioPlayerRef.current?.destroy()
      captureRef.current = null
      sessionRef.current = null
      sinkRef.current = null
      audioPlayerRef.current = null
    }
  }, [avatar.id, isMaster, disconnected])

  const handleDisconnect = () => {
    captureRef.current?.stop()
    sessionRef.current?.close()
    sinkRef.current?.destroy()
    audioPlayerRef.current?.destroy()
    captureRef.current = null
    sessionRef.current = null
    sinkRef.current = null
    audioPlayerRef.current = null
    setStatus('closed')
    setDisconnected(true)
  }

  const handleReconnect = () => {
    setError(null)
    setDisconnected(false)
  }

  const handleSendText = (e: React.FormEvent) => {
    e.preventDefault()
    const text = textInput.trim()
    if (!text || !sessionRef.current?.isConnected()) return
    // This click is a real user gesture, so it's the right moment to
    // unblock the audio AudioContext if browser autoplay policy parked it
    // in 'suspended' state. Audio in v2 lives inside the MP4 → resume the
    // canvas sink's playback context.
    void sinkRef.current?.resume()
    void audioPlayerRef.current?.resume()
    sessionRef.current.sendText(text)
    setTextInput('')
  }

  const toggleMute = () => {
    const next = !muted
    setMuted(next)
    captureRef.current?.setMuted(next)
    void sinkRef.current?.resume()
    void audioPlayerRef.current?.resume()
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="max-w-3xl mx-auto space-y-6"
    >
      <button
        onClick={() => navigate('/avatars')}
        className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft size={14} /> Back to Avatars
      </button>

      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-2xl font-heading text-foreground tracking-tight truncate">
            {editedAvatar.name}
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            v2 · Low Latency · {editedAvatar.voice ?? 'Kore'}
            {editedAvatar.persona_prompt
              ? ` · ${editedAvatar.persona_prompt.slice(0, 64)}${editedAvatar.persona_prompt.length > 64 ? '…' : ''}`
              : ''}
          </p>
        </div>
        {isMaster && (
          <button
            onClick={() => setEditing(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-border text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors shrink-0"
          >
            <Pencil size={12} /> Edit
          </button>
        )}
      </div>

      {editing && (
        <AvatarEditModal
          avatar={editedAvatar}
          onClose={() => setEditing(false)}
          onSaved={(patch) => setEditedAvatar({ ...editedAvatar, ...patch })}
        />
      )}

      <div className="relative aspect-[3/4] max-w-sm mx-auto rounded-2xl overflow-hidden bg-black border border-border shadow-2xl">
        <canvas
          ref={canvasRef}
          className="absolute inset-0 w-full h-full object-cover bg-black"
        />
        <div className="absolute top-3 left-3">
          <StatusPill status={status} />
        </div>
        <button
          type="button"
          onClick={disconnected ? handleReconnect : handleDisconnect}
          className={`absolute top-3 right-3 flex items-center justify-center w-8 h-8 rounded-full backdrop-blur-md border transition-colors ${
            disconnected
              ? 'bg-emerald-500/80 hover:bg-emerald-500 text-white border-white/20'
              : 'bg-black/60 hover:bg-red-500/80 text-white/90 hover:text-white border-white/15'
          }`}
          aria-label={disconnected ? 'Reconnect' : 'Disconnect'}
          title={disconnected ? 'Reconnect' : 'Disconnect'}
        >
          <Power size={14} />
        </button>
      </div>


      {error && (
        <div className="max-w-sm mx-auto p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-500 text-xs">
          {error}
        </div>
      )}

      <div className="max-w-sm mx-auto">
        <form
          onSubmit={handleSendText}
          className="flex items-center gap-2 p-2 rounded-2xl bg-card border border-border shadow-xl"
        >
          <button
            type="button"
            onClick={toggleMute}
            disabled={status !== 'connected'}
            className={`flex items-center justify-center w-10 h-10 rounded-xl transition-colors disabled:opacity-40 ${
              muted
                ? 'bg-red-500/20 text-red-500'
                : 'bg-accent/20 text-accent hover:bg-accent/30'
            }`}
            aria-label={muted ? 'Unmute mic' : 'Mute mic'}
          >
            {muted ? <MicOff size={16} /> : <Mic size={16} />}
          </button>
          <input
            type="text"
            value={textInput}
            onChange={(e) => setTextInput(e.target.value)}
            placeholder={
              status === 'connected'
                ? 'Type to send · or just speak'
                : 'Connecting…'
            }
            disabled={status !== 'connected'}
            className="flex-1 bg-transparent border-none focus:outline-none text-sm placeholder:text-muted-foreground disabled:cursor-wait"
          />
          <button
            type="submit"
            disabled={status !== 'connected' || !textInput.trim()}
            className="flex items-center justify-center w-10 h-10 rounded-xl bg-accent text-accent-foreground disabled:opacity-40 hover:opacity-90 transition-opacity"
            aria-label="Send"
          >
            <Send size={16} />
          </button>
        </form>
      </div>
    </motion.div>
  )
}

const StatusPill = ({ status }: { status: Status }) => {
  const map: Record<Status, { label: string; cls: string; spin: boolean }> = {
    idle: { label: 'Idle', cls: 'bg-black/60 text-white', spin: false },
    connecting: {
      label: 'Connecting…',
      cls: 'bg-black/60 text-white',
      spin: true,
    },
    connected: {
      label: 'Live',
      cls: 'bg-emerald-500/80 text-white',
      spin: false,
    },
    error: { label: 'Error', cls: 'bg-red-500/80 text-white', spin: false },
    closed: {
      label: 'Disconnected',
      cls: 'bg-zinc-500/70 text-white',
      spin: false,
    },
  }
  const { label, cls, spin } = map[status]
  return (
    <div
      className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-medium backdrop-blur-md border border-white/10 ${cls}`}
    >
      {spin && <Loader2 size={12} className="animate-spin" />}
      {label}
    </div>
  )
}
