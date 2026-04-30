// WebCodecs + mp4box.js media pipeline. Replaces the MediaSource path,
// which Chrome's chunk demuxer kept rejecting with "does not match what is
// specified in the mimetype" no matter what codec hint we passed.
//
// mp4box.js parses the fragmented MP4 the model emits and hands us per-sample
// byte ranges. The Live Avatar API multiplexes both video AND audio into the
// same MP4 (we confirmed `audioTracks: 1` from mp4box's onReady) — so this
// sink owns both decoders:
//
//   video samples → VideoDecoder → VideoFrame → ctx.drawImage(canvas)
//   audio samples → AudioDecoder → AudioData   → AudioBufferSourceNode (WebAudio)
//
// WebCodecs takes the binary avcC / AudioSpecificConfig as the `description`
// field, so there's no codec-string round-trip to fight Chrome over.

import {
  createFile,
  DataStream,
  Endianness,
  MP4BoxBuffer,
  type ISOFile,
  type Movie,
  type Sample,
  type Track,
} from 'mp4box'

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

  // Audio playback timeline.
  private audioCtx: AudioContext | null = null
  private nextAudioStart = 0
  // Maps stream timestamps (seconds) to AudioContext wall-clock time:
  //   wallClock = streamSeconds + streamOffset
  // Set once when the first audio AudioData is scheduled. Video frames are
  // queued until this is anchored, then drawn at their target wall-clock
  // time so lip-sync matches the audio.
  private streamOffset: number | null = null
  private pendingVideoFrames: VideoFrame[] = []
  private canvasCtx: CanvasRenderingContext2D | null = null

  private chunkCount = 0
  private videoSampleCount = 0
  private audioSampleCount = 0
  private videoFrameCount = 0
  private audioDataCount = 0
  private pendingVideoSamples: Sample[] = []
  private pendingAudioSamples: Sample[] = []

  constructor(
    private canvas: HTMLCanvasElement,
    private onBroken?: (reason: string) => void,
  ) {
    this.mp4 = createFile()
    this.mp4.onError = (e: string) => this._fail('mp4box error: ' + e)
    this.mp4.onReady = (info: Movie) => {
      // eslint-disable-next-line no-console
      console.log('[VideoCanvasSink] mp4box onReady', {
        videoTracks: info.videoTracks?.length,
        audioTracks: info.audioTracks?.length,
        isFragmented: info.isFragmented,
        videoCodec: info.videoTracks?.[0]?.codec,
        audioCodec: info.audioTracks?.[0]?.codec,
        audioRate: info.audioTracks?.[0]?.audio?.sample_rate,
        audioChannels: info.audioTracks?.[0]?.audio?.channel_count,
      })
      try {
        this._onReadySync(info)
      } catch (e) {
        this._fail('onReady setup failed: ' + (e as Error).message)
      }
    }
    this.mp4.onSamples = (
      id: number,
      _user: unknown,
      samples: Sample[],
    ) => this._onSamples(id, samples)
    // eslint-disable-next-line no-console
    console.log('[VideoCanvasSink] constructed')
  }

  pushChunk(_mimeType: string, data: Uint8Array) {
    if (this.broken || this.destroyed) return
    this.chunkCount += 1
    if (this.chunkCount <= 3 || this.chunkCount % 200 === 0) {
      // eslint-disable-next-line no-console
      console.log(
        `[VideoCanvasSink] pushChunk #${this.chunkCount}`,
        { size: data.byteLength, offset: this.offset, ready: this.trackReady },
      )
    }
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

    // Tell mp4box which tracks to extract samples for. Then start.
    this.mp4.setExtractionOptions(videoTrack.id, null, { nbSamples: 5 })
    if (audioTrack) {
      this.mp4.setExtractionOptions(audioTrack.id, null, { nbSamples: 10 })
    }
    this.mp4.start()
    this.trackReady = true
    // eslint-disable-next-line no-console
    console.log('[VideoCanvasSink] decoders configured + extraction started')

    // Drain any samples mp4box buffered while we were setting up.
    if (this.pendingVideoSamples.length) {
      const drained = this.pendingVideoSamples
      this.pendingVideoSamples = []
      this._dispatchVideoSamples(drained)
    }
    if (this.pendingAudioSamples.length) {
      const drained = this.pendingAudioSamples
      this.pendingAudioSamples = []
      this._dispatchAudioSamples(drained)
    }
  }

  private _configureVideo(track: Track) {
    const description = extractAvcDescription(this.mp4, track)
    if (!description) {
      this._fail('could not extract avcC description')
      return
    }
    const config: VideoDecoderConfig = {
      codec: track.codec,
      codedWidth: track.video?.width ?? 0,
      codedHeight: track.video?.height ?? 0,
      description,
    }
    this.canvas.width = track.video?.width ?? 0
    this.canvas.height = track.video?.height ?? 0
    const ctx = this.canvas.getContext('2d')
    if (!ctx) {
      this._fail('could not acquire 2D canvas context')
      return
    }
    this.canvasCtx = ctx
    this.videoDecoder = new VideoDecoder({
      output: (frame) => {
        this.videoFrameCount += 1
        if (this.videoFrameCount === 1 || this.videoFrameCount % 60 === 0) {
          // eslint-disable-next-line no-console
          console.log(`[VideoCanvasSink] video frame #${this.videoFrameCount}`)
        }
        this._scheduleVideoFrame(frame)
      },
      error: (e) => this._fail('VideoDecoder error: ' + e.message),
    })
    this.videoDecoder.configure(config)
  }

  private _configureAudio(track: Track) {
    const description = extractAudioDescription(this.mp4, track)
    if (!description) {
      // eslint-disable-next-line no-console
      console.warn(
        '[VideoCanvasSink] no AudioSpecificConfig found in audio track — skipping audio',
      )
      return
    }
    this._ensureAudioContext()
    const config: AudioDecoderConfig = {
      codec: track.codec,
      sampleRate: track.audio?.sample_rate ?? 24000,
      numberOfChannels: track.audio?.channel_count ?? 1,
      description,
    }
    this.audioDecoder = new AudioDecoder({
      output: (audio) => {
        this.audioDataCount += 1
        try {
          this._playAudioData(audio)
        } finally {
          audio.close()
        }
      },
      error: (e) => {
        // eslint-disable-next-line no-console
        console.error('[VideoCanvasSink] AudioDecoder error', e.message)
      },
    })
    this.audioDecoder.configure(config)
    // eslint-disable-next-line no-console
    console.log('[VideoCanvasSink] audio decoder configured', {
      codec: track.codec,
      sampleRate: config.sampleRate,
      channels: config.numberOfChannels,
      descriptionBytes: description.byteLength,
    })
  }

  private _onSamples(trackId: number, samples: Sample[]) {
    if (trackId === this.videoTrackId) {
      if (!this.videoDecoder || this.videoDecoder.state !== 'configured') {
        this.pendingVideoSamples.push(...samples)
        return
      }
      this._dispatchVideoSamples(samples)
    } else if (trackId === this.audioTrackId) {
      if (!this.audioDecoder || this.audioDecoder.state !== 'configured') {
        this.pendingAudioSamples.push(...samples)
        return
      }
      this._dispatchAudioSamples(samples)
    }
  }

  private _dispatchVideoSamples(samples: Sample[]) {
    if (!this.videoDecoder) return
    for (const s of samples) {
      if (!s.data) continue
      this.videoSampleCount += 1
      if (
        this.videoSampleCount <= 2 ||
        this.videoSampleCount % 200 === 0
      ) {
        // eslint-disable-next-line no-console
        console.log(
          `[VideoCanvasSink] video sample #${this.videoSampleCount}`,
          { sync: s.is_sync, size: s.data.byteLength },
        )
      }
      this.videoDecoder.decode(
        new EncodedVideoChunk({
          type: s.is_sync ? 'key' : 'delta',
          timestamp: (s.cts * 1_000_000) / s.timescale,
          duration: (s.duration * 1_000_000) / s.timescale,
          data: s.data,
        }),
      )
    }
  }

  private _dispatchAudioSamples(samples: Sample[]) {
    if (!this.audioDecoder) return
    for (const s of samples) {
      if (!s.data) continue
      this.audioSampleCount += 1
      if (
        this.audioSampleCount <= 2 ||
        this.audioSampleCount % 200 === 0
      ) {
        // eslint-disable-next-line no-console
        console.log(
          `[VideoCanvasSink] audio sample #${this.audioSampleCount}`,
          { size: s.data.byteLength },
        )
      }
      this.audioDecoder.decode(
        new EncodedAudioChunk({
          type: 'key', // every AAC frame is independently decodable
          timestamp: (s.cts * 1_000_000) / s.timescale,
          duration: (s.duration * 1_000_000) / s.timescale,
          data: s.data,
        }),
      )
    }
  }

  private _playAudioData(audio: AudioData) {
    this._ensureAudioContext()
    const ctx = this.audioCtx
    if (!ctx) return
    if (ctx.state === 'suspended') {
      void ctx.resume().catch(() => {})
    }
    const numChannels = audio.numberOfChannels
    const numFrames = audio.numberOfFrames
    const sampleRate = audio.sampleRate
    const buffer = ctx.createBuffer(numChannels, numFrames, sampleRate)
    for (let ch = 0; ch < numChannels; ch++) {
      const channel = new Float32Array(numFrames)
      audio.copyTo(channel, { planeIndex: ch, format: 'f32-planar' })
      buffer.copyToChannel(channel, ch)
    }
    const src = ctx.createBufferSource()
    src.buffer = buffer
    src.connect(ctx.destination)
    const start = Math.max(ctx.currentTime, this.nextAudioStart)
    src.start(start)
    this.nextAudioStart = start + buffer.duration

    // Anchor the stream-to-wallclock relationship from the first audio
    // sample. Both video and audio timestamps share the same MP4 timebase,
    // so any video frame's wall-clock target is `streamTime + streamOffset`.
    if (this.streamOffset === null) {
      const audioStreamSec = audio.timestamp / 1_000_000
      this.streamOffset = start - audioStreamSec
      // eslint-disable-next-line no-console
      console.log('[VideoCanvasSink] sync anchored', {
        streamOffset: this.streamOffset,
        firstAudioStreamSec: audioStreamSec,
        startedAt: start,
        pendingVideoFrames: this.pendingVideoFrames.length,
      })
      // Drain any video frames decoded before audio caught up.
      const drained = this.pendingVideoFrames
      this.pendingVideoFrames = []
      for (const f of drained) this._scheduleVideoFrame(f)
    }
    if (this.audioDataCount === 1 || this.audioDataCount % 50 === 0) {
      // eslint-disable-next-line no-console
      console.log(
        `[VideoCanvasSink] audio data #${this.audioDataCount} ` +
          `frames=${numFrames} ch=${numChannels} rate=${sampleRate} ` +
          `ctx=${ctx.state}`,
      )
    }
  }

  private _scheduleVideoFrame(frame: VideoFrame) {
    if (this.destroyed) {
      try { frame.close() } catch {}
      return
    }
    // Until audio playback has actually started, we don't yet know the
    // wall-clock target for any frame. Buffer them.
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
    // eslint-disable-next-line no-console
    console.error('[VideoCanvasSink]', reason)
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

// Extract the AVCDecoderConfigurationRecord (avcC payload, no box header) for
// VideoDecoder.configure({ description }).
function extractAvcDescription(mp4: ISOFile, track: Track): Uint8Array | null {
  const trak = (mp4 as unknown as {
    getTrackById: (id: number) => unknown
  }).getTrackById(track.id) as
    | { mdia?: { minf?: { stbl?: { stsd?: { entries?: Array<unknown> } } } } }
    | undefined
  const entries = trak?.mdia?.minf?.stbl?.stsd?.entries ?? []
  for (const entry of entries) {
    const e = entry as {
      avcC?: { write: (s: DataStream) => void }
      hvcC?: { write: (s: DataStream) => void }
      vpcC?: { write: (s: DataStream) => void }
      av1C?: { write: (s: DataStream) => void }
    }
    const box = e.avcC ?? e.hvcC ?? e.vpcC ?? e.av1C
    if (!box) continue
    const stream = new DataStream(undefined, 0, Endianness.BIG_ENDIAN)
    stream.endianness = Endianness.BIG_ENDIAN
    box.write(stream)
    const buf = stream.buffer as ArrayBuffer
    // Skip 8-byte box header → just the configuration record payload.
    return new Uint8Array(buf, 8)
  }
  return null
}

// Walk the parsed esds DescriptorTree to find the AudioSpecificConfig bytes
// — that's what AudioDecoder wants in `description`.
//   esds → ES_Descriptor (tag 3) → DecoderConfigDescriptor (tag 4) →
//          DecSpecificInfo (tag 5)
// mp4box's parsed esds exposes nested `descs` arrays; the DSI's `data` field
// is the AudioSpecificConfig.
function extractAudioDescription(
  mp4: ISOFile,
  track: Track,
): Uint8Array | null {
  const trak = (mp4 as unknown as {
    getTrackById: (id: number) => unknown
  }).getTrackById(track.id) as
    | { mdia?: { minf?: { stbl?: { stsd?: { entries?: Array<unknown> } } } } }
    | undefined
  const entries = trak?.mdia?.minf?.stbl?.stsd?.entries ?? []
  for (const entry of entries) {
    const e = entry as {
      esds?: {
        esd?: { descs?: Array<{ tag?: number; descs?: Array<{ tag?: number; data?: Uint8Array | ArrayLike<number> }> }> }
      }
    }
    const esd = e.esds?.esd
    if (!esd) continue
    // Find DecoderConfigDescriptor (tag 4) inside ES_Descriptor.
    const dcd = esd.descs?.find((d) => d.tag === 4)
    if (!dcd) continue
    // Find DecSpecificInfo (tag 5) inside DCD.
    const dsi = dcd.descs?.find((d) => d.tag === 5)
    if (!dsi?.data) continue
    return dsi.data instanceof Uint8Array
      ? dsi.data
      : new Uint8Array(dsi.data as ArrayLike<number>)
  }
  return null
}
