// v2 (Low Latency) avatar UI. Wires the live session hook to the canvas + a
// small text/mute control bar. All session lifecycle lives in
// `useAvatarLiveSession` — this component is purely UI.

import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowLeft, Loader2, Mic, MicOff, Pencil, Power, Send } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useAuthStore } from '@/store/useAuthStore'
import { AvatarEditModal } from '@/components/avatar/AvatarEditModal'
import {
  AvatarLiveStatus,
  useAvatarLiveSession,
} from '@/hooks/useAvatarLiveSession'
import type { Avatar } from '@/types/avatar'

interface Props {
  avatar: Avatar
}

function AvatarHeader({
  avatar,
  canWrite,
  onBack,
  onEdit,
}: {
  avatar: Avatar
  canWrite: boolean
  onBack: () => void
  onEdit: () => void
}) {
  const personaSnippet = avatar.persona_prompt
    ? ` · ${avatar.persona_prompt.slice(0, 64)}${avatar.persona_prompt.length > 64 ? '…' : ''}`
    : ''
  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        icon={ArrowLeft}
        onClick={onBack}
        className="text-muted-foreground hover:text-foreground -ml-2"
      >
        Back to Avatars
      </Button>
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-2xl font-heading text-foreground tracking-tight truncate">{avatar.name}</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            v2 · Low Latency · {avatar.voice ?? 'Kore'}
            {personaSnippet}
          </p>
        </div>
        {canWrite && (
          <Button variant="secondary" size="sm" icon={Pencil} onClick={onEdit} className="shrink-0">
            Edit
          </Button>
        )}
      </div>
    </>
  )
}

function AvatarStageCanvas({
  canvasRef,
  status,
  disconnected,
  onTogglePower,
}: {
  canvasRef: React.RefObject<HTMLCanvasElement>
  status: AvatarLiveStatus
  disconnected: boolean
  onTogglePower: () => void
}) {
  return (
    <div className="relative aspect-[3/4] max-w-sm mx-auto rounded-2xl overflow-hidden bg-black border border-border shadow-2xl">
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full object-cover bg-black" />
      <div className="absolute top-3 left-3">
        <StatusPill status={status} />
      </div>
      <Button
        type="button"
        variant="unstyled"
        onClick={onTogglePower}
        className={`absolute top-3 right-3 flex items-center justify-center w-8 h-8 rounded-full backdrop-blur-md border transition-colors ${
          disconnected
            ? 'bg-emerald-500/80 hover:bg-emerald-500 text-white border-white/20'
            : 'bg-black/60 hover:bg-red-500/80 text-white/90 hover:text-white border-white/15'
        }`}
        aria-label={disconnected ? 'Reconnect' : 'Disconnect'}
        title={disconnected ? 'Reconnect' : 'Disconnect'}
      >
        <Power size={14} />
      </Button>
    </div>
  )
}

function AvatarLiveControlBar({
  status,
  muted,
  textInput,
  setTextInput,
  onToggleMute,
  onSendText,
}: {
  status: AvatarLiveStatus
  muted: boolean
  textInput: string
  setTextInput: (v: string) => void
  onToggleMute: () => void
  onSendText: (e: React.FormEvent) => void
}) {
  const isConnected = status === 'connected'
  return (
    <div className="max-w-sm mx-auto">
      <form
        onSubmit={onSendText}
        className="flex items-center gap-2 p-2 rounded-2xl bg-card border border-border shadow-xl"
      >
        <Button
          type="button"
          variant="unstyled"
          onClick={onToggleMute}
          disabled={!isConnected}
          className={`flex items-center justify-center w-10 h-10 rounded-[6px] transition-colors disabled:opacity-40 ${
            muted ? 'bg-red-500/20 text-red-500' : 'bg-accent/20 text-accent hover:bg-accent/30'
          }`}
          aria-label={muted ? 'Unmute mic' : 'Mute mic'}
        >
          {muted ? <MicOff size={16} /> : <Mic size={16} />}
        </Button>
        <Input
          type="text"
          value={textInput}
          onChange={(e) => setTextInput(e.target.value)}
          placeholder={isConnected ? 'Type to send · or just speak' : 'Connecting…'}
          disabled={!isConnected}
          className="flex-1 bg-transparent border-none shadow-none focus-visible:ring-0 text-sm placeholder:text-muted-foreground disabled:cursor-wait"
        />
        <Button type="submit" size="icon" disabled={!isConnected || !textInput.trim()} className="w-10 h-10" aria-label="Send">
          <Send size={16} />
        </Button>
      </form>
    </div>
  )
}

