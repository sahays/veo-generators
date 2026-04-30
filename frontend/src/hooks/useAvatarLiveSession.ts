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

export const useAvatarLiveSession = ({
  avatarId,
  enabled,
  canvasRef,
}: Options) => {
  const sessionRef = useRef<GeminiLiveSession | null>(null)
  const captureRef = useRef<AudioCapture | null>(null)
  const sinkRef = useRef<VideoCanvasSink | null>(null)
  const playerRef = useRef<AudioPlayer | null>(null)

  const [status, setStatus] = useState<AvatarLiveStatus>('idle')
  const [error, setError] = useState<string | null>(null)

  const teardown = () => {
    captureRef.current?.stop()
    sessionRef.current?.close()
    sinkRef.current?.destroy()
    playerRef.current?.destroy()
    captureRef.current = null
    sessionRef.current = null
    sinkRef.current = null
    playerRef.current = null
  }

  useEffect(() => {
    if (!enabled) return
    let cancelled = false

    async function start() {
      setStatus('connecting')
      setError(null)
      try {
        // /live-config still gates the session (auth, voice, system prompt)
        // even though we no longer need its image URL — keep calling it.
        await api.avatars.liveConfig(avatarId)
        if (cancelled) return
        if (!canvasRef.current) throw new Error('Canvas not ready')

        const sink = new VideoCanvasSink(canvasRef.current, setError)
        sinkRef.current = sink
        const player = new AudioPlayer()
        playerRef.current = player
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
            console.log(`[audio-chunk] #${audioChunkCount}`, {
              mime: e.detail.mimeType,
              size: e.detail.data.byteLength,
            })
          }
          player.pushChunk(e.detail.mimeType, e.detail.data)
        })

        await session.connect(buildAvatarLiveUrl(avatarId))
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
      teardown()
    }
    // canvasRef is a ref; teardown is closed over identity-stable refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [avatarId, enabled])

  return {
    status,
    setStatus,
    error,
    setError,
    sessionRef,
    captureRef,
    sinkRef,
    audioPlayerRef: playerRef,
    teardown,
  }
}
