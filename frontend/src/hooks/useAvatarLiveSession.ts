// Lifecycle for the v2 avatar live session: opens the WS, wires up the
// audio + video sinks, and tears everything down on unmount or when the
// caller toggles `disconnected`.

import { useEffect, useRef, useState } from 'react'
import { api, buildAvatarLiveUrl } from '@/lib/api'
import { AudioCapture } from '@/components/avatar/live/AudioCapture'
import { AudioPlayer } from '@/components/avatar/live/AudioPlayer'
import { GeminiLiveSession } from '@/components/avatar/live/GeminiLiveSession'
import { VideoCanvasSink } from '@/components/avatar/live/VideoCanvasSink'

export type AvatarLiveStatus =
  | 'idle'
  | 'connecting'
  | 'connected'
  | 'error'
  | 'closed'

interface Options {
  avatarId: string
  enabled: boolean
  canvasRef: React.RefObject<HTMLCanvasElement>
}

interface ChunkEventDetail {
  mimeType: string
  data: Uint8Array
}

interface ErrorEventDetail {
  error?: { message?: string }
}

function attachSessionListeners(
  session: GeminiLiveSession,
  sink: VideoCanvasSink,
  player: AudioPlayer,
  setStatus: (s: AvatarLiveStatus) => void,
  setError: (e: string | null) => void,
): void {
  session.addEventListener('connected', () => setStatus('connected'))
  session.addEventListener('disconnected', () => setStatus('closed'))
  session.addEventListener('error', (e: Event) => {
    const detail = (e as CustomEvent<ErrorEventDetail>).detail
    setStatus('error')
    setError(detail?.error?.message ?? 'Live session error')
  })
  session.addEventListener('video-chunk', (e: Event) => {
    const detail = (e as CustomEvent<ChunkEventDetail>).detail
    sink.pushChunk(detail.mimeType, detail.data)
  })
  session.addEventListener('audio-chunk', (e: Event) => {
    const detail = (e as CustomEvent<ChunkEventDetail>).detail
    player.pushChunk(detail.mimeType, detail.data)
  })
}

interface SessionRefs {
  sessionRef: React.MutableRefObject<GeminiLiveSession | null>
  captureRef: React.MutableRefObject<AudioCapture | null>
  sinkRef: React.MutableRefObject<VideoCanvasSink | null>
  playerRef: React.MutableRefObject<AudioPlayer | null>
}

function teardownRefs(refs: SessionRefs): void {
  refs.captureRef.current?.stop()
  refs.sessionRef.current?.close()
  refs.sinkRef.current?.destroy()
  refs.playerRef.current?.destroy()
  refs.captureRef.current = null
  refs.sessionRef.current = null
  refs.sinkRef.current = null
  refs.playerRef.current = null
}

async function runLiveSession(
  avatarId: string,
  canvasEl: HTMLCanvasElement | null,
  refs: SessionRefs,
  setStatus: (s: AvatarLiveStatus) => void,
  setError: (e: string | null) => void,
  isCancelled: () => boolean,
): Promise<void> {
  setStatus('connecting')
  setError(null)
  await api.avatars.liveConfig(avatarId)
  if (isCancelled()) return
  if (!canvasEl) throw new Error('Canvas not ready')

  const sink = new VideoCanvasSink(canvasEl, setError)
  const player = new AudioPlayer()
  const session = new GeminiLiveSession()
  refs.sinkRef.current = sink
  refs.playerRef.current = player
  refs.sessionRef.current = session

  attachSessionListeners(session, sink, player, setStatus, setError)
  await session.connect(buildAvatarLiveUrl(avatarId))
  if (isCancelled()) return

  const capture = new AudioCapture()
  refs.captureRef.current = capture
  await capture.start((pcm) => session.sendAudioChunk(pcm))
}

export const useAvatarLiveSession = ({ avatarId, enabled, canvasRef }: Options) => {
  const sessionRef = useRef<GeminiLiveSession | null>(null)
  const captureRef = useRef<AudioCapture | null>(null)
  const sinkRef = useRef<VideoCanvasSink | null>(null)
  const playerRef = useRef<AudioPlayer | null>(null)
  const [status, setStatus] = useState<AvatarLiveStatus>('idle')
  const [error, setError] = useState<string | null>(null)

  const refs: SessionRefs = { sessionRef, captureRef, sinkRef, playerRef }
  const teardown = () => teardownRefs(refs)

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    runLiveSession(avatarId, canvasRef.current, refs, setStatus, setError, () => cancelled).catch(
      (err: unknown) => {
        if (cancelled) return
        setStatus('error')
        setError(err instanceof Error ? err.message : 'Failed to start session')
      },
    )
    return () => {
      cancelled = true
      teardownRefs(refs)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [avatarId, enabled])

  return { status, setStatus, error, setError, sessionRef, captureRef, sinkRef, audioPlayerRef: playerRef, teardown }
}
