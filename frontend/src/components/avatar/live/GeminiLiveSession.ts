// WebSocket client for the v2 live session. Connects to our backend's proxy
// endpoint (which terminates the upstream Vertex AI Gemini Live socket using
// service-account credentials), then relays/parses Gemini Live frames.
//
// The browser never sees an access token — the proxy is the only thing that
// authenticates with Vertex AI.

export type LiveMessage =
  | { type: 'connected' }
  | { type: 'disconnected'; code: number; reason: string }
  | { type: 'video-chunk'; mimeType: string; data: Uint8Array }
  | { type: 'audio-chunk'; mimeType: string; data: Uint8Array }
  | { type: 'transcript'; role: 'user' | 'model'; text: string; isFinal: boolean }
  | { type: 'error'; error: Error }

export class GeminiLiveSession extends EventTarget {
  private ws: WebSocket | null = null
  private connected = false

  /**
   * Open the WS connection. Resolves when the upstream `setupComplete` frame
   * arrives, rejects on socket close before then.
   */
  connect(url: string): Promise<void> {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(url)
      ws.binaryType = 'arraybuffer'
      this.ws = ws

      let settled = false
      const settle = (fn: () => void) => {
        if (!settled) {
          settled = true
          fn()
        }
      }

      ws.onopen = () => {
        // The backend sends the upstream `setup` frame on our behalf, so we
        // wait for setupComplete before declaring "connected".
      }
      ws.onmessage = (e) => this._handleMessage(e.data, () => settle(resolve))
      ws.onerror = () => {
        const err = new Error('WebSocket error')
        this._dispatch({ type: 'error', error: err })
        settle(() => reject(err))
      }
      ws.onclose = (e) => {
        this.connected = false
        this._dispatch({ type: 'disconnected', code: e.code, reason: e.reason })
        settle(() => reject(new Error(`WebSocket closed: ${e.code} ${e.reason}`)))
      }
    })
  }

  sendText(text: string) {
    // Live API expects realtimeInput.text — this matches the upstream
    // demo (gemini-live-client.ts in ffeldhaus/live-agent) and production's
    // current behaviour.
    this._send({ realtimeInput: { text } })
  }

  sendAudioChunk(pcm16: ArrayBuffer) {
    const data = bytesToBase64(new Uint8Array(pcm16))
    this._send({
      realtimeInput: {
        mediaChunks: [{ mimeType: 'audio/pcm;rate=16000', data }],
      },
    })
  }

  isConnected(): boolean {
    return this.connected
  }

  close() {
    try {
      this.ws?.close()
    } catch {}
    this.ws = null
    this.connected = false
  }

  private _send(obj: unknown) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return
    this.ws.send(JSON.stringify(obj))
  }

  private _handleMessage(raw: unknown, onSetup: () => void) {
    const text =
      typeof raw === 'string'
        ? raw
        : new TextDecoder().decode(raw as ArrayBuffer)
    let msg: any
    try {
      msg = JSON.parse(text)
    } catch {
      return
    }

    if (msg.setupComplete) {
      this.connected = true
      this._dispatch({ type: 'connected' })
      onSetup()
      return
    }

    if (msg.serverContent) {
      const sc = msg.serverContent
      const parts = sc.modelTurn?.parts as Array<any> | undefined
      if (parts) {
        for (const part of parts) {
          const inline = part.inlineData
          if (!inline?.data || !inline?.mimeType) continue
          const bytes = base64ToBytes(inline.data)
          if ((inline.mimeType as string).startsWith('video/')) {
            this._dispatch({
              type: 'video-chunk',
              mimeType: inline.mimeType,
              data: bytes,
            })
          } else if ((inline.mimeType as string).startsWith('audio/')) {
            this._dispatch({
              type: 'audio-chunk',
              mimeType: inline.mimeType,
              data: bytes,
            })
          }
        }
      }
      const ot = sc.outputTranscription
      if (ot?.text) {
        this._dispatch({
          type: 'transcript',
          role: 'model',
          text: ot.text,
          isFinal: !!ot.finished,
        })
      }
      const it = sc.inputTranscription
      if (it?.text) {
        this._dispatch({
          type: 'transcript',
          role: 'user',
          text: it.text,
          isFinal: !!it.finished,
        })
      }
    }

    if (msg.goAway) {
      this._dispatch({
        type: 'error',
        error: new Error(`goAway: ${msg.goAway.reason ?? 'session ending'}`),
      })
    }
  }

  private _dispatch(msg: LiveMessage) {
    this.dispatchEvent(new CustomEvent(msg.type, { detail: msg }))
  }
}

// ---- base64 helpers (browser, no deps) -----------------------------------

function bytesToBase64(bytes: Uint8Array): string {
  let binary = ''
  const chunk = 0x8000
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(
      null,
      Array.from(bytes.subarray(i, i + chunk)),
    )
  }
  return btoa(binary)
}

function base64ToBytes(b64: string): Uint8Array {
  const binary = atob(b64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  return bytes
}
