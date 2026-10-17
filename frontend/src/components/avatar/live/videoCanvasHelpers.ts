// MP4 box description extractors and WebAudio buffer helpers for VideoCanvasSink.

import {
  DataStream,
  Endianness,
  type ISOFile,
  type Sample,
  type Track,
} from 'mp4box'

// Extract the AVCDecoderConfigurationRecord (avcC payload, no box header) for
// VideoDecoder.configure({ description }).
export function extractAvcDescription(mp4: ISOFile, track: Track): Uint8Array | null {
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
    return new Uint8Array(buf, 8)
  }
  return null
}

// Walk the parsed esds DescriptorTree to find the AudioSpecificConfig bytes
// — that's what AudioDecoder wants in `description`.
export function extractAudioDescription(
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
    const dcd = e.esds?.esd?.descs?.find((d) => d.tag === 4)
    const dsi = dcd?.descs?.find((d) => d.tag === 5)
    if (!dsi?.data) continue
    return dsi.data instanceof Uint8Array
      ? dsi.data
      : new Uint8Array(dsi.data as ArrayLike<number>)
  }
  return null
}

export function decodeVideoSamples(decoder: VideoDecoder, samples: Sample[]): void {
  for (const s of samples) {
    if (!s.data) continue
    decoder.decode(
      new EncodedVideoChunk({
        type: s.is_sync ? 'key' : 'delta',
        timestamp: (s.cts * 1_000_000) / s.timescale,
        duration: (s.duration * 1_000_000) / s.timescale,
        data: s.data,
      }),
    )
  }
}

export function decodeAudioSamples(decoder: AudioDecoder, samples: Sample[]): void {
  for (const s of samples) {
    if (!s.data) continue
    decoder.decode(
      new EncodedAudioChunk({
        type: 'key',
        timestamp: (s.cts * 1_000_000) / s.timescale,
        duration: (s.duration * 1_000_000) / s.timescale,
        data: s.data,
      }),
    )
  }
}

export function scheduleAudioBuffer(
  ctx: AudioContext,
  audio: AudioData,
  nextAudioStart: number,
): { start: number; nextStart: number } {
  if (ctx.state === 'suspended') {
    void ctx.resume().catch(() => {})
  }
  const numChannels = audio.numberOfChannels
  const numFrames = audio.numberOfFrames
  const buffer = ctx.createBuffer(numChannels, numFrames, audio.sampleRate)
  for (let ch = 0; ch < numChannels; ch++) {
    const channel = new Float32Array(numFrames)
    audio.copyTo(channel, { planeIndex: ch, format: 'f32-planar' })
    buffer.copyToChannel(channel, ch)
  }
  const src = ctx.createBufferSource()
  src.buffer = buffer
  src.connect(ctx.destination)
  const start = Math.max(ctx.currentTime, nextAudioStart)
  src.start(start)
  return { start, nextStart: start + buffer.duration }
}
