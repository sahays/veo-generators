// WebCodecs + mp4box.js media pipeline. Replaces the MediaSource path,
// which Chrome's chunk demuxer kept rejecting with "does not match what is
// specified in the mimetype" no matter what codec hint we passed.
//
// mp4box.js parses the fragmented MP4 the model emits and hands us per-sample
// byte ranges. The Live Avatar API multiplexes both video AND audio into the
// same MP4 — so this sink owns both decoders:
//
//   video samples → VideoDecoder → VideoFrame → ctx.drawImage(canvas)
//   audio samples → AudioDecoder → AudioData   → AudioBufferSourceNode (WebAudio)

import {
  createFile,
  MP4BoxBuffer,
  type ISOFile,
  type Movie,
  type Sample,
  type Track,
} from 'mp4box'
import {
  decodeAudioSamples,
  decodeVideoSamples,
  extractAudioDescription,
  extractAvcDescription,
  scheduleAudioBuffer,
} from './videoCanvasHelpers'

export class VideoCanvasSink {
  private mp4: ISOFile
  private videoDecoder: VideoDecoder | null = null
  private audioDecoder: AudioDecoder | null = null
  private videoTrackId = -1
  private audioTrackId = -1
  private offset = 0
  private destroyed = false
  private broken = false
  private trackReady = false

  private audioCtx: AudioContext | null = null
  private nextAudioStart = 0
  private streamOffset: number | null = null
  private pendingVideoFrames: VideoFrame[] = []
  private canvasCtx: CanvasRenderingContext2D | null = null

  private pendingVideoSamples: Sample[] = []
  private pendingAudioSamples: Sample[] = []

  constructor(
    private canvas: HTMLCanvasElement,
    private onBroken?: (reason: string) => void,
  ) {
    this.mp4 = createFile()
    this.mp4.onError = (e: string) => this._fail('mp4box error: ' + e)
    this.mp4.onReady = (info: Movie) => {
      try {
        this._onReadySync(info)
      } catch (e) {
        this._fail('onReady setup failed: ' + (e as Error).message)
      }
    }
    this.mp4.onSamples = (id: number, _user: unknown, samples: Sample[]) =>
      this._onSamples(id, samples)
  }

  pushChunk(_mimeType: string, data: Uint8Array) {
    if (this.broken || this.destroyed) return
    const buf = MP4BoxBuffer.fromArrayBuffer(data.slice().buffer, this.offset)
    this.offset += buf.byteLength
    try {
      this.mp4.appendBuffer(buf)
    } catch (e) {
      this._fail('mp4.appendBuffer threw: ' + (e as Error).message)
    }
  }

  /** Resume the audio playback context — call from a user-gesture handler. */
  async resume(): Promise<void> {
    this._ensureAudioContext()
    if (this.audioCtx && this.audioCtx.state === 'suspended') {
      try { await this.audioCtx.resume() } catch {}
    }
  }

  private _ensureAudioContext() {
    if (!this.audioCtx) {
      this.audioCtx = new AudioContext()
      this.nextAudioStart = this.audioCtx.currentTime
    }
  }

  private _onReadySync(info: Movie) {
    if (this.trackReady) return
    const videoTrack = info.videoTracks[0]
    if (!videoTrack) {
      this._fail('no video track in init segment')
      return
    }
    this.videoTrackId = videoTrack.id
    this._configureVideo(videoTrack)

    const audioTrack = info.audioTracks?.[0]
    if (audioTrack) {
      this.audioTrackId = audioTrack.id
      this._configureAudio(audioTrack)
    }

    this.mp4.setExtractionOptions(videoTrack.id, null, { nbSamples: 5 })
    if (audioTrack) {
      this.mp4.setExtractionOptions(audioTrack.id, null, { nbSamples: 10 })
    }
    this.mp4.start()
    this.trackReady = true
    this._drainPendingSamples()
  }

  private _drainPendingSamples() {
    if (this.pendingVideoSamples.length && this.videoDecoder) {
      const drained = this.pendingVideoSamples
      this.pendingVideoSamples = []
      decodeVideoSamples(this.videoDecoder, drained)
    }
    if (this.pendingAudioSamples.length && this.audioDecoder) {
      const drained = this.pendingAudioSamples
      this.pendingAudioSamples = []
      decodeAudioSamples(this.audioDecoder, drained)
    }
  }

