import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowLeft, Loader2, Pencil } from 'lucide-react'
import { api } from '@/lib/api'
import { useAuthStore } from '@/store/useAuthStore'
import { AvatarPlayer } from '@/components/avatar/AvatarPlayer'
import { AvatarChatInput } from '@/components/avatar/AvatarChatInput'
import { AvatarTurnBubble } from '@/components/avatar/AvatarTurnBubble'
import { AvatarEditModal } from '@/components/avatar/AvatarEditModal'
import { AvatarLiveView } from '@/components/avatar/AvatarLiveView'
import type { Avatar, AvatarTurn } from '@/types/avatar'
import { STYLE_LABELS, VOICE_TURN_MARKER } from '@/types/avatar'

export const AvatarWorkPage = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { isMaster } = useAuthStore()

  const [avatar, setAvatar] = useState<Avatar | null>(null)
  const [turns, setTurns] = useState<AvatarTurn[]>([])
  const [activeTurnId, setActiveTurnId] = useState<string | null>(null)
  const [activeVideoUrl, setActiveVideoUrl] = useState<string | null>(null)
  const [isGenerating, setIsGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [editing, setEditing] = useState(false)

  // Initial fetch — also resume polling if any turn is still rendering.
  useEffect(() => {
    if (!id) return
    Promise.all([api.avatars.get(id), api.avatars.listTurns(id)])
      .then(([a, ts]) => {
        setAvatar(a)
        setTurns(ts)
        const inflight = ts.find(
          (t: AvatarTurn) => t.status === 'pending' || t.status === 'generating',
        )
        if (inflight) {
          setIsGenerating(true)
          setActiveTurnId(inflight.id)
        }
      })
      .catch((err) => setError(err.message || 'Failed to load avatar'))
  }, [id])

  // Poll the active turn until it completes
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
  }, [activeTurnId])

  const buildHistory = useCallback(
    () =>
      turns
        .slice(-10)
        .filter((t) => t.question !== VOICE_TURN_MARKER && t.answer_text)
        .flatMap((t) => [
          { role: 'user', content: t.question },
          { role: 'model', content: t.answer_text },
        ]),
    [turns],
  )

  const submitTurn = useCallback(
    async (
      placeholderQuestion: string,
      callApi: (history: { role: string; content: string }[]) => Promise<{
        turn_id: string
        answer_text: string
        status: string
      }>,
    ) => {
      if (!id) return
      setSubmitting(true)
      setError(null)
      const localId = `local-${Date.now()}`
      const placeholder: AvatarTurn = {
        id: localId,
        avatar_id: id,
        question: placeholderQuestion,
        answer_text: '',
        status: 'pending',
        progress_pct: 0,
        createdAt: new Date().toISOString(),
      }
      setTurns((prev) => [placeholder, ...prev])
      try {
        const result = await callApi(buildHistory())
        const realTurn: AvatarTurn = {
          ...placeholder,
          id: result.turn_id,
          answer_text: result.answer_text,
        }
        setTurns((prev) => prev.map((t) => (t.id === localId ? realTurn : t)))
        setIsGenerating(true)
        setActiveTurnId(result.turn_id)
        setActiveVideoUrl(null)
      } catch (err) {
        setTurns((prev) => prev.filter((t) => t.id !== localId))
        setError(err instanceof Error ? err.message : 'Failed to ask')
      } finally {
        setSubmitting(false)
      }
    },
    [id, buildHistory],
  )

  const handleAsk = useCallback(
    (question: string) =>
      submitTurn(question, (history) =>
        api.avatars.ask(id!, { question, history }),
      ),
    [id, submitTurn],
  )

  const handleAskAudio = useCallback(
    (audio: Blob) =>
      submitTurn(VOICE_TURN_MARKER, (history) =>
        api.avatars.askAudio(id!, audio, history),
      ),
    [id, submitTurn],
  )

  if (!avatar) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-4">
        {error ? (
          <p className="text-sm text-red-500">{error}</p>
        ) : (
          <>
            <Loader2 className="animate-spin text-accent" size={32} />
            <p className="text-sm text-muted-foreground">Loading avatar…</p>
          </>
        )}
      </div>
    )
  }

  if (avatar.version === 'v2') {
    return <AvatarLiveView avatar={avatar} />
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="max-w-3xl mx-auto space-y-6 pb-32"
    >
      <button
        onClick={() => navigate('/avatars')}
        className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft size={14} /> Back to Avatars
      </button>

      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-2xl font-heading text-foreground tracking-tight truncate">{avatar.name}</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            {STYLE_LABELS[avatar.style]}
            {avatar.persona_prompt
              ? ` · ${avatar.persona_prompt.slice(0, 80)}${avatar.persona_prompt.length > 80 ? '…' : ''}`
              : ' · No persona set'}
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

      {editing && avatar && (
        <AvatarEditModal
          avatar={avatar}
          onClose={() => setEditing(false)}
          onSaved={(patch) => setAvatar({ ...avatar, ...patch })}
        />
      )}

      <AvatarPlayer
        portraitUrl={avatar.image_signed_url || ''}
        videoUrl={activeVideoUrl}
        isGenerating={isGenerating}
        onPlaybackEnded={() => setActiveVideoUrl(null)}
      />

      {error && (
        <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-500 text-xs">
          {error}
        </div>
      )}

      <div className="space-y-3">
        {turns.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-6">
            Ask a question to get started.
          </p>
        ) : (
          turns.map((turn) => (
            <AvatarTurnBubble
              key={turn.id}
              turn={turn}
              onPlay={() => setActiveVideoUrl(turn.video_signed_url || null)}
            />
          ))
        )}
      </div>

      <div className="fixed bottom-6 left-1/2 -translate-x-1/2 w-full max-w-3xl px-4">
        <AvatarChatInput
          onSubmitText={handleAsk}
          onSubmitAudio={handleAskAudio}
          disabled={!isMaster || submitting || isGenerating}
          disabledReason={
            !isMaster
              ? 'Master users only.'
              : isGenerating
                ? 'Generating reply…'
                : undefined
          }
        />
      </div>
    </motion.div>
  )
}
