// Schedules raw PCM audio chunks (Int16, mime e.g. "audio/pcm;rate=24000")
// onto a WebAudio context. Used as a fallback when the live session is
// audio-only — when the model streams video too, audio rides inside the
// MP4 and this class is unused.

export class AudioPlayer {
  private context: AudioContext | null = null
  private nextStartTime = 0
  private chunkCount = 0

  pushChunk(mimeType: string, data: Uint8Array) {
    this._ensureContext()
    if (!this.context) return
    // Opportunistic resume — covers the case where the user has interacted
    // with the page since we created the context.
    if (this.context.state === 'suspended') {
      void this.context.resume().catch(() => {})
    }
    this.chunkCount += 1
    if (this.chunkCount === 1 || this.chunkCount % 50 === 0) {
      const view = new DataView(data.buffer, data.byteOffset, data.byteLength)
      let peak = 0
      for (let i = 0; i < view.byteLength; i += 2) {
        const s = Math.abs(view.getInt16(i, true))
        if (s > peak) peak = s
      }
      // eslint-disable-next-line no-console
      console.log(
        `[AudioPlayer] chunk #${this.chunkCount} mime=${mimeType} ` +
          `size=${data.byteLength} peak=${peak} ctx=${this.context.state}`,
      )
    }
    const sampleRate = parseRate(mimeType) ?? 24000
    const samples = data.byteLength / 2
    if (samples <= 0) return
    const view = new DataView(data.buffer, data.byteOffset, data.byteLength)
    const f32 = new Float32Array(samples)
    for (let i = 0; i < samples; i++) {
      f32[i] = view.getInt16(i * 2, true) / 0x8000
    }
    const buffer = this.context.createBuffer(1, samples, sampleRate)
    buffer.copyToChannel(f32, 0)
    const src = this.context.createBufferSource()
    src.buffer = buffer
    src.connect(this.context.destination)
    const now = this.context.currentTime
    const start = Math.max(now, this.nextStartTime)
    src.start(start)
    this.nextStartTime = start + buffer.duration
  }

  private _ensureContext() {
    if (!this.context) {
      this.context = new AudioContext()
      this.nextStartTime = this.context.currentTime
    }
  }

  /** Force-resume the underlying AudioContext. Safe to call from within a
   * user-gesture handler — browsers will then unblock audio output. */
  async resume(): Promise<void> {
    this._ensureContext()
    if (this.context && this.context.state === 'suspended') {
      try { await this.context.resume() } catch {}
    }
  }

  destroy() {
    this.context?.close().catch(() => {})
    this.context = null
    this.nextStartTime = 0
  }
}

function parseRate(mimeType: string): number | null {
  const m = /rate=(\d+)/.exec(mimeType)
  return m ? parseInt(m[1], 10) : null
}