function useLiveViewControls(
  live: ReturnType<typeof useAvatarLiveSession>,
  muted: boolean,
  setMuted: (v: boolean) => void,
  textInput: string,
  setTextInput: (v: string) => void,
  disconnected: boolean,
  setDisconnected: (v: boolean) => void,
) {
  const onTogglePower = () => {
    if (disconnected) {
      live.setError(null)
      setDisconnected(false)
    } else {
      live.teardown()
      live.setStatus('closed')
      setDisconnected(true)
    }
  }
  const onSendText = (e: React.FormEvent) => {
    e.preventDefault()
    const text = textInput.trim()
    if (!text || !live.sessionRef.current?.isConnected()) return
    void live.sinkRef.current?.resume()
    void live.audioPlayerRef.current?.resume()
    live.sessionRef.current.sendText(text)
    setTextInput('')
  }
  const onToggleMute = () => {
    const next = !muted
    setMuted(next)
    live.captureRef.current?.setMuted(next)
    void live.sinkRef.current?.resume()
    void live.audioPlayerRef.current?.resume()
  }
  return { onTogglePower, onSendText, onToggleMute }
}

export const AvatarLiveView = ({ avatar }: Props) => {
  const navigate = useNavigate()
  const canWrite = useAuthStore((s) => s.isMaster || s.isPower)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [muted, setMuted] = useState(false)
  const [textInput, setTextInput] = useState('')
  const [editing, setEditing] = useState(false)
  const [editedAvatar, setEditedAvatar] = useState<Avatar>(avatar)
  const [disconnected, setDisconnected] = useState(false)
  useEffect(() => setEditedAvatar(avatar), [avatar])

  const live = useAvatarLiveSession({ avatarId: avatar.id, enabled: canWrite && !disconnected, canvasRef })
  const { onTogglePower, onSendText, onToggleMute } = useLiveViewControls(
    live, muted, setMuted, textInput, setTextInput, disconnected, setDisconnected,
  )

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="max-w-3xl mx-auto space-y-6">
      <AvatarHeader avatar={editedAvatar} canWrite={canWrite} onBack={() => navigate('/avatars')} onEdit={() => setEditing(true)} />
      {editing && <AvatarEditModal avatar={editedAvatar} onClose={() => setEditing(false)} onSaved={(p) => setEditedAvatar({ ...editedAvatar, ...p })} />}
      <AvatarStageCanvas canvasRef={canvasRef} status={live.status} disconnected={disconnected} onTogglePower={onTogglePower} />
      {live.error && <div className="max-w-sm mx-auto p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-500 text-xs">{live.error}</div>}
      <AvatarLiveControlBar status={live.status} muted={muted} textInput={textInput} setTextInput={setTextInput} onToggleMute={onToggleMute} onSendText={onSendText} />
    </motion.div>
  )
}

const STATUS_PILL: Record<
  AvatarLiveStatus,
  { label: string; cls: string; spin: boolean }
> = {
  idle: { label: 'Idle', cls: 'bg-black/60 text-white', spin: false },
  connecting: { label: 'Connecting…', cls: 'bg-black/60 text-white', spin: true },
  connected: { label: 'Live', cls: 'bg-emerald-500/80 text-white', spin: false },
  error: { label: 'Error', cls: 'bg-red-500/80 text-white', spin: false },
  closed: { label: 'Disconnected', cls: 'bg-zinc-500/70 text-white', spin: false },
}

const StatusPill = ({ status }: { status: AvatarLiveStatus }) => {
  const { label, cls, spin } = STATUS_PILL[status]
  return (
    <div
      className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-medium backdrop-blur-md border border-white/10 ${cls}`}
    >
      {spin && <Loader2 size={12} className="animate-spin" />}
      {label}
    </div>
  )
}