  private _configureVideo(track: Track) {
    const description = extractAvcDescription(this.mp4, track)
    if (!description) {
      this._fail('could not extract avcC description')
      return
    }
    const width = track.video?.width ?? 0
    const height = track.video?.height ?? 0
    this.canvas.width = width
    this.canvas.height = height
    const ctx = this.canvas.getContext('2d')
    if (!ctx) {
      this._fail('could not acquire 2D canvas context')
      return
    }
    this.canvasCtx = ctx
    this.videoDecoder = new VideoDecoder({
      output: (frame) => this._scheduleVideoFrame(frame),
      error: (e) => this._fail('VideoDecoder error: ' + e.message),
    })
    this.videoDecoder.configure({
      codec: track.codec,
      codedWidth: width,
      codedHeight: height,
      description,
    })
  }

  private _configureAudio(track: Track) {
    const description = extractAudioDescription(this.mp4, track)
    if (!description) return
    this._ensureAudioContext()
    this.audioDecoder = new AudioDecoder({
      output: (audio) => {
        try {
          this._playAudioData(audio)
        } finally {
          audio.close()
        }
      },
      error: () => {},
    })
    this.audioDecoder.configure({
      codec: track.codec,
      sampleRate: track.audio?.sample_rate ?? 24000,
      numberOfChannels: track.audio?.channel_count ?? 1,
      description,
    })
  }

  private _onSamples(trackId: number, samples: Sample[]) {
    if (trackId === this.videoTrackId) {
      if (!this.videoDecoder || this.videoDecoder.state !== 'configured') {
        this.pendingVideoSamples.push(...samples)
        return
      }
      decodeVideoSamples(this.videoDecoder, samples)
    } else if (trackId === this.audioTrackId) {
      if (!this.audioDecoder || this.audioDecoder.state !== 'configured') {
        this.pendingAudioSamples.push(...samples)
        return
      }
      decodeAudioSamples(this.audioDecoder, samples)
    }
  }

  private _playAudioData(audio: AudioData) {
    this._ensureAudioContext()
    if (!this.audioCtx) return
    const { start, nextStart } = scheduleAudioBuffer(
      this.audioCtx,
      audio,
      this.nextAudioStart,
    )
    this.nextAudioStart = nextStart

    if (this.streamOffset === null) {
      const audioStreamSec = audio.timestamp / 1_000_000
      this.streamOffset = start - audioStreamSec
      const drained = this.pendingVideoFrames
      this.pendingVideoFrames = []
      for (const f of drained) this._scheduleVideoFrame(f)
    }
  }

  private _scheduleVideoFrame(frame: VideoFrame) {
    if (this.destroyed) {
      try { frame.close() } catch {}
      return
    }
    if (this.streamOffset === null || !this.audioCtx) {
      this.pendingVideoFrames.push(frame)
      return
    }
    const streamSec = (frame.timestamp ?? 0) / 1_000_000
    const target = streamSec + this.streamOffset
    const delayMs = Math.max(0, (target - this.audioCtx.currentTime) * 1000)
    if (delayMs <= 1) {
      this._drawFrame(frame)
      return
    }
    setTimeout(() => {
      if (this.destroyed) {
        try { frame.close() } catch {}
        return
      }
      this._drawFrame(frame)
    }, delayMs)
  }

  private _drawFrame(frame: VideoFrame) {
    try {
      this.canvasCtx?.drawImage(
        frame,
        0,
        0,
        this.canvas.width,
        this.canvas.height,
      )
    } finally {
      frame.close()
    }
  }

  private _fail(reason: string) {
    if (this.broken) return
    this.broken = true
    try {
      this.onBroken?.(reason)
    } catch {
      // Swallow caller errors; we still need to stop accepting chunks.
    }
  }

  destroy() {
    this.destroyed = true
    for (const f of this.pendingVideoFrames) {
      try { f.close() } catch {}
    }
    this.pendingVideoFrames = []
    if (this.videoDecoder && this.videoDecoder.state !== 'closed') {
      try { this.videoDecoder.close() } catch {}
    }
    if (this.audioDecoder && this.audioDecoder.state !== 'closed') {
      try { this.audioDecoder.close() } catch {}
    }
    if (this.audioCtx && this.audioCtx.state !== 'closed') {
      try { void this.audioCtx.close() } catch {}
    }
    try { this.mp4.flush() } catch {}
  }
}
