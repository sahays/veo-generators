import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowLeft, Loader2, Pencil } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { api } from '@/hooks/useApiClient'
import { useAuthStore } from '@/store/useAuthStore'
import { AvatarPlayer } from '@/components/avatar/AvatarPlayer'
import { AvatarChatInput } from '@/components/avatar/chat/AvatarChatInput'
import { AvatarTurnBubble } from '@/components/avatar/chat/AvatarTurnBubble'
import { AvatarEditModal } from '@/components/avatar/AvatarEditModal'
import { AvatarLiveView } from '@/components/avatar/AvatarLiveView'
import type { Avatar, AvatarTurn } from '@/types/avatar'
import { STYLE_LABELS, VOICE_TURN_MARKER } from '@/types/avatar'

function formatAvatarHistory(turns: AvatarTurn[]) {
  return turns
    .slice(-10)
    .filter((t) => t.question !== VOICE_TURN_MARKER && t.answer_text)
    .flatMap((t) => [
      { role: 'user', content: t.question },
      { role: 'model', content: t.answer_text },
    ])
}

function useTurnPoller(
  activeTurnId: string | null,
  setTurns: React.Dispatch<React.SetStateAction<AvatarTurn[]>>,
  setIsGenerating: (v: boolean) => void,
  setActiveVideoUrl: (v: string | null) => void,
  setActiveTurnId: (v: string | null) => void,
  setError: (v: string | null) => void,
) {
  useEffect(() => {
    if (!activeTurnId) return
    const tick = async () => {
      try {
        const t: AvatarTurn = await api.avatars.getTurn(activeTurnId)
        setTurns((prev) => prev.map((x) => (x.id === t.id ? t : x)))
        if (t.status === 'completed') {
          setIsGenerating(false)
          setActiveVideoUrl(t.video_signed_url || null)
          setActiveTurnId(null)
        } else if (t.status === 'failed') {
          setIsGenerating(false)
          setError(t.error_message || 'Video generation failed')
          setActiveTurnId(null)
        }
      } catch {
        // ignore poll error
      }
    }
    const timer = setInterval(tick, 5000)
    tick()
    return () => clearInterval(timer)
  }, [activeTurnId, setTurns, setIsGenerating, setActiveVideoUrl, setActiveTurnId, setError])
}

function useAvatarTurnsState(id: string | undefined) {
  const [avatar, setAvatar] = useState<Avatar | null>(null)
  const [turns, setTurns] = useState<AvatarTurn[]>([])
  const [activeTurnId, setActiveTurnId] = useState<string | null>(null)
  const [activeVideoUrl, setActiveVideoUrl] = useState<string | null>(null)
  const [isGenerating, setIsGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!id) return
    Promise.all([api.avatars.get(id), api.avatars.listTurns(id)])
      .then(([a, ts]) => {
        setAvatar(a)
        setTurns(ts)
        const inflight = ts.find((t: AvatarTurn) => t.status === 'pending' || t.status === 'generating')
        if (inflight) {
          setIsGenerating(true)
          setActiveTurnId(inflight.id)
        }
      })
      .catch((err) => setError(err.message || 'Failed to load avatar'))
  }, [id])

  useTurnPoller(activeTurnId, setTurns, setIsGenerating, setActiveVideoUrl, setActiveTurnId, setError)

  return {
    avatar, setAvatar, turns, setTurns, activeVideoUrl, setActiveVideoUrl,
    isGenerating, setIsGenerating, setActiveTurnId, error, setError, submitting, setSubmitting,
  }
}

async function executeTurnSubmission(
  id: string,
  placeholderQuestion: string,
  callApi: (history: { role: string; content: string }[]) => Promise<{ turn_id: string; answer_text: string; status: string }>,
  state: ReturnType<typeof useAvatarTurnsState>,
) {
  const { turns, setTurns, setSubmitting, setError, setIsGenerating, setActiveTurnId, setActiveVideoUrl } = state
  setSubmitting(true)
  setError(null)
  const localId = `local-${Date.now()}`
  const placeholder: AvatarTurn = { id: localId, avatar_id: id, question: placeholderQuestion, answer_text: '', status: 'pending', progress_pct: 0, createdAt: new Date().toISOString() }
  setTurns((prev) => [placeholder, ...prev])
  try {
    const result = await callApi(formatAvatarHistory(turns))
    setTurns((prev) => prev.map((t) => (t.id === localId ? { ...placeholder, id: result.turn_id, answer_text: result.answer_text } : t)))
    setIsGenerating(true)
    setActiveTurnId(result.turn_id)
    setActiveVideoUrl(null)
  } catch (err) {
    setTurns((prev) => prev.filter((t) => t.id !== localId))
    setError(err instanceof Error ? err.message : 'Failed to ask')
  } finally {
    setSubmitting(false)
  }
}

