// Microphone capture for the v2 live session. Wraps an AudioWorkletNode
// that emits 16 kHz mono Int16 PCM chunks (~100 ms each) to onChunk.
//
// The worklet runs in a separate thread; this class handles permissions,
// the AudioContext, mute, and teardown.

export class AudioCapture {
  private context: AudioContext | null = null
  private node: AudioWorkletNode | null = null
  private source: MediaStreamAudioSourceNode | null = null
  private stream: MediaStream | null = null
  private muted = false

  async start(onChunk: (pcm: ArrayBuffer) => void): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    })
    this.context = new AudioContext()
    // Resume after creation — browsers create AudioContext in 'suspended'
    // state until the user gestures. Without this, the worklet runs but
    // input samples are all zero.
    if (this.context.state === 'suspended') {
      try { await this.context.resume() } catch {}
    }
    await this.context.audioWorklet.addModule('/audio-capture-worklet.js')
    this.source = this.context.createMediaStreamSource(this.stream)
    this.node = new AudioWorkletNode(this.context, 'audio-capture-processor')
    let chunkCount = 0
    this.node.port.onmessage = (e) => {
      if (this.muted) return
      const pcm = e.data as ArrayBuffer
      // Log first chunk + occasional samples so we can confirm non-silent
      // capture from the browser console.
      if (chunkCount < 3 || chunkCount % 100 === 0) {
        const view = new DataView(pcm)
        let peak = 0
        for (let i = 0; i < view.byteLength; i += 2) {
          const s = Math.abs(view.getInt16(i, true))
          if (s > peak) peak = s
        }
        // eslint-disable-next-line no-console
        console.log(
          `[mic] chunk #${chunkCount} ${pcm.byteLength}B peak=${peak} ` +
          `ctx=${this.context?.state}`,
        )
      }
      chunkCount++
      onChunk(pcm)
    }
    this.source.connect(this.node)
    // Chrome won't run a worklet that has no downstream connection. Route
    // it into a muted gain node so the user doesn't hear their own mic.
    const sink = this.context.createGain()
    sink.gain.value = 0
    this.node.connect(sink)
    sink.connect(this.context.destination)
  }

  setMuted(muted: boolean) {
    this.muted = muted
  }

  isMuted() {
    return this.muted
  }

  stop() {
    try { this.node?.disconnect() } catch {}
    try { this.source?.disconnect() } catch {}
    this.stream?.getTracks().forEach((t) => t.stop())
    this.context?.close().catch(() => {})
    this.context = null
    this.node = null
    this.source = null
    this.stream = null
  }
}
