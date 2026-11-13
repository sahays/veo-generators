/** Ports and origins shared by the stub server, the Playwright config and the test fixtures. */
export const DEFAULT_STUB_PORT = 8787
/** `next dev` port used by the browser tests. */
export const APP_PORT = 5199
export const HOST = '127.0.0.1'

/** The stub API port: `STUB_PORT` when set (validated), else 8787. */
export function stubPort(): number {
  const raw = process.env.STUB_PORT
  if (!raw) return DEFAULT_STUB_PORT
  const port = Number(raw)
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`STUB_PORT must be an integer between 1 and 65535, got "${raw}"`)
  }
  return port
}

export const stubOrigin = (): string => `http://${HOST}:${stubPort()}`
export const APP_ORIGIN = `http://${HOST}:${APP_PORT}`
