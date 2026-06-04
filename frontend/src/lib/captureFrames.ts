import { api } from '@/lib/api'
import { parseTimestamp } from '@/lib/utils'

export interface FrameMoment {
  timestamp_start: string
  timestamp_end: string
}

export interface CapturedFrame {
  index: number
  gcs_uri: string
  signed_url: string
}

/**
 * Capture a still frame at the midpoint of each moment by seeking the <video>,
 * drawing onto a <canvas>, and uploading the PNG to GCS. Shared by the
 * Thumbnails (screenshots) and Key Moments (frames) features.
 *
 * The video element must have `crossOrigin="anonymous"` so the canvas isn't
 * tainted. `onCaptured` fires after each successful upload for incremental UI.
 */
export async function captureVideoFrames(
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement,
  moments: FrameMoment[],
  onCaptured?: (frame: CapturedFrame) => void,
): Promise<CapturedFrame[]> {
  const ctx = canvas.getContext('2d')
  if (!ctx) return []

  const captured: CapturedFrame[] = []

  for (let i = 0; i < moments.length; i++) {
    const moment = moments[i]
    const startSec = parseTimestamp(moment.timestamp_start)
    const endSec = parseTimestamp(moment.timestamp_end)
    const midpoint = (startSec + endSec) / 2

    video.currentTime = midpoint
    await new Promise<void>(resolve => {
      video.addEventListener('seeked', () => resolve(), { once: true })
    })

    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    ctx.drawImage(video, 0, 0)

    const blob = await new Promise<Blob | null>(resolve =>
      canvas.toBlob(resolve, 'image/png'),
    )
    if (!blob) continue

    const file = new File([blob], `frame-${i}.png`, { type: 'image/png' })
    const result = await api.assets.upload(file)
    const frame: CapturedFrame = {
      index: i,
      gcs_uri: result.gcs_uri,
      signed_url: result.signed_url,
    }
    captured.push(frame)
    onCaptured?.(frame)
  }

  return captured
}
