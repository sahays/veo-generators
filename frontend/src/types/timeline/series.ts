import type { TimelineEmotion } from '@/types/insights'
import type { IntervalIndex } from './intervalIndex'

export interface EmotionSample {
  /** Sample time in seconds (the middle of its bin). */
  time: number
  /** Strongest intensity active at that time, 0 when no emotion is tagged. */
  intensity: number
  /** Name of that strongest emotion, or null. */
  emotion: string | null
}

/**
 * Emotion intensity over time for charting: the strongest tagged emotion at
 * the middle of each of up to `maxSamples` equal bins. Each sample is one
 * index lookup; intensities are taken from the spans as they are, never
 * averaged across spans.
 */
export function emotionIntensitySeries(
  emotions: IntervalIndex<TimelineEmotion>,
  duration: number,
  maxSamples = 120,
): EmotionSample[] {
  if (!(duration > 0)) return []
  const count = Math.max(Math.min(Math.floor(maxSamples), Math.ceil(duration * 4)), 1)
  const step = duration / count
  const samples: EmotionSample[] = []
  for (let i = 0; i < count; i++) {
    const time = Math.round((i + 0.5) * step * 100) / 100
    const active = emotions.at(time)
    const top = active.reduce<TimelineEmotion | null>((best, e) => (best && best.intensity >= e.intensity ? best : e), null)
    samples.push({ time, intensity: top?.intensity ?? 0, emotion: top?.emotion ?? null })
  }
  return samples
}
