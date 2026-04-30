// AudioWorkletProcessor: downsamples mic input to 16 kHz mono, packs as
// Int16 little-endian PCM, and posts ~100 ms chunks back to the main thread.
//
// This file is loaded as a static asset (not bundled) — keep it standalone
// vanilla ES.

const TARGET_RATE = 16000
const TARGET_CHUNK_SAMPLES = 1600  // 100 ms @ 16 kHz

class AudioCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this._pending = new Float32Array(0)
    this._ratio = sampleRate / TARGET_RATE
    this._inIndex = 0
  }

  _appendInput(input) {
    const merged = new Float32Array(this._pending.length + input.length)
    merged.set(this._pending, 0)
    merged.set(input, this._pending.length)
    this._pending = merged
  }

  _drainAndDownsample() {
    // Linear-interpolation resampler. Consumes from _pending until we don't
    // have enough source samples for the next output sample, then keeps the
    // remainder in _pending for the next call.
    const out = []
    while (true) {
      const needed = Math.ceil(this._inIndex) + 1
      if (needed >= this._pending.length) break
      const lo = Math.floor(this._inIndex)
      const hi = lo + 1
      const frac = this._inIndex - lo
      const sample = this._pending[lo] * (1 - frac) + this._pending[hi] * frac
      out.push(Math.max(-1, Math.min(1, sample)))
      this._inIndex += this._ratio
    }
    if (this._inIndex >= 1) {
      const consumed = Math.floor(this._inIndex)
      this._pending = this._pending.slice(consumed)
      this._inIndex -= consumed
    }
    return out
  }

  process(inputs) {
    const input = inputs[0]
    if (!input || input.length === 0) return true
    const channel = input[0]
    if (!channel || channel.length === 0) return true

    this._appendInput(channel)
    const downsampled = this._drainAndDownsample()
    if (downsampled.length === 0) return true

    if (!this._chunk) {
      this._chunk = []
    }
    for (let i = 0; i < downsampled.length; i++) {
      this._chunk.push(downsampled[i])
      if (this._chunk.length >= TARGET_CHUNK_SAMPLES) {
        this._flushChunk()
      }
    }
    return true
  }

  _flushChunk() {
    const samples = this._chunk
    this._chunk = []
    const buf = new ArrayBuffer(samples.length * 2)
    const view = new DataView(buf)
    for (let i = 0; i < samples.length; i++) {
      const s = Math.max(-1, Math.min(1, samples[i]))
      view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true)
    }
    this.port.postMessage(buf, [buf])
  }
}

registerProcessor('audio-capture-processor', AudioCaptureProcessor)