function useSubmitTurnAction(id: string | undefined, state: ReturnType<typeof useAvatarTurnsState>) {
  const submitTurn = useCallback(
    async (placeholderQuestion: string, callApi: (history: { role: string; content: string }[]) => Promise<{ turn_id: string; answer_text: string; status: string }>) => {
      if (!id) return
      await executeTurnSubmission(id, placeholderQuestion, callApi, state)
    },
    [id, state],
  )
  const handleAsk = useCallback((question: string) => submitTurn(question, (history) => api.avatars.ask(id!, { question, history })), [id, submitTurn])
  const handleAskAudio = useCallback((audio: Blob) => submitTurn(VOICE_TURN_MARKER, (history) => api.avatars.askAudio(id!, audio, history)), [id, submitTurn])
  return { handleAsk, handleAskAudio }
}

const AvatarV1View = ({
  avatar,
  setAvatar,
  turns,
  activeVideoUrl,
  setActiveVideoUrl,
  isGenerating,
  error,
  submitting,
  canWrite,
  onBack,
  onAsk,
  onAskAudio,
}: {
  avatar: Avatar
  setAvatar: (a: Avatar) => void
  turns: AvatarTurn[]
  activeVideoUrl: string | null
  setActiveVideoUrl: (u: string | null) => void
  isGenerating: boolean
  error: string | null
  submitting: boolean
  canWrite: boolean
  onBack: () => void
  onAsk: (q: string) => void
  onAskAudio: (b: Blob) => void
}) => {
  const [editing, setEditing] = useState(false)
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="max-w-3xl mx-auto space-y-6 pb-32">
      <Button variant="ghost" size="sm" icon={ArrowLeft} onClick={onBack} className="text-muted-foreground hover:text-foreground -ml-2">
        Back to Avatars
      </Button>
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-2xl font-heading text-foreground tracking-tight truncate">{avatar.name}</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            {STYLE_LABELS[avatar.style]}
            {avatar.persona_prompt ? ` · ${avatar.persona_prompt.slice(0, 80)}${avatar.persona_prompt.length > 80 ? '…' : ''}` : ' · No persona set'}
          </p>
        </div>
        {canWrite && (
          <Button variant="secondary" size="sm" icon={Pencil} onClick={() => setEditing(true)} className="shrink-0">
            Edit
          </Button>
        )}
      </div>
      {editing && <AvatarEditModal avatar={avatar} onClose={() => setEditing(false)} onSaved={(patch) => setAvatar({ ...avatar, ...patch })} />}
      <AvatarPlayer portraitUrl={avatar.image_signed_url || ''} videoUrl={activeVideoUrl} isGenerating={isGenerating} onPlaybackEnded={() => setActiveVideoUrl(null)} />
      {error && <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-500 text-xs">{error}</div>}
      <div className="space-y-3">
        {turns.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-6">Ask a question to get started.</p>
        ) : (
          turns.map((turn) => <AvatarTurnBubble key={turn.id} turn={turn} onPlay={() => setActiveVideoUrl(turn.video_signed_url || null)} />)
        )}
      </div>
      <div className="fixed bottom-6 left-1/2 -translate-x-1/2 w-full max-w-3xl px-4">
        <AvatarChatInput onSubmitText={onAsk} onSubmitAudio={onAskAudio} disabled={!canWrite || submitting || isGenerating} disabledReason={!canWrite ? 'Master users only.' : isGenerating ? 'Generating reply…' : undefined} />
      </div>
    </motion.div>
  )
}

export const AvatarWorkPage = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const canWrite = useAuthStore((s) => s.isMaster || s.isPower)
  const state = useAvatarTurnsState(id)
  const { handleAsk, handleAskAudio } = useSubmitTurnAction(id, state)

  if (!state.avatar) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-4">
        {state.error ? <p className="text-sm text-red-500">{state.error}</p> : <><Loader2 className="animate-spin text-accent" size={32} /><p className="text-sm text-muted-foreground">Loading avatar…</p></>}
      </div>
    )
  }
  if (state.avatar.version === 'v2') return <AvatarLiveView avatar={state.avatar} />
  return (
    <AvatarV1View avatar={state.avatar} setAvatar={state.setAvatar} turns={state.turns} activeVideoUrl={state.activeVideoUrl} setActiveVideoUrl={state.setActiveVideoUrl} isGenerating={state.isGenerating} error={state.error} submitting={state.submitting} canWrite={canWrite} onBack={() => navigate('/avatars')} onAsk={handleAsk} onAskAudio={handleAskAudio} />
  )
}
